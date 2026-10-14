"""Every `make <target>` a runbook tells you to run must exist.

A runbook is executed by someone under pressure, often at 3 AM, often by someone
who did not write it. A target that does not exist fails with
`No rule to make target`, which reads as a broken checkout rather than as a
broken instruction -- and sends the reader looking in the wrong place.

This is not hypothetical. `docs/runbooks/gcp-hub-bootstrap.md` §5 instructed
`make tf-gcp-secrets-sync` for months. THAT TARGET WAS NEVER BUILT; the sync
shipped as `make sync-secret-manager`. It was found by reading the runbook line
by line against the Makefile, which is exactly the manual check this replaces.

Scope is deliberately narrow: existence, not correctness. Whether a target does
what the surrounding prose claims is a question for the person running it. What
this closes is the failure that needs no judgement to detect and that nobody
performs by hand twice.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MAKEFILE = REPO / "Makefile"
DOCS = REPO / "docs"

_MAKE_CALL = re.compile(r"\bmake\s+((?:[A-Z_]+=\S+\s+)*)([a-z][a-z0-9-]*)")

# ONLY inside code -- fenced blocks and inline spans. Prose is excluded on
# purpose, and measuring showed why: an unscoped pattern reported `make the`,
# `make it`, `make a` and `make them` as missing targets across 59 documents,
# burying the handful of real ones. English uses the verb; a runbook instructs
# in code.
_FENCE = re.compile(r"```.*?```", re.S)
_INLINE = re.compile(r"`([^`\n]+)`")


def _declared_targets() -> set[str]:
    """Every target the Makefile declares, including multi-target rules."""
    text = MAKEFILE.read_text(encoding="utf-8")
    targets: set[str] = set()
    for line in text.splitlines():
        # A rule line: `name:` or `a b c:` at column 0, not a variable assignment
        m = re.match(r"^([A-Za-z0-9_./ -]+):(?!=)", line)
        if m:
            targets.update(m.group(1).split())
    # .PHONY lists names that are always real targets too.
    for m in re.finditer(r"^\.PHONY:\s*(.+)$", text, re.M):
        targets.update(m.group(1).split())
    targets.discard(".PHONY")
    return targets


# Instructions, not records. An ADR, a lesson and an audit report are all DATED
# accounts of what was true when they were written -- `lesson-256` naming
# `make argo-preview` documents the target that existed in May, and "correcting"
# it would falsify the record rather than help anyone.
#
# Only a document that tells the reader to RUN something has to be executable.
# Scoping to those took the ledger from 32 documents to zero, which is the
# measure of how much of the original finding was really a scoping mistake.
_INSTRUCTIONAL = ("runbooks", "troubleshooting")
# CLAUDE.md is instructional too, and read by every agent session: it told them
# to run `make deploy-vps`, a target that never existed, for months (#1748).
_AGENT_INSTRUCTIONS = REPO / "CLAUDE.md"


def _runbooks() -> list[Path]:
    docs = [path for prefix in _INSTRUCTIONAL for path in (DOCS / prefix).rglob("*.md")]
    return sorted([*docs, _AGENT_INSTRUCTIONS])


def _referenced(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    code = [m.group(0) for m in _FENCE.finditer(text)]
    code += [m.group(1) for m in _INLINE.finditer(_FENCE.sub("", text))]
    return {m.group(2) for chunk in code for m in _MAKE_CALL.finditer(chunk)}


# A DEBT LEDGER, and it may only shrink.
#
# 32 documents already name targets that do not exist -- `make deploy-vps` among
# them, which CLAUDE.md separately records as never having existed. Fixing all of
# them needs a judgement per entry (was it renamed? retired? never built?) and
# does not belong in the change that added this test.
#
# Freezing them here is the difference between debt that is visible and bounded
# and debt that keeps growing: a NEW stale reference fails immediately, and every
# fix must delete a line from this list. `test_the_ledger_only_shrinks` below
# stops the list itself from going stale.
#
# #1239 cleared the original 32: the instructional docs were corrected, and the
# dated records that made up the rest were never in scope. Kept as a mechanism, not
# as a list -- a NEW stale reference still has somewhere to be frozen if one
# ever needs to be.
#
# Keyed by (document, target), never by target alone (#2261): an exemption is
# justified by one document's text, so it holds in that document only. Keyed by
# name, `backup-pvc` exempted for CLAUDE.md's removal note would also have let a
# new runbook instruct `make backup-pvc` without a word from this test.
KNOWN_STALE: dict[tuple[str, str], str] = {
    # WHAT REMAINS, each with the reason it is still here. Not a list of names:
    # a name alone is what let 32 entries sit unexamined.
    #
    # -- Not make targets at all. The extractor reads code spans, and these live
    #    inside them while being English or commentary.
    ("docs/troubleshooting/ssl-certificates.md", "config"): "`# Fix: make config match mount` is a sentence",
    ("docs/runbooks/deployment.md", "deploy-prod"): "appears only in the note explaining it was retired",
    ("CLAUDE.md", "backup-pvc"): "appears only in the note recording its removal (OPS-023)",
    #
    # -- Retired with no replacement. Each needs the INSTRUCTION rewritten, not a
    #    target renamed, which is why they outlive a mechanical pass (DOCS-004, #836).
    ("docs/runbooks/deploy-new-k3s-service.md", "sops-check"): "no equivalent; now part of `make setup-sops`",
    ("docs/troubleshooting/build-failures.md", "clean"): "no equivalent; dev cleanup is `make dev-full-clean`",
    ("docs/troubleshooting/deployment.md", "clean"): "no equivalent; dev cleanup is `make dev-full-clean`",
    ("docs/troubleshooting/deployment.md", "status"): "no equivalent; nearest is `make k8s-status ENV=x`",
    ("docs/troubleshooting/quick-diagnostics.md", "status"): "no equivalent; nearest is `make k8s-status ENV=x`",
    ("docs/troubleshooting/environment-configuration.md", "env-validate"): "folded into `make config-generate`",
    ("docs/troubleshooting/quick-diagnostics.md", "env-validate"): "folded into `make config-generate`",
    ("docs/troubleshooting/networking-dns.md", "verify-dns"): "no equivalent; DNS checks live in `make test-e2e`",
    ("docs/troubleshooting/ssl-certificates.md", "verify-dns"): "no equivalent; DNS checks live in `make test-e2e`",
    ("docs/troubleshooting/deployment.md", "emergency-rollback"): "no equivalent; rollback is an Argo CD operation",
    ("docs/troubleshooting/deployment.md", "restore"): "no equivalent; see the restore runbook, not one target",
}


def _unexplained(doc: str, referenced: set[str], declared: set[str]) -> list[str]:
    """Targets `doc` names that neither exist nor carry an exemption for `doc`."""
    return sorted(t for t in referenced if t not in declared and (doc, t) not in KNOWN_STALE)


@pytest.mark.parametrize("doc", _runbooks(), ids=lambda p: str(p.relative_to(REPO)))
def test_every_make_target_a_doc_names_exists(doc: Path) -> None:
    rel = str(doc.relative_to(REPO))
    missing = _unexplained(rel, _referenced(doc), _declared_targets())
    assert not missing, (
        f"{rel} tells the reader to run targets that do not exist: "
        f"{missing}. A runbook naming a target nobody built fails as "
        "`No rule to make target`, which reads as a broken checkout rather than "
        "as a broken instruction."
    )


def test_an_exemption_holds_only_in_its_own_document() -> None:
    """#2261: the name exempted for one document is still caught in any other."""
    declared = _declared_targets()
    for doc, target in KNOWN_STALE:
        assert _unexplained(doc, {target}, declared) == []
        assert _unexplained("docs/runbooks/a-new-runbook.md", {target}, declared) == [target]


