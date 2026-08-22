"""`make backup-coverage` asks R2, not the nodes — BACKUP-044 AC1.

The criterion's wording is the design constraint: *"by listing snapshots from a
machine that is not the source node. Reading the playbook is not verification."*
Every other backup control runs ON the node it checks, so it shares that node's
fate — a node that is broken, lying or gone reports nothing, or reports what it
believes. This one asks the destination, and works with the homelab powered off,
which is precisely when half the fleet cannot answer for itself.

The tests below are about the ONE thing that cannot be inferred safely: which
repository name in R2 belongs to which node in `backup.sources`. They are not
the same string, and getting it wrong reports a healthy node as UNCOVERED.
"""

from __future__ import annotations

import pathlib
from unittest.mock import patch

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
COMMON = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())


def _repository_name(node: str) -> str:
    from toolkit.features.backup_destination import repository_name

    class _StubCM:
        def get_merged_config(self) -> dict:
            return COMMON

    return repository_name(_StubCM(), node)


@pytest.mark.parametrize("node", sorted(COMMON["backup"]["sources"]))
def test_the_repository_name_is_the_hostname_from_the_ssot(node: str) -> None:
    """Read, never derived. The prefix is already in the value.

    `node_backup_r2_repository` is built from `inventory_hostname`, and the
    inventory is not uniformly prefixed: `networking.vps.hostname` is already
    `kubelab-vps` while every homelab node is its own bare name.

    An earlier revision of this code inferred the prefix from the node's
    position in `common.yaml` — cloud nodes are siblings of `networking.nodes`,
    homelab nodes are members — and produced `kubelab-kubelab-vps`. The report
    then called the VPS UNCOVERED while a nightly backup sat in R2. A rule that
    reproduces a value already in the SSOT is a second declaration, and this is
    what the second one costs.
    """
    networking = COMMON["networking"]
    nodes = networking.get("nodes", {})
    entry = nodes.get(node) if node in nodes else networking.get(node, {})
    expected = (entry or {}).get("hostname")
    assert expected, f"{node} has no hostname in common.yaml; the report cannot name its repository"
    assert _repository_name(node) == expected, (
        f"{node}: repository resolved to {_repository_name(node)!r}, but the SSOT says "
        f"{expected!r}. A mismatch reports a node with a healthy backup as UNCOVERED."
    )


def test_the_vps_is_the_case_that_breaks_a_naive_rule() -> None:
    """Pinned as a literal, deliberately, and it is the only one that is.

    The test above compares the function against `common.yaml`, so both sides
    move together if the SSOT changes — correct, and it would not have caught
    the double-prefix bug on its own, because the bug was in the *derivation*
    rather than in the source.

    This one states the answer measured against the live bucket on 2026-08-22:

        PRE beelink/   PRE kubelab-vps/   PRE rpi3/   PRE rpi4/
    """
    assert _repository_name("vps") == "kubelab-vps", (
        "the VPS repository is `kubelab-vps` in R2 — one prefix, already present "
        "in networking.vps.hostname. Adding one produces `kubelab-kubelab-vps`; "
        "stripping it produces `vps`. Both report a covered node as uncovered."
    )
    assert _repository_name("rpi3") == "rpi3", "homelab nodes carry no prefix"


def test_every_declared_node_can_be_named() -> None:
    """A node in `backup.sources` with no resolvable hostname is unreportable.

    It would be skipped or misnamed, and the report would be quietly narrower
    than the fleet — the failure this whole command exists to make impossible.
    """
    unnamed = [n for n in sorted(COMMON["backup"]["sources"]) if not _repository_name(n)]
    assert not unnamed, f"these declared nodes resolve to no repository name: {unnamed}"


def test_an_uncovered_node_fails_the_command() -> None:
    """The exit code is what a cron or a human reads. It must not be advisory.

    Verified by driving the real function with a stub `run` that answers as
    restic does for a repository that was never initialised.
    """
    from toolkit.features import backup_destination

    def _run(argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
        if argv[:2] == ["restic", "version"]:
            return 0, "restic 0.19.1", ""
        return 1, "", "Fatal: unable to open config file: Stat: The specified key does not exist."

    class _StubCM:
        def get_merged_config(self) -> dict:
            return COMMON

        def get_secret_by_path(self, path: str) -> str:
            return "stub-password"

    with patch.object(backup_destination, "load_credentials", return_value={}):
        assert backup_destination.coverage(cm=_StubCM(), run=_run) is False, (
            "a node with no repository must make the command exit non-zero; an "
            "advisory report of a missing backup is the silence AC1 exists to end"
        )
