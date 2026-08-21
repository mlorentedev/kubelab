"""The rendered cloud-init must be valid YAML and must finish the hub.

`terraform validate` does not render `templatefile`, and `terraform plan` needs
credentials no runner has. So the only thing standing between a broken
cloud-config and an unattended boot failure is this file.

That gap is not theoretical here. This project already learned that
`# yamllint disable-file` is inert in a cloud-config -- the directive is honoured
only on line 1, and line 1 must be `#cloud-config` -- so the usual escape hatch
for "the linter does not understand this file" does not exist. A cloud-config
that fails to parse does not fail loudly either: cloud-init logs it to the serial
console and the instance comes up without ever having run the bootstrap, looking
healthy to the MIG the whole time.

The renderer below emulates Terraform's `templatefile` well enough to catch the
failures that matter: an unescaped `$${` that should have been literal, a
variable the module forgot to pass, and YAML that does not parse once the
substitutions land.
"""

from __future__ import annotations

import base64
import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
CLOUD_INIT = REPO / "infra/terraform/gcp/cloud-init.yml"
MAIN_TF = REPO / "infra/terraform/gcp/main.tf"

# Values shaped like the real ones. `spoke_servers` is JSON-in-a-string exactly
# as `jsonencode()` produces it, because the bootstrap parses it with jq.
def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


TEMPLATE_VARS = {
    "hostname": "gcp1",
    "deploy_user": "deployer",
    "ssh_public_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5 test@example",
    "timezone": "Europe/Madrid",
    "k3s_version": "v1.34.4+k3s1",
    "headscale_url": "https://vpn.kubelab.live",
    "headscale_api_key_secret": "gcp-headscale-api-key",
    "project_id": "kubelab-hub",
    "argocd_chart_version": "9.5.13",
    "helm_version": "v3.18.4",
    "managed_spokes": "staging",
    "spoke_servers": '{"staging":"https://100.64.0.11:6443"}',
    "secret_admin_hash": "argocd-admin-password-hash",
    "secret_oidc": "apps-services-security-authelia-oidc-client-secret-argocd",
    "secret_slack": "argocd-slack-webhook-url",
    "secret_github": "argocd-github-webhook-secret",
    # Computed, not pasted. A base64 literal here scans as a high-entropy string
    # and trips the secret detector -- and the reader cannot tell what it holds
    # without decoding it either. These are the shapes Terraform embeds.
    "argocd_values_b64": _b64("configs: {}\n"),
    "applications_b64": _b64("kind: Application\n"),
    "cluster_secret_tpl_b64": _b64("kind: Secret\n"),
}

_SENTINEL = "\x00ESCAPED_DOLLAR_BRACE\x00"


def _render(text: str, variables: dict[str, str]) -> str:
    """Emulate `templatefile`: `$${` is a literal, `${name}` substitutes.

    The escape is handled FIRST via a sentinel. Doing it in the other order
    would let a `$${foo}` be substituted as if it were `${foo}` -- which is the
    exact bug this test exists to catch, so getting it wrong here would make the
    test agree with the defect.
    """
    text = text.replace("$${", _SENTINEL)
    missing: set[str] = set()

    def sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in variables:
            missing.add(name)
            return match.group(0)
        return variables[name]

    text = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", sub, text)
    if missing:
        raise AssertionError(
            f"cloud-init.yml references template variables the test does not "
            f"supply: {sorted(missing)}. Either main.tf passes them and this "
            f"fixture is stale, or the template uses a variable nobody passes -- "
            f"which renders as the literal text and breaks the boot."
        )
    return text.replace(_SENTINEL, "${")


@pytest.fixture(scope="module")
def rendered() -> str:
    return _render(CLOUD_INIT.read_text(), TEMPLATE_VARS)