def test_the_ledger_only_shrinks() -> None:
    """An entry that is no longer stale must be deleted from the ledger.

    Without this the list would silently become a permission to be wrong: a
    target could be built, or a doc corrected, and the name would sit here
    suppressing a check that now has nothing to suppress.
    """
    declared = _declared_targets()
    referenced = {(str(d.relative_to(REPO)), t) for d in _runbooks() for t in _referenced(d)}

    now_real = sorted(entry for entry in KNOWN_STALE if entry[1] in declared)
    assert not now_real, f"these targets now EXIST — remove them from KNOWN_STALE: {now_real}"

    gone = sorted(entry for entry in KNOWN_STALE if entry not in referenced)
    assert not gone, f"the document no longer names the target — remove them from KNOWN_STALE: {gone}"


def test_the_extractor_finds_something() -> None:
    """Guard the guard: a regex that matched nothing would pass every doc above.

    The GCP bootstrap runbook is the densest caller in `docs/` and the one whose
    stale target motivated this test, so its absence means the pattern broke.
    """
    found = _referenced(DOCS / "runbooks" / "gcp-hub-bootstrap.md")
    assert len(found) >= 10, f"expected many `make` calls in the GCP runbook, found {found}"


def test_declared_targets_are_actually_parsed() -> None:
    """The other half: an empty target set would fail every doc, not pass it.

    Named separately so a parser regression reports itself rather than arriving
    as a wall of confusing per-document failures.
    """
    declared = _declared_targets()
    assert {"test", "lint", "deploy-argocd"} <= declared, (
        f"the Makefile parser missed well-known targets; it found {len(declared)}"
    )
