"""`gcp-tfvars` renders the SSOT, and deliberately not secrets.

`aws-tfvars` exists to inject two SOPS values -- `tailscale_authkey` and
`headscale_api_key` -- and delete the file afterwards. The GCP module needs
NEITHER: cloud-init reads its credentials from Secret Manager at boot, so
Terraform never carries one. Measured while building this: all 19 variables in
`infra/terraform/gcp/variables.tf` have a default and none is `sensitive`.

So the shape survives (a toolkit command, `-var-file`, removed after use) and the
content is redefined: this renders the values `common.yaml` already declares,
which is what the `MIRRORED` guard's own docstring said it would do.

The mapping is DERIVED where a rule exists and explicit only where none does --
every `networking.gcp` key whose name equals a Terraform variable is rendered by
computation, so nobody has to remember to add one.
"""

from __future__ import annotations

import pytest

from toolkit.features import gcp_tfvars


def _assigned(rendered: str, name: str) -> str:
    """The value assigned to `name`, independent of `=` alignment.

    Asserting on the exact spacing would couple every content test to the
    formatting rule, so a change to alignment would redden tests that are not
    about alignment. `TestTheOutputIsFormatClean` owns that property alone.
    """
    for line in rendered.splitlines():
        head, _, tail = line.partition("=")
        if head.strip() == name:
            return tail.strip()
    raise AssertionError(f"{name!r} is not assigned in:\n{rendered}")


@pytest.fixture
def config() -> dict:
    return {
        "k3s": {"api_port": 6443},
        "argocd": {
            "chart_version": "9.5.13",
            "helm_version": "v3.18.4",
            "spokes": {"staging": {"node": "ace1"}},
        },
        "networking": {
            "ssh_users": {"homelab": "manu", "cloud": "deployer"},
            "nodes": {"ace1": {"tailscale_ip": "100.64.0.11"}},
            "gcp": {
                "project_id": "kubelab-hub",
                "region": "europe-west4",
                "machine_type": "e2-small",
                "disk_size_gb": 12,
                "network_tier": "STANDARD",
                # not a Terraform variable -- must NOT be rendered
                "location": "cloud",
                "dashboard": {"url": "https://example"},
            },
        },
    }


class TestItRendersTheSSOTAndNothingElse:
    def test_a_networking_gcp_key_matching_a_variable_is_rendered(self, config: dict) -> None:
        out = gcp_tfvars.render(config, variable_names={"region", "machine_type"})
        assert _assigned(out, "region") == '"europe-west4"'
        assert _assigned(out, "machine_type") == '"e2-small"'

    def test_a_networking_gcp_key_with_no_matching_variable_is_skipped(self, config: dict) -> None:
        """`location` and `dashboard` are SSOT config the module has no input for.
        Rendering them makes `terraform plan` fail on an undeclared variable."""
        out = gcp_tfvars.render(config, variable_names={"region"})
        assert "location" not in out
        assert "dashboard" not in out

    def test_a_number_is_not_quoted(self, config: dict) -> None:
        out = gcp_tfvars.render(config, variable_names={"disk_size_gb"})
        assert _assigned(out, "disk_size_gb") == "12"

    def test_the_cross_section_pairs_are_rendered(self, config: dict) -> None:
        """Three variables mirror keys OUTSIDE `networking.gcp`. No rule derives
        them, so they are declared -- and that is the honest difference between
        "absent because computed" and "absent because forgotten"."""
        out = gcp_tfvars.render(
            config, variable_names={"argocd_chart_version", "helm_version", "deploy_user"}
        )
        assert _assigned(out, "argocd_chart_version") == '"9.5.13"'
        assert _assigned(out, "helm_version") == '"v3.18.4"'
        assert _assigned(out, "deploy_user") == '"deployer"'

    def test_spoke_servers_is_derived_not_restated(self, config: dict) -> None:
        """Through `argocd_spokes`, so this is not a fourth copy of the
        derivation #1215 tracks."""
        out = gcp_tfvars.render(config, variable_names={"spoke_servers"})
        assert "spoke_servers = {" in out
        assert 'staging = "https://100.64.0.11:6443"' in out