class TestItRendersToValidCloudConfig:
    def test_the_first_line_is_the_cloud_config_marker(self) -> None:
        # Without it cloud-init does not recognise the file at all and simply
        # does nothing -- no error, no bootstrap, an instance that looks fine.
        assert CLOUD_INIT.read_text().splitlines()[0] == "#cloud-config"

    def test_the_rendered_output_parses_as_yaml(self, rendered: str) -> None:
        try:
            parsed = yaml.safe_load(rendered)
        except yaml.YAMLError as exc:  # pragma: no cover - the failure IS the message
            pytest.fail(f"the rendered cloud-config is not valid YAML: {exc}")
        assert isinstance(parsed, dict), "cloud-config must render to a mapping"
        for key in ("write_files", "runcmd", "users"):
            assert key in parsed, f"the rendered cloud-config lost its {key!r} section"

    def test_every_template_variable_main_tf_passes_is_actually_used(self, rendered: str) -> None:
        """A variable passed but unused is dead weight; unused-but-named is a lie.

        The reverse direction (used but not passed) is caught by the renderer
        itself, which raises rather than leaving the literal in place.
        """
        block = re.search(r"user-data\s*=\s*templatefile\((.*?)\n    \}\)", MAIN_TF.read_text(), re.S)
        assert block, "could not find the templatefile call in main.tf"
        passed = set(re.findall(r"^\s*([a-z_]+)\s*=", block.group(1), re.M))
        used = set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", CLOUD_INIT.read_text()))
        unused = passed - used - {"user-data"}
        assert not unused, f"main.tf passes template variables cloud-init never uses: {sorted(unused)}"


class TestTheBootstrapFinishesTheHub:
    """Finding F1: a MIG recreate that stops at K3s is a hub that never returns."""

    def test_argo_cd_is_installed_not_merely_namespaced(self, rendered: str) -> None:
        assert "helm upgrade --install argocd" in rendered, (
            "cloud-init creates the argocd namespace but never installs Argo CD. "
            "aws1 gets away with that because a Spot stop/restart keeps its EBS "
            "volume; a MIG recreate has a fresh disk and nothing to keep."
        )

    def test_the_chart_version_is_pinned_in_the_install(self, rendered: str) -> None:
        assert re.search(r"--version\s+\"?9\.5\.13", rendered), (
            "the helm install does not pin --version. Unpinned, a preemption at "
            "3am is also a major upgrade of the management plane (#1209)."
        )

    def test_the_applications_and_cluster_secrets_are_applied(self, rendered: str) -> None:
        assert "argocd-applications.yaml" in rendered, "the Applications are never applied"
        assert "cluster-secret.yaml.tpl" in rendered, "no spoke cluster secret is ever created"

    def test_spoke_rbac_is_never_reapplied_from_the_hub(self, rendered: str) -> None:
        # The spoke's ServiceAccount and token are persistent SPOKE state, shared
        # with whichever hub is live. Re-applying the RBAC would delete and
        # recreate the ClusterRoles, opening a permission gap for the other hub.
        assert "spoke-rbac" not in rendered, (
            "cloud-init touches the spoke RBAC. Both hubs share one "
            "ServiceAccount, so re-applying it breaks whichever hub is live."
        )


class TestNoCredentialReachesArgvOrTheLog:
    """The bootstrap tees everything to /var/log, so this is where a leak lands."""

    def test_secrets_are_passed_to_helm_by_file_not_by_value(self, rendered: str) -> None:
        # `--set` puts the value in helm's argv, readable by `ps` for the life of
        # the install. `--set-file` passes a path.
        for line in rendered.splitlines():
            if "--set " in line and "secdir" in line:
                pytest.fail(f"a secret is passed by value on argv: {line.strip()}")
        assert "--set-file" in rendered, "secrets are not passed to helm as files"

    def test_no_fetched_secret_is_ever_echoed(self, rendered: str) -> None:
        # `sm_get` writes to a file; echoing its output would put the value in
        # the log the script tees to.
        assert not re.search(r"echo[^\n]*\$\(\s*sm_get", rendered), "a fetched secret is echoed into the bootstrap log"

    def test_the_secret_directory_is_on_tmpfs_and_removed(self, rendered: str) -> None:
        assert "/dev/shm/" in rendered, "secrets are staged on disk rather than tmpfs"
        assert rendered.count('rm -rf "$secdir"') >= 2, (
            "the secret directory is not removed on every path out of the install"
        )
