"""The hub's day-2 playbook must agree with what its cloud-init actually boots.

`infra/ansible/playbooks/provision-gcp1.yml` asserts a hardware contract --
swap and RAM floors -- that `infra/terraform/gcp/cloud-init.yml` is what
satisfies. The two are declarations of the same contract in different files,
and before this test nothing compared them. Lowering the cloud-init swap
directive below the playbook's floor produces a green review and a provision
run that fails against a live node; on a MIG, which recreates rather than
restarts, it fails on EVERY recreate.

That failure mode is this spec's recurring one, named in its own commits: a
description saying it mirrors something is not a guard. Three instances were
found in two commits on this branch, each documented and compared by nothing.

The second property here is narrower and comes from how the file was written.
`provision-gcp1.yml` was derived from `provision-aws1.yml`, so a surviving
`config.networking.aws.*` reference is the live hazard: it would build the TLS
SAN and the kubeconfig's API address from the node being DECOMMISSIONED, and
both would look entirely plausible in review -- a working hub kubeconfig
pointing at the wrong machine.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
PLAYBOOKS = REPO / "infra/ansible/playbooks"
GCP_PLAYBOOK = PLAYBOOKS / "provision-gcp1.yml"
AWS_PLAYBOOK = PLAYBOOKS / "provision-aws1.yml"
CLOUD_INIT = REPO / "infra/terraform/gcp/cloud-init.yml"


def _plays(playbook: Path) -> list[dict]:
    return yaml.safe_load(playbook.read_text(encoding="utf-8"))


def _assert_floor(playbook: Path, fact: str) -> int:
    """The numeric floor a playbook's `assert` imposes on an ansible fact.

    Raises rather than returning a default: an assertion that has been renamed
    or removed must fail this test loudly, not be read as a floor of zero.
    """
    pattern = re.compile(rf'ansible_facts\["{fact}"\]\s*>=\s*(\d+)')
    for play in _plays(playbook):
        for task in play.get("pre_tasks", []) or []:
            for clause in (task.get("assert") or {}).get("that", []) or []:
                found = pattern.search(str(clause))
                if found:
                    return int(found.group(1))
    raise AssertionError(f"{playbook.name} no longer asserts a floor on {fact!r}")


def _cloud_init_swap_mib() -> int:
    """The swap the cloud-init `swap:` directive provisions, in MiB.

    Regex rather than a YAML load: the file is a Terraform templatefile whose
    runcmd block carries bash with `${...}` and bare colons, so parsing it as
    YAML is not reliably possible.
    """
    text = CLOUD_INIT.read_text(encoding="utf-8")
    block = re.search(r"^swap:\n(?:[ \t]+.*\n)+", text, flags=re.M)
    assert block, "cloud-init.yml no longer declares a `swap:` directive at all"
    size = re.search(r"^\s+size:\s*(\d+)", block.group(0), flags=re.M)
    assert size, "the `swap:` directive no longer declares a size"
    return int(size.group(1)) // (1024 * 1024)


class TestTheHardwareContractIsCompared:
    def test_cloud_init_provisions_at_least_the_swap_the_playbook_demands(self) -> None:
        floor = _assert_floor(GCP_PLAYBOOK, "swaptotal_mb")
        provisioned = _cloud_init_swap_mib()
        assert provisioned >= floor, (
            f"cloud-init provisions {provisioned}MiB of swap but provision-gcp1.yml "
            f"refuses to continue below {floor}MB. Every `make provision NODE=gcp1` "
            "would fail against a live node, and on a MIG that repeats on every "
            "recreate."
        )

    def test_both_hubs_hold_the_same_memory_floor(self) -> None:
        """RELIAB-009's minimum is a property of Argo CD, not of a provider.

        The 1GB predecessor OOMed on every Helm upgrade. If gcp1's floor drifts
        below aws1's, the migration has quietly relaxed the bar that incident
        set rather than carried it across.
        """
        assert _assert_floor(GCP_PLAYBOOK, "memtotal_mb") == _assert_floor(AWS_PLAYBOOK, "memtotal_mb"), (
            "the two hub playbooks disagree on the minimum RAM for the same workload"
        )


class TestItDoesNotStillPointAtTheNodeItReplaces:
    def test_no_reference_survives_to_the_aws_networking_section(self) -> None:
        text = GCP_PLAYBOOK.read_text(encoding="utf-8")
        # Comments legitimately discuss aws1 -- the header contrasts the two
        # hubs deliberately. Only live config lookups are the hazard.
        live = [line for line in text.splitlines() if "networking.aws" in line and not line.lstrip().startswith("#")]
        assert not live, (
            "provision-gcp1.yml still reads networking.aws.*, so it would build "
            f"the hub's TLS SAN or kubeconfig from the decommissioned node: {live}"
        )

    @pytest.mark.parametrize("consumer", ["_k3s_tls_san", "k3s_api_address"])
    def test_the_magicdns_consumers_read_the_gcp_section(self, consumer: str) -> None:
        """Both derive from the same SSOT key, and both are silent when wrong.

        A TLS SAN for the wrong host yields certificate errors that read as a
        broken mesh; an API address for the wrong host yields a kubeconfig that
        works right up until aws1 is destroyed.
        """
        text = GCP_PLAYBOOK.read_text(encoding="utf-8")
        after = text.split(consumer, 1)
        assert len(after) == 2, f"{consumer} is gone from provision-gcp1.yml"
        assert "config.networking.gcp.tailscale_dns" in after[1].split("\n\n")[0], (
            f"{consumer} no longer resolves from networking.gcp.tailscale_dns"
        )

    def test_the_play_targets_the_host_the_ssot_names(self) -> None:
        common = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())
        hostname = common["networking"]["gcp"]["hostname"]
        targets = {play["hosts"] for play in _plays(GCP_PLAYBOOK)}
        assert targets == {hostname}, (
            f"the playbook targets {targets} but the SSOT names the hub {hostname!r}; "
            "the generated inventory has no other name to match"
        )
