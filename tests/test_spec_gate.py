"""CI-GATE-009 (#1096): the gate that refuses a PR closing a spec it leaves active.

The gate this file tests exists because the one `CLAUDE.md` described did not.
Four specs reached master closed-but-unarchived before anyone noticed, and the
tests below are written against those real shapes rather than invented ones —
`test_pr_1093_shape_is_rejected` is the literal reproduction #1096 AC5 asks for.

Deliberately filesystem-only: no network, no `gh`, no repo state. The gate reads
a tree and a PR body, so the tests build a tree and pass a body. That keeps the
negative case cheap enough to run on every commit, which matters — a gate whose
own test needs a live PR is a gate nobody runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from toolkit.features import spec_gate

REPO = "mlorentedev/kubelab"


def _spec(root: Path, feature_id: str, issue: str, *, archived: bool = False, review: bool = True) -> Path:
    """Create a spec folder that declares `issue` in its proposal front-matter."""
    folder = root / "archive" / feature_id if archived else root / feature_id
    folder.mkdir(parents=True)
    (folder / "proposal.md").write_text(
        "---\n"
        f'id: "{feature_id}"\n'
        "type: spec\n"
        "status: implementing\n"
        f'issue: "{issue}"   # repo#NNN — GitHub issue that tracks this spec\n'
        "---\n\n"
        f"# {feature_id}\n",
        encoding="utf-8",
    )
    if archived and review:
        (folder / "review.md").write_text(
            '---\nverdict: "PASS"\nreviewer: "nan/deepseek-v4-flash"\n---\n', encoding="utf-8"
        )
    return folder


@pytest.fixture
def specs(tmp_path: Path) -> Path:
    root = tmp_path / "specs"
    (root / "archive").mkdir(parents=True)
    return root


# ---------------------------------------------------------------------------
# The failure this gate exists to stop
# ---------------------------------------------------------------------------


def test_pr_1093_shape_is_rejected(specs: Path) -> None:
    """#1096 AC5, reproduced from the real event.

    PR #1093 merged with `Closes #970` in its body. GitHub closed #970 one
    second later. `specs/SEC-004-rate-limit-middleware/` stayed in the active
    tree with no `review.md`, and nothing said so — it was found by reading the
    tree weeks later.
    """
    _spec(specs, "SEC-004-rate-limit-middleware", f"{REPO}#970")

    violations = spec_gate.check("Closes #970\n\nRate-limit middleware.", specs, repo=REPO)

    assert len(violations) == 1
    assert violations[0].feature_id == "SEC-004-rate-limit-middleware"
    assert "specs/archive/SEC-004-rate-limit-middleware/" in violations[0].reason
    assert spec_gate.report(violations, None)[1] == 1


def test_archiving_in_the_same_pr_passes(specs: Path) -> None:
    _spec(specs, "SEC-004-rate-limit-middleware", f"{REPO}#970", archived=True)

    assert spec_gate.check("Closes #970", specs, repo=REPO) == []


def test_archived_without_a_review_is_rejected(specs: Path) -> None:
    """#1096 AC3 — the merge path must not land a spec no reviewer signed.

    `dotf spec archive` refuses this too, but only when a human runs it, which
    is exactly the assumption that produced four unarchived specs.
    """
    _spec(specs, "TOOL-020-windows-safe-sync", f"{REPO}#835", archived=True, review=False)

    violations = spec_gate.check("Fixes #835", specs, repo=REPO)

    assert len(violations) == 1
    assert "review.md" in violations[0].reason


def test_idp_031_shape_passes_while_its_issue_stays_open(specs: Path) -> None:
    """The fourth instance had nothing inconsistent to detect, and that is the point.

    IDP-031 sat complete and unarchived with its issue still OPEN, so no PR
    closed it and this gate correctly says nothing. The gate closes the
    *closing* path; a spec that is simply never finished is a different problem
    and must not produce a false positive here.
    """
    _spec(specs, "IDP-031-namespace-resource-governance", f"{REPO}#811")

    assert spec_gate.check("Some PR that closes nothing.", specs, repo=REPO) == []


# ---------------------------------------------------------------------------
# Resolution: from the issue, never from the branch or folder name (AC2)
# ---------------------------------------------------------------------------


def test_resolution_ignores_the_feature_id_in_the_body(specs: Path) -> None:
    """Naming the spec in prose is not closing its issue.

    #1093's branch (`docs/sec-004-close`) carried the feature id only by
    convention, which is why the gate resolves through `proposal.md`'s `issue:`
    field instead.
    """
    _spec(specs, "SEC-004-rate-limit-middleware", f"{REPO}#970")

    assert spec_gate.check("Groundwork for SEC-004. Closes #12345.", specs, repo=REPO) == []


def test_cross_repo_specs_are_not_matched_by_a_bare_number(specs: Path) -> None:
    """Several specs here track `mlorentedev/knowledge#NNN`.

    A bare `Closes #90` in a kubelab PR closes kubelab#90, not knowledge#90.
    Matching on the number alone would fail PRs for a spec they cannot close.
    """
    _spec(specs, "CONSOLE-002-cross-context-bitacora", "mlorentedev/knowledge#90")

    assert spec_gate.check("Closes #90", specs, repo=REPO) == []


def test_cross_repo_spec_is_matched_when_the_slug_agrees(specs: Path) -> None:
    _spec(specs, "CONSOLE-002-cross-context-bitacora", "mlorentedev/knowledge#90")

    violations = spec_gate.check("Closes mlorentedev/knowledge#90", specs, repo="mlorentedev/knowledge")

    assert len(violations) == 1


def test_a_spec_without_an_issue_field_is_skipped(specs: Path) -> None:
    folder = specs / "NOTIFY-001"
    folder.mkdir()
    (folder / "proposal.md").write_text('---\nid: "NOTIFY-001"\n---\n', encoding="utf-8")

    assert spec_gate.check("Closes #1", specs, repo=REPO) == []


# ---------------------------------------------------------------------------
# Closing-keyword coverage — a keyword missed here is a spec that closes silently
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        "Closes #970",
        "closes #970",
        "CLOSES #970",
        "Closed #970",
        "Close #970",
        "Fixes #970",
        "Fixed #970",
        "Fix #970",
        "Resolves #970",
        "Resolved #970",
        "Resolve #970",
        "Closes: #970",
        f"Closes {REPO}#970",
        f"Closes https://github.com/{REPO}/issues/970",
        "Some text\n\nCloses #970\n\nmore text",
    ],
)
def test_every_github_closing_form_is_detected(specs: Path, body: str) -> None:
    _spec(specs, "SEC-004-rate-limit-middleware", f"{REPO}#970")

    assert len(spec_gate.check(body, specs, repo=REPO)) == 1, f"missed: {body!r}"


@pytest.mark.parametrize(
    "body",
    [
        "Related to #970",
        "See #970",
        "Part of #970",
        "This unblocks #970",
        "#970",
        "Closes https://github.com/someone/else/issues/970",
    ],
)
def test_a_mere_mention_does_not_trip_the_gate(specs: Path, body: str) -> None:
    """GitHub does not close on these, so neither may the gate.

    A false positive here is worse than it looks: it fails PRs that correctly
    reference a spec in passing, and the cheapest way to make that stop is to
    delete the reference — which costs the repo its cross-links.
    """
    _spec(specs, "SEC-004-rate-limit-middleware", f"{REPO}#970")

    assert spec_gate.check(body, specs, repo=REPO) == [], f"false positive: {body!r}"


# ---------------------------------------------------------------------------
# The escape hatch leaves a record (AC4)
# ---------------------------------------------------------------------------


def test_declared_exception_passes_but_is_reported(specs: Path) -> None:
    _spec(specs, "SEC-004-rate-limit-middleware", f"{REPO}#970")
    body = "Closes #970\n\nSpec-archive-exception: reviewer pool exhausted, archiving in #1234\n"

    violations = spec_gate.check(body, specs, repo=REPO)
    message, code = spec_gate.report(violations, spec_gate.declared_exception(body))

    assert violations, "the exception must not hide the finding, only waive it"
    assert code == 0
    assert "WAIVED" in message
    assert "reviewer pool exhausted" in message
    assert "SEC-004-rate-limit-middleware" in message


def test_an_exception_without_a_reason_does_not_waive(specs: Path) -> None:
    """An empty declaration is the silent skip this gate refuses to allow."""
    _spec(specs, "SEC-004-rate-limit-middleware", f"{REPO}#970")
    body = "Closes #970\n\nSpec-archive-exception:\n"

    assert spec_gate.declared_exception(body) is None
    assert spec_gate.report(spec_gate.check(body, specs, repo=REPO), None)[1] == 1


# ---------------------------------------------------------------------------
# The failure message has to be actionable, because it fires on someone else's PR
# ---------------------------------------------------------------------------


def test_failure_message_names_the_command_that_fixes_it(specs: Path) -> None:
    _spec(specs, "SEC-004-rate-limit-middleware", f"{REPO}#970")

    message, code = spec_gate.report(spec_gate.check("Closes #970", specs, repo=REPO), None)

    assert code == 1
    assert "dotf spec archive" in message
    assert "dotf spec review" in message
    assert "Spec-archive-exception:" in message


def test_no_closing_reference_short_circuits(specs: Path) -> None:
    """The common case must not walk the tree at all."""
    _spec(specs, "SEC-004-rate-limit-middleware", f"{REPO}#970")

    assert spec_gate.check("A PR that closes nothing.", specs, repo=REPO) == []


# ---------------------------------------------------------------------------
# The gate must pass against the repo as it actually stands
# ---------------------------------------------------------------------------


def test_the_real_specs_tree_is_fully_visible_to_the_gate() -> None:
    """Every active spec declares an `issue:`, so the gate can resolve all of them.

    This began as a ratchet over four grandfathered specs (#1144). The ratchet
    reached zero on 2026-08-18 and the exemption list is gone, which turns this
    from "the set does not grow" into the flat invariant: a spec the gate cannot
    see is a spec whose issue can be closed out silently, and there are none.

    Resolving the four was not the bookkeeping it looked like. TOOL-001 mapped
    cleanly to #520 and DT-004 to #465 — whose title says DASH-DT-004, so the
    ids disagree and the mismatch is annotated rather than renamed, because the
    gate resolves by issue NUMBER. The other two were not pending work at all:
    ANSIBLE-021 shipped in #815 and sat complete for seven weeks, and VPNACL-001
    has been deployed and live on the VPS since 2026-06-01. Both were invisible
    here, and the audit that should have caught ANSIBLE-021 — "no active spec
    has a closed issue" — passed green precisely because it declared no issue to
    check. Half of what the blind set hid was finished work nobody archived.

    Keep this list empty. Adding a name back is allowed only with the issue that
    tracks the exemption, because `spec init` is gated on an open issue: a new
    blind spec means the gate was bypassed, not that the rule needs relaxing.
    """
    root = Path(__file__).resolve().parents[1] / "specs"
    known_blind: set[str] = set()

    blind = set(spec_gate.undeclared_specs(root))

    assert not (blind - known_blind), (
        f"spec(s) with no `issue:` field: {sorted(blind - known_blind)} — "
        "`spec init` is gated on an open issue, so this means the gate was bypassed"
    )
    if known_blind - blind:
        pytest.fail(
            f"these specs now declare an issue: {sorted(known_blind - blind)} — "
            "remove them from known_blind so the ratchet keeps tightening"
        )


def test_undeclared_specs_are_reported_without_failing_the_build() -> None:
    """A spec that forgot its issue is not the fault of the PR that ran the gate."""
    message, code = spec_gate.report([], None, ["VPNACL-001-fleet-segmentation"])

    assert code == 0
    assert "VPNACL-001-fleet-segmentation" in message
    assert "cannot see" in message


# ---------------------------------------------------------------------------
# Issue-field forms — the majority of this repo uses the short one
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "declared",
    ["mlorentedev/kubelab#970", "kubelab#970"],
)
def test_both_issue_field_forms_resolve(specs: Path, declared: str) -> None:
    """18 of this repo's 28 specs declare `kubelab#NNN`, not the full slug.

    The first draft of the gate required `owner/repo` and was therefore blind to
    the majority of the tree — it passed everything, and 35 green unit tests did
    not notice, because every one of them used the canonical form. Found by
    running the gate against the real repo instead of against fixtures.
    """
    _spec(specs, "SEC-004-rate-limit-middleware", declared)

    assert len(spec_gate.check("Closes #970", specs, repo=REPO)) == 1, f"blind to {declared!r}"


def test_the_real_specs_tree_resolves_end_to_end() -> None:
    """Every active spec resolves to a number for THIS repo, or tracks another one.

    Sibling to the visibility test above, and deliberately a different question.
    That one asks whether a spec declares an issue at all; this one asks whether
    the declaration resolves *for this repo* — because `spec_issue` returns None
    for a cross-repo reference just as it does for a missing field, and the gate
    is equally unable to act on either.

    Two specs legitimately track `mlorentedev/knowledge`, and they are named
    rather than counted: a third appearing means someone pointed a kubelab spec
    at the wrong tracker, which reads as "declared" everywhere else and is
    invisible to the gate here. The fixture suite cannot catch this — it is a
    property of what is committed, not of the parser.
    """
    root = Path(__file__).resolve().parents[1] / "specs"
    folders = sorted(p for p in root.iterdir() if p.is_dir() and p.name != "archive")

    assert not spec_gate.undeclared_specs(root), (
        "specs invisible to the gate: "
        f"{sorted(spec_gate.undeclared_specs(root))!r} — see the ratchet above"
    )

    cross_repo = {
        f.name
        for f in folders
        if (f / "proposal.md").is_file()
        and spec_gate.spec_issue(f / "proposal.md", REPO) is None
    }
    assert cross_repo == {"NOTIFY-001", "TOOL-009-cluster-operator-bootstrap"}, (
        f"the set of specs tracked outside {REPO} changed: {sorted(cross_repo)!r}. "
        "A kubelab spec pointed at another repo's tracker looks declared to every "
        "other check and cannot be resolved by this gate."
    )


# ---------------------------------------------------------------------------
# CI-GATE-013 (#1157): the body is Markdown, and code in it is not a directive
# ---------------------------------------------------------------------------
#
# Every expectation below about GitHub's own behaviour was measured, not
# reasoned: a temporary PR body on kubelab#1159, read back through
# `closingIssuesReferences`, restored immediately, targeting already-closed
# issues so a merge in the window would have been a no-op. The three results are
# recorded as dated rows beside `_CLOSES_RE` in the module.
#
# The reason this matters is narrower than "the gate should be correct". The
# gate's own failure hint prints the waiver line to copy, so the documents most
# likely to quote closing keywords and `Spec-archive-exception:` are the ones
# written *about this gate* — which is exactly how #1155 tripped it while
# documenting it.

FENCE_CASES = [
    pytest.param("the string `closes #999` appears in a log", set(), id="inline-span"),
    pytest.param("```\ncloses #999\n```", set(), id="bare-fence"),
    pytest.param("```python\n# closes #999\n```", set(), id="fence-with-info-string"),
    pytest.param("~~~\ncloses #999\n~~~", set(), id="tilde-fence"),
    pytest.param("intro\n```\ncloses #999\nno terminator follows", set(), id="unclosed-fence"),
    pytest.param("`closes #111` and `closes #222`", set(), id="two-spans"),
    pytest.param("quoted `closes #111` and real closes #222", {222}, id="quoted-and-real"),
    pytest.param("this closes #999 for real", {999}, id="plain-prose-still-matches"),
    pytest.param("> fixes #999", {999}, id="blockquote-still-matches"),
    pytest.param("closes `x` #999", set(), id="span-breaks-adjacency"),
]


@pytest.mark.parametrize(("body", "expected"), FENCE_CASES)
def test_code_is_not_a_closing_directive(body: str, expected: set[int]) -> None:
    """Keywords inside code spans and fences are text; GitHub agrees, so must the gate.

    `blockquote-still-matches` and `plain-prose-still-matches` are the guard on
    the fix rather than on the bug: stripping too eagerly turns an over-report
    into an under-report, and that direction fails OPEN. Both were measured to
    link on GitHub, so both must keep matching here.

    `span-breaks-adjacency` pins the placeholder. Deleting a span outright would
    collapse ``closes `x` #999`` to ``closes  #999`` and invent a link GitHub
    does not make — measured: that body produced no reference.
    """
    assert spec_gate.closed_issues(body, REPO) == expected


def test_a_quoted_waiver_is_not_a_declared_waiver() -> None:
    """The fails-OPEN twin, and the worse of the two.

    `_EXCEPTION_RE` also ran over the unparsed body, so a PR *quoting* the waiver
    syntax — in a runbook, a lesson, or by pasting the gate's own failure output,
    which prints the line to copy — was read as a real declaration. The gate then
    reported WAIVED and exited 0, leaving a declared exception in the merge
    record that nobody declared. A silent bypass, not a red build.
    """
    quoted = "Example of the escape hatch:\n\n```\nSpec-archive-exception: <why>\n```\n"
    assert spec_gate.declared_exception(quoted) is None
    assert spec_gate.declared_exception("Spec-archive-exception: genuinely not this PR") == (
        "genuinely not this PR"
    )


def test_pr_1155_shape_passes() -> None:
    """The shape that surfaced CI-GATE-013: a document *about* closing keywords.

    #1155 documents that GitHub parses closing keywords out of prose, so its body
    necessarily quotes one. GitHub linked nothing; the gate failed the PR. Both
    parsers read the same body and disagreed, and the gate was the wrong one.

    This is the shape rather than that PR's literal text — its body has since
    been reworded around the bug, so quoting it today would reproduce the
    workaround instead of the defect.
    """
    body = (
        "## What\n\n"
        "GitHub's parser is not context-aware. A sentence asserting there is no\n"
        "closing reference can itself be one:\n\n"
        "```\n"
        "...would rightly refuse a PR that closed #1056 without archiving it\n"
        "```\n\n"
        "The fix is the gerund, since `closes #1056` and `closed #1056` both link\n"
        "and `closing #1056` does not.\n"
    )
    assert spec_gate.closed_issues(body, REPO) == set()
    assert spec_gate.declared_exception(body) is None
