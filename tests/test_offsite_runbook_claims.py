"""The offsite runbook states what was measured, and every value it names is derived (BACKUP-057 AC5).

A recovery document is read on the day nothing else works, so a stale line in it
costs more than a stale line anywhere else. Until this test, the restore steps
still pointed at `kubelab-backups`, frozen since the 2026-10-08 migration: followed
as written, they would have restored data weeks old and reported success.

`kubelab-backups` still exists, so a whole-file search for it would be wrong: the
migration and watcher sections name it truthfully until it is deleted. The check is
scoped to the sections that tell an operator where backups are and how to read them.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

from toolkit.features.backup_destination import node_bucket
from toolkit.features.backup_node_credentials import access_key_path, restic_password_path, secret_key_path
from toolkit.features.r2_tfvars import LOCKED_PREFIXES

REPO = pathlib.Path(__file__).resolve().parent.parent
OFFSITE = REPO / "docs" / "runbooks" / "offsite-backup-restore.md"
DISASTER = REPO / "docs" / "runbooks" / "runbook-disaster-recovery.md"
COMMON = REPO / "infra" / "config" / "values" / "common.yaml"
SOPS = REPO / ".sops.yaml"

SHARED_BUCKET = "kubelab-backups"
SHARED_SECRETS = ("backup.r2.access_key_id", "backup.r2.secret_access_key", "backup.restic_password")
PATHS_SECTIONS = (
    "What exists",
    "Backing up on demand",
    "Restoring — normal case",
    "Restoring — the disaster case",
    "Rotation — the ordering matters",
)
COVERAGE_SECTION = "What the lock does and does not cover"


def _section(text: str, title: str) -> str:
    """The body of a `##` section, up to the next `##`. Raises if the heading is gone."""
    match = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert match, f"section {title!r} is missing"
    return match.group(1)


def _sops_recipients(sops_yaml: str) -> set[str]:
    return {
        recipient
        for rule in yaml.safe_load(sops_yaml)["creation_rules"]
        for group in rule.get("key_groups", [])
        for recipient in group.get("age", [])
    }


def sops_claim_problems(section: str, recipient_count: int) -> list[str]:
    """What the SOPS paragraph gets wrong for this many age recipients.

    With more than the operator's key, a recipient key is both a read path and a
    lock-removal path, and the runbook must say both. With only the operator's
    key, #1852 has landed and the warning must go, or it describes a hole that
    no longer exists.
    """
    has_ticket = "#1852" in section
    if recipient_count <= 1:
        return ["#1852 has landed: remove its warning"] if has_ticket else []
    missing = [
        claim
        for claim, needle in (
            ("the ticket", "#1852"),
            ("the read path", "read every node's history"),
            ("the lock-removal path", "remove a lock rule"),
            ("the file that decides it", ".sops.yaml"),
        )
        if needle not in section
    ]
    return [f"SOPS recipient case lacks {claim}" for claim in missing]


@pytest.fixture(scope="module")
def offsite() -> str:
    return OFFSITE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def backup() -> dict:
    return yaml.safe_load(COMMON.read_text(encoding="utf-8"))["backup"]


def test_the_runbook_names_every_node_bucket(offsite: str, backup: dict) -> None:
    section = _section(offsite, "What exists")
    missing = [node_bucket(node) for node in backup["sources"] if node_bucket(node) not in section]
    assert not missing, f"not named in 'What exists': {missing}"


def test_the_lock_section_names_the_four_prefixes_and_r(offsite: str, backup: dict) -> None:
    section = _section(offsite, COVERAGE_SECTION)
    for prefix in LOCKED_PREFIXES:
        assert f"`{prefix}`" in section, f"locked prefix {prefix} is not named"
    assert f"R = {backup['r2']['lock_retention_days']} days" in section


def test_the_lock_section_says_what_it_leaves_out(offsite: str) -> None:
    section = _section(offsite, COVERAGE_SECTION)
    for prefix in ("locks/", "index/"):
        assert f"`{prefix}`" in section, f"unlocked prefix {prefix} is not named"
    assert "restic repair index" in section, "no recovery for a node whose index was deleted"


def test_the_uncovered_cases_are_named(offsite: str) -> None:
    section = _section(offsite, COVERAGE_SECTION)
    assert "`cloudflare.r2_admin_token`" in section, "the admin token is not named"
    assert "no node" in section, "the runbook must say no node holds the admin token"
    assert "older than R" in section, "data older than R is not named"


def test_the_sops_recipient_case_matches_sops_yaml(offsite: str) -> None:
    recipients = _sops_recipients(SOPS.read_text(encoding="utf-8"))
    # The bullet alone: the admin token's bullet also says "remove a lock rule",
    # so reading the whole section would pass with the SOPS half deleted.
    bullets = _section(offsite, COVERAGE_SECTION).splitlines()
    bullet = next((line for line in bullets if line.startswith("- **A SOPS recipient key")), "")
    assert not sops_claim_problems(bullet, len(recipients))


def test_the_sops_claim_flips_when_the_ci_recipient_goes() -> None:
    complete = "#1852: .sops.yaml; read every node's history; remove a lock rule"
    assert sops_claim_problems(complete, 2) == []
    assert sops_claim_problems(complete, 1) == ["#1852 has landed: remove its warning"]
    assert sops_claim_problems("nothing about it", 1) == []
    assert len(sops_claim_problems("nothing about it", 2)) == 4


@pytest.mark.parametrize("title", PATHS_SECTIONS)
def test_no_operating_section_points_at_the_shared_bucket(offsite: str, title: str) -> None:
    section = _section(offsite, title)
    assert SHARED_BUCKET not in section
    stale = [secret for secret in SHARED_SECRETS if secret in section]
    assert not stale, f"{title!r} still reads {stale}"


def test_the_restore_uses_the_nodes_own_credentials(offsite: str) -> None:
    section = _section(offsite, "Restoring — normal case")
    for path in (access_key_path("$NODE"), secret_key_path("$NODE"), restic_password_path("$NODE")):
        assert path in section, f"the restore does not read {path}"
    assert 'kubelab-backup-$NODE"' in section, "the repository is not the node's bucket root"


def test_the_disaster_case_says_the_r2_pair_is_not_escrowed(offsite: str) -> None:
    section = _section(offsite, "Restoring — the disaster case")
    assert "KUBELAB_RESTIC_PASSWORD_<NODE>" in section
    assert "Cloudflare dashboard" in section, "the node's R2 pair is minted again, not read from the escrow"


def test_the_rebuild_runbook_points_at_the_node_buckets() -> None:
    text = DISASTER.read_text(encoding="utf-8")
    assert "kubelab-backup-<node>" in text
    assert SHARED_BUCKET not in text
    assert "`backup.r2.*`" not in text, "that glob is the shared pair, which reads no node's bucket root"
