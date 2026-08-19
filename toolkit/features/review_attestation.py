"""Report whether a pull request was actually reviewed (TOOL-021, #1140).

The gate answers ONE question: did a review happen? Never who performed it, and
never whether it was any good. A human review attests exactly as well as a bot's.

It exists because a reviewer reports its own status, and a skipped review is not
a failed one. Measured across 2026-08-17/19, eleven PRs in this repository
carried a green reviewer check with no review behind it, and seven of them
merged. Two reviewers run here and BOTH fail open, independently — so the defect
is not one vendor's status lying, and a third reviewer that also failed open
would add a third way to see green and no new way to be stopped.

States, decided by CONTENT rather than by check status:

    attested   a review happened (a member, or a declared reviewer)   -> 0
    exempt     the diff carries nothing a review could act on         -> 0
    disclosed  no review, but the escape is declared in full          -> 0
    declined   a reviewer said it could not review                    -> 1
    pending    no reviewer output yet                                 -> 1
    unreadable the PR state could not be determined                   -> 2

`declined` and `pending` both refuse and are reported distinctly on purpose.
Telling a PR that carries three reviews "no reviewer output yet" is a false
statement, and a gate built so that green means reviewed cannot afford to be
wrong about why it went red.

Anything unreadable exits 2, never 0: for a gate, "I could not determine" must
never be delivered as "fine" — that IS the defect being fixed here, and
reproducing it in the fix would be absurd.

**No reviewer is named anywhere in this module, and `tests/` enforces it.** Every
vendor-specific string lives in `harness/review-attestation.json`, including the
prose explaining each one. A vendor name here is how "the registry is
authoritative" quietly stops being true.

Ported from mlorentedev/dotfiles `scripts/check-review-attestation.sh` at
2bac1c5. Reimplemented in the toolkit rather than as a shell script because this
repository's other gate already works that way, for a stated reason: the logic
and its tests live together, so the negative case runs on every commit instead
of needing a live PR to exercise.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Associations that mean "belongs to this repository". CONTRIBUTOR is
#: deliberately absent: it is granted by having had a commit merged, which a bot
#: holds as easily as a person, and including it would reopen the defect this
#: check closes — a shared automation login attesting for a PR nobody read.
_MEMBER_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})

DEFAULT_REGISTRY = Path("harness/review-attestation.json")


class RegistryError(Exception):
    """The reviewer registry is missing, unparseable, or the wrong shape."""


class PayloadError(Exception):
    """The PR payload could not be read or is not the expected shape."""


@dataclass(frozen=True)
class Verdict:
    """The gate's answer. `ok` maps to exit 0; `state` is never collapsed."""

    state: str  # attested | exempt | disclosed | declined | pending
    ok: bool
    detail: str


def _norm(login: str | None) -> str:
    """Fold a login for comparison.

    The two GitHub APIs disagree about bot logins: GraphQL returns the bare
    name, REST appends a `[bot]` suffix. Matching raw would make the verdict
    depend on which API produced the payload, so a fixture written from one
    would prove nothing about the other.

    Stated as the rule rather than with an example login on purpose — naming one
    here would put a vendor string in this module, which `tests/` forbids and
    which is how the registry quietly stops being the authority.
    """
    value = (login or "").strip().casefold()
    return value[: -len("[bot]")] if value.endswith("[bot]") else value


