"""The GCP hub's Terraform module must carry the properties the ADR decided.

Static parse of `infra/terraform/gcp/*.tf`. No GCP, no credentials, no network --
it runs in `make test-fast` and on a hosted runner, which is the point: every
property asserted here is one whose absence is either expensive or silent, and a
`terraform plan` against a real project is not available at review time.

Each assertion below traces to a decision in
`docs/adr/adr-063-hub-cloud-provider-migration.md` and to the reason it was made.
The reasons matter more than the values, because a future edit that reverts one
of these will look locally reasonable:

- **`provisioning_model = "SPOT"`** -- the entire cost case ($9.57/mo against
  $12.75 on AWS). On-demand `e2-small` in europe-west4 is $13.43/mo for compute
  alone, so a silent revert here costs more than the migration saved.

- **No `instance_termination_action`** -- ADR-063 specified `DELETE`, and GCP
  refuses it: *"Spot virtual machines with termination action set to DELETE
  cannot be used with Managed Instance Groups."* Measured on the first real
  apply, after the decision had been made, documented, encoded and pinned by a
  test. A green suite asserted a configuration that could never exist.

- **A REGIONAL MIG with `target_size = 1`** -- GCP Spot VMs do not auto-restart,
  unlike the AWS persistent Spot request this replaces. Regional rather than
  zonal because #1066 was precisely "no capacity in the zone we picked": a
  regional MIG follows capacity instead of guessing at it. Zonal would still
  self-heal and would still reproduce that outage.

- **No `google_compute_address`** -- an external IP that is *reserved but not
  attached* costs $0.010/hr, **4x** the $0.0025/hr Spot-attached rate, and a MIG
  that recreates VMs is exactly the machine for orphaning reserved addresses.
  The hub needs no stable public address: every path in and out is Tailscale.
  This is the likeliest single route to the $15 budget cap, designed out rather
  than merely alerted on.

- **No autohealing in v1** -- the ADR justified this by DELETE termination
  restoring target size without a health check. That premise died with DELETE,
  and whether a MIG revives a STOPPED preempted Spot VM unaided is deliberately
  NOT asserted here from documentation. AC4 settles it by observation. A probe that fires before
  cloud-init's multi-minute bootstrap finishes produces a recreate loop on a Spot
  hub. Adding autohealing later requires `initial_delay_sec` no shorter than the
  measured bootstrap time, so the guard here is "not silently present".

- **No credential literal in any `.tf`** -- tfvars is rendered from SOPS and
  deleted after every use (`toolkit infra terraform gcp-tfvars`). A key pasted
  into a `.tf` would be committed to a public repository.

See `specs/GCP-001-hub-cloud-provider-migration/` for the full plan.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
GCP_DIR = REPO / "infra/terraform/gcp"
COMMON_YAML = REPO / "infra/config/values/common.yaml"


def _strip_comments(text: str) -> str:
    """Drop HCL line comments, leaving string literals intact.

    The regex form this replaces (`re.sub(r"//[^\n]*", "", text)`) also ate every
    URL in the module: `"https://100.64.0.11:6443"` became `"https:`. That is not
    cosmetic. `TestNoCredentialLiterals` scans this same text, so a credential
    embedded the way credentials usually are -- `https://user:token@host` -- was
    truncated away before the scan, and the guard reported clean having looked at
    a string that no longer contained what it was hunting for.

    One left-to-right pass tracking quote state is enough: HCL line comments open
    with `#` or `//` and run to end of line, and neither opens one inside a
    double-quoted string. Escapes are honoured so a `\\"` does not end the string.
    """
    out: list[str] = []
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < len(text):
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "#" or text.startswith("//", i):
            nl = text.find("\n", i)
            if nl == -1:
                break
            i = nl
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _tf_text() -> str:
    """Every .tf file in the module, concatenated, comments stripped.

    Comments are stripped so a property discussed in a comment can never satisfy
    an assertion about the configuration -- the failure mode where a test passes
    because someone wrote *about* the setting instead of setting it.
    """
    return "\n".join(_strip_comments(path.read_text()) for path in sorted(GCP_DIR.glob("*.tf")))


def _networking() -> dict:
    return yaml.safe_load(COMMON_YAML.read_text())["networking"]


def _common() -> dict:
    return yaml.safe_load(COMMON_YAML.read_text())


def _ssot(dotted: str) -> object:
    """Resolve a dotted path in common.yaml, failing loudly at the missing hop.

    The mirror map spans two top-level sections -- sizing under `networking.gcp`,
    the pinned versions under `argocd` -- so it holds full paths rather than bare
    keys under one assumed parent. A bare-key map cannot express the second
    section at all, which is how `argocd.chart_version` came to be documented as
    mirrored and checked by nothing.
    """
    node: object = _common()
    walked: list[str] = []
    for part in dotted.split("."):
        assert isinstance(node, dict) and part in node, (
            f"common.yaml has no {dotted!r} -- resolved as far as "
            f"{'.'.join(walked) or '<root>'}; the SSOT must carry it"
        )
        node = node[part]
        walked.append(part)
    return node


def _var_default(tf: str, name: str) -> str | None:
    """The declared default of a Terraform variable, or None.

    The module parameterises rather than hardcodes -- `disk_type = var.disk_type`
    -- so the effective value lives in the variable's default. Asserting against
    the literal in a resource block would pass only for a module that hardcoded,
    which is the worse design.
    """
    m = re.search(
        r'variable\s+"' + re.escape(name) + r'"\s*\{(.*?)\n\}',
        tf,
        re.S,
    )
    if not m:
        return None
    d = re.search(r'default\s*=\s*"?([^"\n]+)"?', m.group(1))
    return d.group(1).strip() if d else None


def _var_default_list(tf: str, name: str) -> list[str] | None:
    """The declared default of a LIST-typed Terraform variable, or None.

    `_var_default` cannot read one: its regex excludes the quote character, so
    `default = ["staging"]` comes back as `"["`. That is not a bug there -- it is
    built for scalars -- but it means a list mirror added to `MIRRORED` would
    fail while reporting a comparison nobody can act on.
    """
    block = re.search(r'variable\s+"' + re.escape(name) + r'"\s*\{(.*?)\n\}', tf, re.S)
    if not block:
        return None
    default = re.search(r"default\s*=\s*\[(.*?)\]", block.group(1), re.S)
    if not default:
        return None
    return re.findall(r'"([^"]+)"', default.group(1))


def _var_defaults_any(tf: str, name: str) -> list[str]:
    """Every default value of a variable, whether it is a scalar or a map.

    `_var_default` handles the scalar form. The Argo CD secret ids arrive as a
    map, and a checker that silently skipped maps would report a clean result
    while examining none of them.
    """
    scalar = _var_default(tf, name)
    if scalar and scalar.startswith("["):
        # A list default. Nothing in the access list should be one, and silently
        # returning [] would let a list of secret ids go unchecked while the test
        # reported clean -- so this is loud instead.
        raise AssertionError(f'variable "{name}" defaults to a list; the access list expects scalars or a map')
    if scalar and "{" not in scalar:
        return [scalar]
    block = re.search(r'variable\s+"' + re.escape(name) + r'"\s*\{(.*?)\n\}', tf, re.S)
    if not block:
        return []
    default = re.search(r"default\s*=\s*\{(.*?)\n  \}", block.group(1), re.S)
    if not default:
        return []
    return re.findall(r'=\s*"([^"]+)"', default.group(1))


@pytest.fixture(scope="module")
def tf() -> str:
    if not GCP_DIR.is_dir():
        pytest.fail(f"{GCP_DIR.relative_to(REPO)} does not exist")
    return _tf_text()


class TestSpotAndPreemption:
    """The cost case and the recovery model, which are the two load-bearing choices."""

    def test_provisioning_model_is_spot(self, tf: str) -> None:
        assert re.search(r'provisioning_model\s*=\s*"SPOT"', tf), (
            "the hub must run on Spot -- on-demand e2-small in europe-west4 is "
            "$13.43/mo for compute alone, more than the AWS setup this replaces"
        )

    def test_no_termination_action_is_set(self, tf: str) -> None:
        """This test asserted `DELETE` and the API refuses it.

            Spot virtual machines with termination action set to DELETE cannot
            be used with Managed Instance Groups.

        Measured on the first real apply, after the decision had been made in
        ADR-063, written into the module, and pinned here. A green test asserted
        a configuration that could never exist -- the test agreed with the ADR
        rather than with GCP, which is the failure mode a static guard has when
        nothing has ever run.

        Inverted deliberately rather than deleted: someone reading the ADR will
        try to restore DELETE, and this is what will stop them.
        """
        assert not re.search(r"instance_termination_action", tf), (
            "instance_termination_action is set again. A MIG rejects DELETE outright, "
            "and STOP is the default -- so any value here is either refused or noise."
        )

    def test_the_group_is_regional_not_zonal(self, tf: str) -> None:
        assert "google_compute_region_instance_group_manager" in tf, (
            "the MIG must be REGIONAL: #1066 was 'no Spot capacity in the zone we "
            "picked', and a regional group follows capacity across zones instead "
            "of guessing at one. A zonal group self-heals and still reproduces it."
        )
        assert "google_compute_instance_group_manager" not in tf.replace(
            "google_compute_region_instance_group_manager", ""
        ), "a zonal MIG must not also be declared"

    def test_target_size_is_exactly_one(self, tf: str) -> None:
        assert re.search(r"target_size\s*=\s*1\b", tf), "the hub is a singleton -- target_size must be 1"

    def test_autohealing_is_not_silently_enabled(self, tf: str) -> None:
        # v1 omits it deliberately (ADR-063 D2). If it is added, it MUST carry an
        # initial delay -- a probe firing before cloud-init finishes recreate-loops
        # a Spot hub, which is worse than the hang it would be there to catch.
        if "auto_healing_policies" in tf:
            assert re.search(r"initial_delay_sec\s*=\s*\d+", tf), (
                "auto_healing_policies without initial_delay_sec recreate-loops a "
                "Spot hub: the probe fires before cloud-init has installed K3s"
            )


class TestNetworkTierIsChosenNotInherited:
    """A cost-relevant default nobody decided is the defect, whichever value wins."""

    def test_network_tier_is_set_explicitly(self, tf: str) -> None:
        assert re.search(r"network_tier\s*=", tf), (
            "network_tier must be set on access_config, not left to the PREMIUM "
            "API default. The hub's egress is Argo CD polling two spokes forever, "
            "and the reported free allowances differ by roughly two orders of "
            "magnitude between the tiers -- against $0.43/mo of headroom that is "
            "the difference between free and not."
        )

    def test_network_tier_is_declared_in_the_ssot(self, tf: str) -> None:
        tier = _networking()["gcp"].get("network_tier")
        assert tier in {"STANDARD", "PREMIUM"}, (
            "networking.gcp.network_tier must be declared in common.yaml and be "
            "STANDARD or PREMIUM -- it is deployment policy with a cost "
            "consequence, so the SSOT owns it, not a Terraform default"
        )


class TestSSHExposure:
    """TCP/22 is open to the world for first-boot bootstrap, so narrow what it grants."""

    def test_project_ssh_keys_are_blocked(self, tf: str) -> None:
        assert re.search(r'block-project-ssh-keys\s*=\s*"TRUE"', tf), (
            "with TCP/22 open to 0.0.0.0/0 for bootstrap, project-level metadata "
            "SSH keys would grant a login on every instance the MIG ever creates "
            "-- an access path that widens silently as the project grows and that "
            "nothing in this module would reflect"
        )


class TestNoReservedAddress:
    """A reserved-but-unattached IP costs 4x the attached Spot rate."""

    def test_no_static_external_address_is_declared(self, tf: str) -> None:
        assert "google_compute_address" not in tf, (
            "the hub uses an EPHEMERAL external IP. A reserved address costs "
            "$0.010/hr while unattached -- 4x the $0.0025/hr Spot-attached rate -- "
            "and a MIG that recreates VMs orphans reserved addresses by design. "
            "The hub needs no stable public address: access is via Tailscale."
        )


class TestModuleDefaultsMatchTheSSOT:
    """Terraform defaults duplicate `networking.gcp`, so they can drift from it.

    Until `gcp-tfvars` renders these inputs from `common.yaml` (deferred to the
    follow-up that adds the Makefile targets), both places hold the same values
    and nothing but this test stops them diverging. `common.yaml` is the SSOT --
    a Terraform default that disagrees with it is the defect, in that direction.

    Deployment POLICY lives here too, not only sizing: `network_tier` has a cost
    consequence measured against $0.43/mo of headroom, and a policy value
    declared in one place and read from the other is exactly how the AWS hub's
    cost drifted unnoticed for two years (ADR-063 D4).
    """

    # dotted path in common.yaml  ->  Terraform variable name
    MIRRORED = {
        # Found while building `gcp-tfvars`: both of these carry a description
        # SAYING they mirror an SSOT key, and neither was compared. Same class as
        # the two pins one commit earlier -- three instances now, which makes it
        # the module's default failure mode rather than three oversights.
        "networking.gcp.project_id": "project_id",
        "networking.ssh_users.cloud": "deploy_user",
        "networking.gcp.region": "region",
        "networking.gcp.machine_type": "machine_type",
        "networking.gcp.image_family": "image_family",
        "networking.gcp.image_project": "image_project",
        "networking.gcp.disk_size_gb": "disk_size_gb",
        "networking.gcp.disk_type": "disk_type",
        "networking.gcp.network_tier": "network_tier",
        "networking.gcp.hostname": "hostname",
        "networking.gcp.k3s_version": "k3s_version",
        # The two pins. Their variable descriptions SAY they mirror these paths;
        # nothing checked it, so the operator path (`_deploy-argocd-helm`, which
        # reads the SSOT) and the unattended one (cloud-init, which reads the
        # Terraform default) could install different versions of Argo CD while
        # both truthfully claimed to be pinned.
        "argocd.chart_version": "argocd_chart_version",
        "argocd.helm_version": "helm_version",
    }

    # Same contract as MIRRORED, separate because the comparison differs: these
    # defaults are HCL lists, and `_var_default` returns "[" for one -- its regex
    # stops at the first quote. Folding them into the scalar test would compare
    # "[" against "['staging']" and fail with a message about the wrong thing.
    MIRRORED_LISTS = {
        # WHICH SPOKES THIS HUB WRITES TO. The invariant is that exactly one hub
        # writes to any given spoke at any moment; cloud-init installs a cluster
        # secret and an Application only for the spokes named here. A drift
        # between the two declarations does not fail -- it produces a second
        # controller on a spoke that already has one, which is the failure mode
        # with no error message.
        "networking.gcp.managed_spokes": "managed_spokes",
    }

    @pytest.mark.parametrize("ssot_key,var_name", sorted(MIRRORED.items()))
    def test_default_matches_common_yaml(self, tf: str, ssot_key: str, var_name: str) -> None:
        expected = _ssot(ssot_key)
        default = _var_default(tf, var_name)
        assert default is not None, f'no variable "{var_name}" in the module'
        assert str(default) == str(expected), (
            f'variable "{var_name}" defaults to {default!r} but {ssot_key} is {expected!r}; common.yaml is the SSOT'
        )

    @pytest.mark.parametrize("ssot_key,var_name", sorted(MIRRORED_LISTS.items()))
    def test_list_default_matches_common_yaml(self, tf: str, ssot_key: str, var_name: str) -> None:
        expected = _ssot(ssot_key)
        assert isinstance(expected, list), f"{ssot_key} is not a list in common.yaml; use MIRRORED instead"
        default = _var_default_list(tf, var_name)
        assert default is not None, f'variable "{var_name}" is absent or does not default to a list'
        assert default == [str(item) for item in expected], (
            f'variable "{var_name}" defaults to {default!r} but {ssot_key} is {expected!r}; common.yaml is the SSOT'
        )

    def test_boot_disk_is_pd_balanced(self, tf: str) -> None:
        assert _var_default(tf, "disk_type") == "pd-balanced", (
            "pd-balanced carries a 3,000 IOPS per-instance floor independent of "
            "size, which is what makes a 12 GB disk match gp3's flat 3,000 rather "
            "than regress on it"
        )


class TestCommentStrippingKeepsStrings:
    """The stripper feeds every other test here, so its bugs become theirs.

    Guarding it is not ceremony: the regex form it replaced silently truncated
    `"https://..."` to `"https:`, weakening the credential scan below without
    failing anything. A suite that reads a mangled copy of the file reports on
    the copy.
    """

    def test_a_url_keeps_its_double_slash(self) -> None:
        assert _strip_comments('a = "https://host:6443"') == 'a = "https://host:6443"'

    def test_a_hash_inside_a_string_survives(self) -> None:
        assert _strip_comments('a = "frag#ment"') == 'a = "frag#ment"'

    def test_a_real_line_comment_is_still_removed(self) -> None:
        """The stripper's original purpose, kept: a property discussed in a
        comment must never satisfy an assertion about the configuration."""
        assert "spot" not in _strip_comments("# provisioning_model = SPOT\nx = 1").lower()
        assert "spot" not in _strip_comments("// provisioning_model = SPOT\nx = 1").lower()

    def test_an_escaped_quote_does_not_end_the_string(self) -> None:
        assert _strip_comments('a = "he said \\"hi\\"" # gone').rstrip() == 'a = "he said \\"hi\\""'


class TestSpokeServersMatchTheSSOT:
    """`spoke_servers` holds literal Tailscale IPs; common.yaml holds the truth.

    `make register-spoke` derives each spoke's apiserver URL from
    `argocd.spokes.<env>.node` -> that node's `tailscale_ip` -> `k3s.api_port`.
    The Terraform default restates the RESULT of that derivation, so the two can
    disagree with nothing to say so, and the disagreement surfaces as a recreated
    hub whose cluster secret points at an address the spoke no longer answers on.

    Deriving the expectation here rather than restating the literals is the whole
    point: a test that hardcoded the same IPs would agree with the module and
    with nothing else. This one reads the SSOT, so drift makes it red -- which is
    what separates a guard from a fourth copy of the fact.

    The node lookup carries `networking`'s cloud/homelab asymmetry (`vps` sits at
    the top level, homelab nodes under `nodes`). That asymmetry is #1182 and is
    NOT smoothed here: this spec exists to measure what a provider change costs,
    and refactoring the shape mid-measurement destroys the reading.
    """

    def _expected(self) -> dict[str, str]:
        common = _common()
        net = common["networking"]
        port = common["k3s"]["api_port"]
        out: dict[str, str] = {}
        for env, spoke in common["argocd"]["spokes"].items():
            node = spoke["node"]
            entry = net[node] if node in net else net["nodes"][node]
            out[env] = f"https://{entry['tailscale_ip']}:{port}"
        return out

    def test_every_declared_spoke_matches_its_derivation(self, tf: str) -> None:
        declared = _var_defaults_any(tf, "spoke_servers")
        expected = self._expected()
        assert set(declared) == set(expected.values()), (
            f"spoke_servers defaults to {sorted(declared)} but common.yaml derives "
            f"{sorted(expected.values())} from argocd.spokes -> tailscale_ip -> "
            f"k3s.api_port. common.yaml is the SSOT."
        )

    def test_a_spoke_added_to_the_ssot_is_not_silently_missing(self, tf: str) -> None:
        """Set equality above is symmetric; this names the direction that hurts.

        A spoke declared in `argocd.spokes` and absent from `spoke_servers` gives
        a hub asked to manage an env whose apiserver URL it cannot template --
        failing inside cloud-init, unattended, after a preemption.
        """
        declared = _var_defaults_any(tf, "spoke_servers")
        for env, url in self._expected().items():
            assert url in declared, (
                f"argocd.spokes declares {env!r} but spoke_servers has no entry resolving to {url!r}"
            )


class TestTerraformBindsOnlyDeclaredSecrets:
    """The module's IAM grants and the catalog's tags describe the same fact.

    Terraform decides what the hub's service account may READ; the catalog
    decides what the sync WRITES. Nothing couples them, so they can disagree in
    two directions and neither shows up at plan time: a binding with no tag is a
    grant to something the sync never delivers (a permission nobody chose), and a
    tag with no binding is a secret the sync writes and cloud-init then cannot
    read -- surfacing unattended, after a preemption, at the worst moment.
    """

    def test_every_iam_bound_secret_is_tagged_in_the_catalog(self, tf: str) -> None:
        from toolkit.features.secrets_manager import (
            secret_manager_name,
            secrets_synced_to_secret_manager,
        )

        # The grants are a `for_each` over `local.hub_readable_secrets`, so the
        # local IS the access list. Reading the resource block alone would find
        # `each.value` and prove nothing.
        block = re.search(r"hub_readable_secrets\s*=\s*concat\((.*?)\n  \)", tf, re.S)
        assert block, "local.hub_readable_secrets is gone; the IAM grants can no longer be checked"
        body = block.group(1)

        assert "google_secret_manager_secret_iam_member" in tf, "no Secret Manager IAM grant in the module"
        assert 'role      = "roles/secretmanager.secretAccessor"' in tf, (
            "the grant is not secretAccessor; a broader role would let the hub write "
            "or manage secrets rather than only read the ones it boots from"
        )

        tagged = {secret_manager_name(s.key_path) for s in secrets_synced_to_secret_manager()}

        # Strip the `for env in var.managed_spokes :` clause before looking for
        # secret references. That one names the LOOP SOURCE, not a secret, and
        # excluding it structurally beats an allowlist of variable names -- an
        # allowlist grows silently and eventually excuses something real.
        secret_refs = re.sub(r"for\s+\w+\s+in\s+var\.[a-z_]+\s*:", "", body)

        # Every remaining `var.` reference resolves to a tagged secret.
        for var_name in re.findall(r"var\.([a-z_]+)", secret_refs):
            for value in _var_defaults_any(tf, var_name):
                assert value in tagged, (
                    f"the module grants secretAccessor on {value!r} (via var.{var_name}), "
                    f"but no SecretSpec carries sync_to_secret_manager=True for it. Either "
                    f"the sync never delivers it -- cloud-init would read nothing -- or the "
                    f"grant is wider than the design (ADR-063 D7)."
                )

        # The spoke entries are the OTHER input class and are deliberately absent
        # from the catalog: Kubernetes generates those credentials, so tagging
        # them would assert a SOPS origin they do not have. What is asserted here
        # is that they follow the same name mapping and are scoped to the spokes
        # this hub manages -- a hub that does not reconcile prod must not be able
        # to read prod's cluster credentials either.
        spoke_literals = re.findall(r'"(argocd-spokes-[^"]*)"', body)
        assert len(spoke_literals) == 2, f"expected token and ca per spoke, found {spoke_literals}"
        for literal in spoke_literals:
            assert literal.startswith("argocd-spokes-${env}-"), (
                f"{literal!r} does not follow the spoke naming rule, so it cannot be what the sync wrote"
            )
        assert "for env in var.managed_spokes" in body, (
            "the spoke grants are not scoped to managed_spokes; this hub could read "
            "credentials for a spoke another hub is reconciling"
        )


class TestNoCredentialLiterals:
    """tfvars is rendered from SOPS and deleted after use; nothing lands in git."""

    # Shapes of the credentials this module actually handles. A Headscale key is
    # the one that would matter most: it is long-lived and would let anyone join
    # the mesh. The repo is public, so a committed literal is an immediate leak.
    _SECRET_SHAPES = (
        (r"hskey-(auth|api)-", "a Headscale pre-auth or API key"),
        (r"AKIA[0-9A-Z]{16}", "an AWS access key id"),
        (r'private_key\s*=\s*"-----BEGIN', "an inline private key"),
    )

    def test_no_secret_literal_appears_in_any_tf_file(self) -> None:
        # Deliberately NOT using the comment-stripped text: a key pasted into a
        # comment is committed exactly as hard as one in a value.
        for path in sorted(GCP_DIR.glob("*.tf")):
            body = path.read_text()
            for pattern, what in self._SECRET_SHAPES:
                assert not re.search(pattern, body), (
                    f"{path.name} contains what looks like {what}. Credentials "
                    f"reach Terraform through `toolkit infra terraform gcp-tfvars`, "
                    f"which renders from SOPS and is deleted after every use."
                )

    def test_sensitive_variables_are_marked_sensitive(self, tf: str) -> None:
        # Mirrors the AWS module: a variable that carries a credential must be
        # `sensitive = true` so it is not echoed into plan output or CI logs.
        for block in re.findall(r'variable\s+"([^"]+)"\s*\{(.*?)\n\}', tf, re.S):
            name, body = block
            # `public` excludes ssh_public_key_path. The `_secret` / `_secret_ids`
            # suffix marks a variable holding a Secret Manager IDENTIFIER rather
            # than a value -- `headscale_api_key_secret` names a secret, it does
            # not contain one. Neither is a credential, and marking them
            # sensitive would hide harmless plan output for nothing.
            #
            # The suffix is the whole convention, so it is narrow on purpose: a
            # variable that actually carries a credential cannot accidentally
            # acquire this exemption without being renamed to claim it.
            if re.search(r"public|_secret\b|_secret_ids?\b", name, re.I):
                continue
            if re.search(r"key|secret|token|password", name, re.I):
                assert re.search(r"sensitive\s*=\s*true", body), (
                    f'variable "{name}" looks like a credential but is not marked '
                    f"sensitive = true; plan output and CI logs would echo it"
                )


class TestTheMigCanActuallyReplaceItsInstance:
    """A regional MIG rejects a `maxUnavailable` of 1, and the failure is late.

    Measured on the first real apply: eleven resources created, then

        Error 400: Fixed updatePolicy.maxUnavailable for regional managed
        instance group has to be either 0 or at least equal to the number of
        zones.

    The rule exists because a regional group spans every zone in the region. The
    tempting fix is the zone count -- 3 for europe-west4 -- which puts a literal
    next to a `region` that is a variable, and goes silently wrong the moment
    the region changes to one with a different number of zones. Wrong in the
    worst direction, too: too low a value blocks replacement entirely, on the
    exact path a MIG exists to perform.
    """

    def test_max_unavailable_is_derived_not_written_as_a_number(self, tf: str) -> None:
        """The zone count is the only legal non-zero value, and it is a fact
        about the region rather than about this design."""
        assert re.search(r"max_unavailable_fixed\s*=\s*length\(data\.google_compute_zones", tf), (
            "maxUnavailable must be derived from the region's zone count. A literal "
            "is a fact about europe-west4 sitting beside a `region` that is a variable, "
            "and it fails closed on any region with a different zone count."
        )

    def test_the_percent_form_is_not_used(self, tf: str) -> None:
        """Rejected by the API for this group: percent is only allowed for
        regional MIGs of size at least 10, and this one is a singleton."""
        assert "max_unavailable_percent" not in tf

    def test_the_zone_data_source_follows_the_region_variable(self, tf: str) -> None:
        """Pinning it to a literal region would reintroduce the same drift one
        level down -- a zone count read for a region the module does not use."""
        block = re.search(r'data\s+"google_compute_zones"\s+"available"\s*\{(.*?)\n\}', tf, re.S)
        assert block and "var.region" in block.group(1)

    def test_surge_stays_forbidden(self, tf: str) -> None:
        """The invariant the percent change must not quietly relax: two hubs
        must never exist at once, both registering the same Headscale
        given-name and both reconciling the same spokes."""
        assert re.search(r"max_surge_fixed\s*=\s*0", tf)