class TestTheOutputIsFormatClean:
    """A generated file that `terraform fmt -check` rewrites turns any repo-wide
    format gate into a race with whichever target last rendered it."""

    def test_assignments_are_aligned_the_way_terraform_fmt_aligns_them(self, config: dict) -> None:
        out = gcp_tfvars.render(config, variable_names={"region", "machine_type", "disk_size_gb"})
        cols = [line.index("=") for line in out.splitlines() if " = " in line and not line.startswith(" ")]
        assert len(set(cols)) == 1, f"top-level assignments are not aligned: columns {cols}"

    def test_a_block_assignment_is_left_unpadded(self, config: dict) -> None:
        """`terraform fmt` does not pad a multi-line block's own line, and it
        ends the alignment run. Padding it was the first attempt here and fmt
        rewrote it straight back -- so this asserts the measured behaviour, not
        the intuitive one."""
        out = gcp_tfvars.render(
            config, variable_names={"spoke_servers", "region", "argocd_chart_version"}
        )
        block = next(line for line in out.splitlines() if line.startswith("spoke_servers"))
        assert block == "spoke_servers = {", f"block assignment was padded: {block!r}"

    def test_nested_map_entries_are_aligned_within_their_own_block(self, config: dict) -> None:
        config["argocd"]["spokes"]["prod"] = {"node": "vps"}
        config["networking"]["vps"] = {"tailscale_ip": "100.64.0.2"}
        out = gcp_tfvars.render(config, variable_names={"spoke_servers"})
        inner = [line.index("=") for line in out.splitlines() if line.startswith("  ")]
        assert len(set(inner)) == 1, f"map entries are not aligned: columns {inner}"


class TestNoSecretIsEverRendered:
    """The property that separates this from `aws-tfvars`, asserted rather than
    assumed -- someone adding a sensitive variable later must trip this."""

    def test_the_render_set_contains_no_catalog_secret_path(self, config: dict) -> None:
        from toolkit.features.secrets_manager import SECRET_CATALOG

        rendered_paths = set(gcp_tfvars.SSOT_PATHS.values())
        catalog_paths = {s.key_path for s in SECRET_CATALOG}
        assert not (rendered_paths & catalog_paths), (
            "a SOPS-managed secret path is in the tfvars render set; GCP reads its "
            "credentials from Secret Manager and Terraform must carry none"
        )

    def test_no_decrypt_path_is_reachable_from_this_module(self) -> None:
        """It takes a plaintext config dict. There is no decrypt path to misuse,
        which is a stronger guarantee than remembering not to call one.

        Asserted over the module's IMPORTS AND CALLS via `ast`, never over its
        text. A grep for "sops" reads the docstring above -- which exists to
        explain why SOPS is absent -- and fails a module that is correct. That is
        the same class of defect as lesson-363 one mirror over: an assertion that
        cannot tell prose from code reports on whichever it happened to read.
        """
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(gcp_tfvars))

        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
                imported.update(f"{node.module}.{a.name}" for a in node.names)

        forbidden = ("sops", "secrets_manager", "credentials", "configuration")
        offenders = [m for m in imported if any(f in m for f in forbidden)]
        assert not offenders, f"gcp_tfvars reaches a decrypt path via {offenders}"

        called = {
            node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        }
        assert not {c for c in called if "decrypt" in c.lower() or "sops" in c.lower()}, (
            "gcp_tfvars calls a decrypt function"
        )


class TestItFailsRatherThanRenderingAHole:
    def test_a_missing_ssot_key_names_the_path(self, config: dict) -> None:
        del config["argocd"]["chart_version"]
        with pytest.raises(KeyError, match="argocd.chart_version"):
            gcp_tfvars.render(config, variable_names={"argocd_chart_version"})

    def test_an_empty_value_is_refused(self, config: dict) -> None:
        """An empty string renders as valid HCL and produces a plan against a
        blank project id -- the failure surfaces at apply, wearing a cloud
        provider's error message rather than this one."""
        config["networking"]["gcp"]["region"] = ""
        with pytest.raises(ValueError, match="region"):
            gcp_tfvars.render(config, variable_names={"region"})