def load_registry(path: Path) -> dict[str, Any]:
    """Read and shape-check the reviewer registry, failing closed.

    Shape, not just syntax. Valid JSON of the wrong shape parses fine and then
    produces empty strings downstream, which classify as "nobody declined" and
    "no escape configured" — a malformed registry would make the gate quietly
    more permissive, the one direction it must never fail in.
    """
    if not path.is_file():
        raise RegistryError(f"reviewer registry not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"reviewer registry is not readable JSON: {path} ({exc})") from exc

    reviewers = data.get("reviewers") if isinstance(data, dict) else None
    escape = data.get("escape") if isinstance(data, dict) else None
    shape_ok = (
        isinstance(data, dict)
        and isinstance(reviewers, list)
        and len(reviewers) > 0
        and all(
            isinstance(r, dict)
            and isinstance(r.get("login"), str)
            and r["login"]
            and isinstance(r.get("declined_markers"), list)
            and all(isinstance(m, str) and m for m in r["declined_markers"])
            and isinstance(r.get("review_markers"), list)
            and all(isinstance(m, str) and m for m in r["review_markers"])
            for r in reviewers
        )
        and isinstance(escape, dict)
        and isinstance(escape.get("label"), str)
        and escape["label"]
        and isinstance(escape.get("section"), str)
        and escape["section"]
    )
    if not shape_ok:
        raise RegistryError(
            "reviewer registry is valid JSON but the wrong shape (needs "
            "reviewers[].login, reviewers[].declined_markers[], "
            f"reviewers[].review_markers[], escape.label, escape.section): {path}"
        )
    return data


def _rationale_under(body: str, section: str) -> str:
    """Text between `section` and the next `## ` heading, whitespace stripped.

    An empty section is not a disclosure. The escape exists to put the reason in
    the durable record; a heading with nothing under it records the intent to
    disclose and discloses nothing.
    """
    lines = [line.rstrip() for line in (body or "").replace("\r", "").split("\n")]
    try:
        start = lines.index(section)
    except ValueError:
        return ""
    rest = lines[start + 1 :]
    for i, line in enumerate(rest):
        if line.startswith("## "):
            rest = rest[:i]
            break
    return "".join("".join(rest).split())


def classify(pr: dict[str, Any], registry: dict[str, Any]) -> Verdict:
    """Decide the PR's review state. Pure — no IO, no network."""
    if not isinstance(pr, dict):
        raise PayloadError("PR payload is not an object")

    author = _norm((pr.get("author") or {}).get("login"))
    reviewers = registry["reviewers"]
    declared = {_norm(r["login"]) for r in reviewers}

    # --- attested by a review? -------------------------------------------------
    # A review attests when its author is not the PR author AND that author is
    # either a member of this repository or a DECLARED reviewer.
    #
    # The second half matters because an identity can be SHARED: every workflow
    # here posts under one automation login, so counting "any login that is not
    # mine" would let a labeler or a release job attest for a PR nobody read. A
    # person's identity is not shared that way, which is why only bots need a
    # declaration and any human review still counts.
    #
    # The residue falls the safe way. An outside human whose association reads
    # NONE does not attest, and the refusal tells them to be declared. A gate
    # that under-attests refuses a good PR loudly; one that over-attests passes a
    # bad one in silence.
    attesting: list[str] = []
    unqualified: list[str] = []
    for review in pr.get("reviews") or []:
        login = ((review or {}).get("author") or {}).get("login") or "?"
        if _norm(login) == author:
            continue
        assoc = (review or {}).get("authorAssociation") or ""
        if assoc in _MEMBER_ASSOCIATIONS or _norm(login) in declared:
            attesting.append(login)
        else:
            unqualified.append(login)

    if attesting:
        return Verdict("attested", True, f"reviewed by: {', '.join(sorted(set(attesting)))}")

    # --- attested by a comment-shaped review? ----------------------------------
    # A reviewer that does not use the reviews API leaves `reviews[]` empty on a
    # PR it genuinely reviewed. Matched on a DECLARED (login, marker) pair, never
    # on "a bot commented" — the latter lets a labeler attest through the
    # comments door, which is the same defect arriving by another route.
    #
    # Runs BEFORE the declined check on purpose: both can be true at once when
    # one reviewer reviews while another's quota is spent, and the gate asks
    # whether a review happened, so one that did outranks one that did not.
    comments = pr.get("comments") or []
    for reviewer in reviewers:
        login_n = _norm(reviewer["login"])
        for marker in reviewer["review_markers"]:
            for comment in comments:
                c_login = _norm(((comment or {}).get("author") or {}).get("login"))
                if c_login == login_n and c_login != author and marker in ((comment or {}).get("body") or ""):
                    return Verdict(
                        "attested",
                        True,
                        f'reviewed by: {reviewer["login"]} (comment-shaped review: "{marker}")',
                    )

    # --- exempt? ---------------------------------------------------------------
    # Some changes carry nothing a review could act on. Matched by DIFF SIGNATURE
    # and nothing else — not by author (the tools that open such changes run
    # under a human token, so an author rule never fires) and not by branch (any
    # branch can be named to match).
    #
    # Exact set equality, both directions. Upstream's comment describes only half
    # of this as "every changed file must appear in the declared set"; the code
    # is stricter, and the difference is load-bearing here because release
    # tooling in this repository opens per-app releases whose file sets vary. The
    # strictness is kept and each real shape is declared instead: a shape nobody
    # declared produces a red PR asking for one, never a silent exemption.
    changed = {f.get("path") for f in (pr.get("files") or []) if isinstance(f, dict) and f.get("path")}
    if changed:
        for sig in (registry.get("exempt") or {}).get("signatures") or []:
            if changed == set(sig.get("files") or []):
                return Verdict(
                    "exempt",
                    True,
                    f'every changed file is in the "{sig.get("name")}" signature; nothing here is reviewable',
                )

    # --- declined? -------------------------------------------------------------
    declined_by = declined_marker = ""
    for reviewer in reviewers:
        login_n = _norm(reviewer["login"])
        for marker in reviewer["declined_markers"]:
            if any(
                _norm(((c or {}).get("author") or {}).get("login")) == login_n
                and marker in ((c or {}).get("body") or "")
                for c in comments
            ):
                declined_by, declined_marker = reviewer["login"], marker
                break
        if declined_by:
            break

    # --- disclosed? ------------------------------------------------------------
    # Label AND section, never one alone. Proceeding on an unreviewed PR is
    # allowed; proceeding silently is not.
    escape = registry["escape"]
    has_label = any((lbl or {}).get("name") == escape["label"] for lbl in (pr.get("labels") or []))
    rationale = _rationale_under(pr.get("body") or "", escape["section"])
    if has_label and rationale:
        who = f" ({declined_by} declined)" if declined_by else ""
        return Verdict(
            "disclosed",
            True,
            f'no review ran{who}, and the merge is declared: "{escape["label"]}" + "{escape["section"]}"',
        )

    if declined_by:
        return Verdict(
            "declined",
            False,
            f'{declined_by} posted a notice that no review ran (marker: "{declined_marker}"). '
            "A notice that no review ran leaves this PR UNREVIEWED, and its checks may still "
            "be green: the reviewer reports its own status, and a skipped review is not a failed one.",
        )
    if unqualified:
        return Verdict(
            "pending",
            False,
            f"reviews exist, but none of them attests: {', '.join(sorted(set(unqualified)))}. "
            "A review counts when its author is a member of this repository, or is declared in "
            "the reviewer registry. A shared automation identity is neither until it is declared.",
        )
    return Verdict("pending", False, "no reviewer output on this PR yet")
