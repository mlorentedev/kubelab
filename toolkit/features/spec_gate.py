"""CI-GATE-009: a PR may not close a spec's issue while leaving the spec active.

`CLAUDE.md` has long stated, as an assumption other workflows lean on, that "the
spec gate declines to merge a PR closing a spec's issue without archiving it".
Nothing implemented it. The only refusal that existed lived in `dotf spec
archive`, which fires *after* someone chooses to archive — so skipping the choice
skipped the enforcement, and a spec could be closed out without the gate ever
being consulted.

Four instances reached master before anyone noticed, and the fourth is the one
that shows the shape: #970 (via #1093), TOOL-016, TOOL-020, and IDP-031. In
IDP-031's case the *issue was still open*, so nothing anywhere was inconsistent
— the spec simply sat complete and unarchived indefinitely, because no state
transition ever asked the question.

This module answers it from the merge result rather than from the diff. If the
PR's tree still holds `specs/<feature-id>/` for an issue the PR closes, the
archive did not happen, however the branch got there — a rebase, a squash, or a
hand-applied patch cannot route around it. Comparing trees rather than diffs is
deliberate: the diff describes intent, the tree describes what merges.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: GitHub's own closing keywords. Matched case-insensitively, in the PR body,
#: exactly as GitHub matches them — a keyword this list misses is a spec that
#: closes silently, so the list is copied from GitHub's documentation rather
#: than trimmed to the ones this repo happens to use.
_CLOSING_KEYWORDS = (
    "close",
    "closes",
    "closed",
    "fix",
    "fixes",
    "fixed",
    "resolve",
    "resolves",
    "resolved",
)

_KEYWORDS_RE = "|".join(_CLOSING_KEYWORDS)

#: `Closes #123`, `Fixes owner/repo#123`, and the full-URL form GitHub also honours.
_CLOSES_RE = re.compile(
    rf"\b(?:{_KEYWORDS_RE})\b\s*:?\s+"
    r"(?:"
    r"https?://github\.com/(?P<url_repo>[\w.-]+/[\w.-]+)/issues/(?P<url_num>\d+)"
    r"|(?P<slug_repo>[\w.-]+/[\w.-]+)?#(?P<num>\d+)"
    r")",
    re.IGNORECASE,
)

#: The spec's own declaration of what tracks it, from `proposal.md` front-matter:
#: `issue: "mlorentedev/kubelab#988"`. Resolving the spec from the issue rather
#: than from the branch name is deliberate (#1096 AC2) — branch names are not
#: required to carry the feature id, and #1093's only did by convention.
_ISSUE_FIELD_RE = re.compile(r"^issue:\s*[\"']?(?P<repo>[\w.-]+(?:/[\w.-]+)?)?#(?P<num>\d+)", re.MULTILINE)

#: An escape hatch that leaves a record (#1096 AC4). A silent skip would rebuild
#: the hole this gate exists to close, so the reason is required and is echoed
#: into the failure output.
_EXCEPTION_RE = re.compile(r"^\s*Spec-archive-exception:\s*(?P<reason>\S.*?)\s*$", re.MULTILINE | re.IGNORECASE)


#: Sentinel for `undeclared_specs`: match whatever repo a spec declares, so the
#: report flags only specs whose issue cannot be parsed at all — a cross-repo
#: spec is resolvable, just not by this repo's gate.
_ANY_REPO = "*/*"


@dataclass(frozen=True)
class Violation:
    """One spec that this PR closes out without archiving."""

    feature_id: str
    issue: str
    reason: str

    def render(self) -> str:
        return f"  {self.feature_id} (closes {self.issue}): {self.reason}"


def closed_issues(pr_body: str, repo: str) -> set[int]:
    """Issue numbers in `repo` that `pr_body` closes on merge.

    Cross-repo references are ignored: a spec in this repo cannot be closed by
    an issue in another, and several specs here legitimately track
    `mlorentedev/knowledge#NNN`.
    """
    found: set[int] = set()
    for m in _CLOSES_RE.finditer(pr_body or ""):
        if m.group("url_num"):
            if m.group("url_repo") == repo:
                found.add(int(m.group("url_num")))
            continue
        slug = m.group("slug_repo")
        if slug is None or slug == repo:
            found.add(int(m.group("num")))
    return found


def spec_issue(proposal: Path, repo: str) -> int | None:
    """The issue number a spec declares, or None if it tracks another repo."""
    try:
        text = proposal.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _ISSUE_FIELD_RE.search(text)
    if m is None:
        return None
    declared = m.group("repo")
    if repo != _ANY_REPO and declared is not None and declared not in (repo, repo.split("/")[-1]):
        return None
    return int(m.group("num"))


def declared_exception(pr_body: str) -> str | None:
    """The reason given for skipping the gate, if the PR declares one."""
    m = _EXCEPTION_RE.search(pr_body or "")
    return m.group("reason") if m else None


def undeclared_specs(specs_root: Path) -> list[str]:
    """Active specs whose `proposal.md` declares no `issue:` at all.

    These are the gate's blind spot: with nothing to resolve, a PR closing their
    issue passes silently — the same can't-fail shape this module exists to
    remove, one level up. Reported rather than treated as a violation, because
    the fix is to declare the issue on the spec, not to change the PR that
    tripped over it.

    `spec init` is gated on an open issue, so a spec without one either predates
    that gate or went around it. Four did, found while writing this module.
    """
    if not specs_root.is_dir():
        return []
    missing = []
    for folder in sorted(p for p in specs_root.iterdir() if p.is_dir() and p.name != "archive"):
        proposal = folder / "proposal.md"
        if not proposal.is_file():
            continue
        # Deliberately `spec_issue`, the same function the gate resolves with,
        # rather than a cheaper "does the file contain `issue:`" test. The first
        # draft used the cheap one and reported four blind specs while a fifth —
        # BACKUP-044, declaring the bare `kubelab#1056` the regex then rejected —
        # was invisible to BOTH the gate and the report of what the gate cannot
        # see. A blind-spot report with its own blind spot is worse than none.
        if spec_issue(proposal, _ANY_REPO) is None:
            missing.append(folder.name)
    return missing


def check(
    pr_body: str,
    specs_root: Path,
    repo: str = "mlorentedev/kubelab",
) -> list[Violation]:
    """Every spec this PR closes out while leaving it outside `specs/archive/`.

    Reads the tree it is given — in CI that is the PR's merge result, so a spec
    still present under `specs/<id>/` means the archive is not in this PR,
    regardless of how the branch was assembled.
    """
    closing = closed_issues(pr_body, repo)
    if not closing:
        return []

    archive_root = specs_root / "archive"
    violations: list[Violation] = []

    # Active folders: closing the issue without moving the folder is the failure.
    for folder in sorted(p for p in specs_root.iterdir() if p.is_dir() and p.name != "archive"):
        number = spec_issue(folder / "proposal.md", repo)
        if number is None or number not in closing:
            continue
        if not (archive_root / folder.name).is_dir():
            violations.append(
                Violation(
                    folder.name,
                    f"#{number}",
                    f"still at specs/{folder.name}/ — this PR closes its issue but does "
                    f"not move it to specs/archive/{folder.name}/",
                )
            )

    # Archived folders are scanned separately, not as an else-branch of the loop
    # above: after a correct archive the active folder is *gone*, so a review
    # check hanging off the active listing would never run — which is how the
    # first draft of this gate passed a spec with no review.md at all.
    if archive_root.is_dir():
        for folder in sorted(p for p in archive_root.iterdir() if p.is_dir()):
            number = spec_issue(folder / "proposal.md", repo)
            if number is None or number not in closing:
                continue
            if not (folder / "review.md").is_file():
                violations.append(
                    Violation(
                        folder.name,
                        f"#{number}",
                        f"archived without specs/archive/{folder.name}/review.md — no "
                        "independent review signed this spec",
                    )
                )

    return violations


def report(
    violations: list[Violation],
    exception: str | None,
    undeclared: list[str] | None = None,
) -> tuple[str, int]:
    """Human-readable outcome and the exit code CI should use.

    `undeclared` never changes the exit code. A spec that forgot to name its
    issue is not the fault of whatever PR happened to run the gate, and failing
    strangers' builds for it is how a useful check gets disabled.
    """
    blind = ""
    if undeclared:
        blind = (
            "\n\nNote — specs this gate cannot see, because their proposal.md declares\n"
            "no `issue:` field. A PR closing their issue would pass silently:\n"
            + "\n".join(f"  {name}" for name in undeclared)
        )

    if not violations:
        return ("No spec closes out unarchived in this PR." + blind, 0)

    body = "\n".join(v.render() for v in violations)
    if exception is not None:
        return (
            "Spec gate WAIVED by an explicit declaration in the PR body.\n"
            f"  Reason: {exception}\n"
            "Findings it would otherwise have raised:\n"
            f"{body}\n"
            "Recorded rather than skipped silently — the waiver is in the merge record." + blind,
            0,
        )
    return (
        "Spec gate FAILED — this PR closes a spec's issue without archiving the spec.\n"
        f"{body}\n"
        "\n"
        "Fix by archiving the spec in this PR:\n"
        "    dotf spec archive <feature-id>\n"
        "which requires a passing pooled review (specs/archive/<id>/review.md).\n"
        "Run it with `dotf spec review <feature-id>` first; the reviewer must not\n"
        "be the model that implemented the change.\n"
        "\n"
        "If archiving genuinely does not belong in this PR, say so in the body:\n"
        "    Spec-archive-exception: <why>\n"
        "which passes the gate and leaves the reason in the merge record." + blind,
        1,
    )
