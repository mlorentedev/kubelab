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

- **`instance_termination_action = "DELETE"`** -- the API default is `STOP`,
  which leaves a `TERMINATED` shell behind after every preemption. DELETE keeps
  the MIG's reconciliation unambiguous and the project free of husks.

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

- **No autohealing in v1** -- with DELETE termination the MIG already restores
  target size on preemption without a health check. A probe that fires before
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


def _tf_text() -> str:
    """Every .tf file in the module, concatenated, comments stripped.

    Comments are stripped so a property discussed in a comment can never satisfy
    an assertion about the configuration -- the failure mode where a test passes
    because someone wrote *about* the setting instead of setting it.
    """
    parts = []
    for path in sorted(GCP_DIR.glob("*.tf")):
        text = path.read_text()
        text = re.sub(r"#[^\n]*", "", text)
        text = re.sub(r"//[^\n]*", "", text)
        parts.append(text)
    return "\n".join(parts)


def _networking() -> dict:
    return yaml.safe_load(COMMON_YAML.read_text())["networking"]


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

    def test_termination_action_is_delete_not_the_stop_default(self, tf: str) -> None:
        assert re.search(r'instance_termination_action\s*=\s*"DELETE"', tf), (
            "instance_termination_action defaults to STOP, which leaves a "
            "TERMINATED husk after every preemption; DELETE keeps the MIG's "
            "reconciliation unambiguous"
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

    # common.yaml key under networking.gcp  ->  Terraform variable name
    MIRRORED = {
        "region": "region",
        "machine_type": "machine_type",
        "image_family": "image_family",
        "image_project": "image_project",
        "disk_size_gb": "disk_size_gb",
        "disk_type": "disk_type",
        "network_tier": "network_tier",
        "hostname": "hostname",
        "k3s_version": "k3s_version",
    }

    @pytest.mark.parametrize("ssot_key,var_name", sorted(MIRRORED.items()))
    def test_default_matches_common_yaml(self, tf: str, ssot_key: str, var_name: str) -> None:
        gcp = _networking()["gcp"]
        assert ssot_key in gcp, f"networking.gcp is missing {ssot_key!r} -- the SSOT must carry it"
        default = _var_default(tf, var_name)
        assert default is not None, f'no variable "{var_name}" in the module'
        assert str(default) == str(gcp[ssot_key]), (
            f'variable "{var_name}" defaults to {default!r} but '
            f"networking.gcp.{ssot_key} is {gcp[ssot_key]!r}; common.yaml is the SSOT"
        )

    def test_boot_disk_is_pd_balanced(self, tf: str) -> None:
        assert _var_default(tf, "disk_type") == "pd-balanced", (
            "pd-balanced carries a 3,000 IOPS per-instance floor independent of "
            "size, which is what makes a 12 GB disk match gp3's flat 3,000 rather "
            "than regress on it"
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
            # `public` excludes ssh_public_key_path, and `_secret` names a Secret
            # Manager secret *identifier* rather than its value -- neither is a
            # credential, and marking them sensitive would hide harmless plan
            # output for nothing.
            if re.search(r"public|_secret\b", name, re.I):
                continue
            if re.search(r"key|secret|token|password", name, re.I):
                assert re.search(r"sensitive\s*=\s*true", body), (
                    f'variable "{name}" looks like a credential but is not marked '
                    f"sensitive = true; plan output and CI logs would echo it"
                )
