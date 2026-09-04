"""The review-attestation gate must be red when nobody reviewed the PR.

TOOL-021 (#1140). Eleven PRs across 2026-08-17/19 carried a green reviewer check
with no review behind them, and seven merged. The check reports its own status,
and a skipped review is not a failed one.

These tests drive `classify()` against payload shapes taken from real `gh pr
view --json` output, and against the committed registry — not only against
fixtures written for the test. A gate whose fixtures all use one spelling proves
only that its fixtures agree with each other, which is how a gate in this repo
shipped with 35 green unit tests and a blind spot covering 18 of 28 specs
(#1143).
"""

from __future__ import annotations

import json
import pathlib

import pytest

from toolkit.features.review_attestation import (
    DEFAULT_REGISTRY,
    PayloadError,
    RegistryError,
    classify,
    load_registry,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / DEFAULT_REGISTRY


@pytest.fixture(scope="module")
def registry() -> dict:
    """The committed registry, not a hand-written one.

    Asserting against the real file is the point: a fixture registry would let
    the shipped one rot while every test stayed green.
    """
    return load_registry(REGISTRY_PATH)


def pr(**over) -> dict:
    """A payload shaped like `gh pr view --json number,state,labels,body,comments,reviews,author,files`."""
    base = {
        "number": 1,
        "state": "OPEN",
        "labels": [],
        "body": "",
        "comments": [],
        "reviews": [],
        "author": {"login": "mlorentedev"},
        "files": [{"path": "README.md"}],
    }
    base.update(over)
    return base


def comment(login: str, body: str) -> dict:
    return {"author": {"login": login}, "body": body}


def review(login: str, assoc: str) -> dict:
    return {"author": {"login": login}, "authorAssociation": assoc, "state": "COMMENTED"}


# --------------------------------------------------------------------------- #
# The state the gate exists for
# --------------------------------------------------------------------------- #


class TestDeclined:
    def test_a_rate_limit_notice_is_not_a_review(self, registry: dict) -> None:
        """The whole point: a reviewer saying it could not review must be red."""
        marker = registry["reviewers"][0]["declined_markers"][0]
        login = registry["reviewers"][0]["login"]
        v = classify(pr(comments=[comment(login, f"<!-- {marker} -->")]), registry)
        assert v.state == "declined"
        assert not v.ok

    def test_every_declared_reviewer_has_its_notice_recognised(self, registry: dict) -> None:
        """Each reviewer with a declined marker must actually be matchable.

        Not a formality. This repo runs more than one reviewer and they exhaust
        independently; a registry entry nobody exercises is a reviewer whose
        notice reads as `pending` — still red, but for the wrong reason, and the
        wrong reason is what stops people trusting the gate.
        """
        exercised = 0
        for r in registry["reviewers"]:
            for marker in r["declined_markers"]:
                v = classify(pr(comments=[comment(r["login"], f"...{marker}...")]), registry)
                assert v.state == "declined", f'{r["login"]} / "{marker}" classified as {v.state}'
                exercised += 1
        assert exercised >= 2, "expected at least two reviewers with declined markers"

    def test_declined_and_pending_are_not_collapsed(self, registry: dict) -> None:
        """Both refuse; reporting them the same would throw away the diagnosis."""
        marker = registry["reviewers"][0]["declined_markers"][0]
        login = registry["reviewers"][0]["login"]
        assert classify(pr(comments=[comment(login, marker)]), registry).state == "declined"
        assert classify(pr(), registry).state == "pending"


class TestPending:
    def test_no_reviewer_output_is_pending(self, registry: dict) -> None:
        assert classify(pr(), registry).state == "pending"

    def test_an_undeclared_bot_review_does_not_attest(self, registry: dict) -> None:
        """A shared automation identity is not a reviewer until it is declared.

        Every workflow here posts under one login, so counting "any login that
        is not the author" would let a labeler attest for a PR nobody read.
        """
        v = classify(pr(reviews=[review("some-labeler-bot", "NONE")]), registry)
        assert v.state == "pending"
        assert "some-labeler-bot" in v.detail, "the refusal must name the reviews it did not count"

    def test_contributor_association_does_not_attest(self, registry: dict) -> None:
        """CONTRIBUTOR is earned by a merged commit, which a bot holds as easily."""
        assert classify(pr(reviews=[review("drive-by", "CONTRIBUTOR")]), registry).state == "pending"

    def test_a_payload_without_author_association_does_not_attest(self, registry: dict) -> None:
        """Absent field falls the safe way — under-attest loudly, never over-attest."""
        v = classify(pr(reviews=[{"author": {"login": "who"}, "state": "COMMENTED"}]), registry)
        assert v.state == "pending"


# --------------------------------------------------------------------------- #
# Attestation, and the ways it must NOT be reachable
# --------------------------------------------------------------------------- #


class TestAttested:
    @pytest.mark.parametrize("assoc", ["OWNER", "MEMBER", "COLLABORATOR"])
    def test_a_member_review_attests(self, registry: dict, assoc: str) -> None:
        assert classify(pr(reviews=[review("someone", assoc)]), registry).ok

    def test_the_authors_own_review_never_attests(self, registry: dict) -> None:
        """Self-review is the one case where a non-empty reviews[] means nobody looked."""
        payload = pr(author={"login": "mlorentedev"}, reviews=[review("mlorentedev", "OWNER")])
        assert classify(payload, registry).state == "pending"

    def test_a_declared_reviewer_attests_through_the_comments_api(self, registry: dict) -> None:
        """A reviewer that leaves reviews[] empty on a PR it genuinely reviewed."""
        declared = next(r for r in registry["reviewers"] if r["review_markers"])
        marker = declared["review_markers"][0]
        v = classify(pr(comments=[comment(declared["login"], f"{marker}\n\nfindings...")]), registry)
        assert v.state == "attested"
        assert marker in v.detail

    @pytest.mark.parametrize("spelling", ["github-actions", "github-actions[bot]", "GitHub-Actions"])
    def test_login_spelling_does_not_change_the_verdict(self, registry: dict, spelling: str) -> None:
        """GraphQL says `github-actions`, REST says `github-actions[bot]`.

        Matching raw would make the verdict depend on which API produced the
        payload — a fixture written from one would prove nothing about the other.
        """
        # Pinned to the reviewer this test is ABOUT, not to "the first entry
        # with markers". That shortcut held only while exactly one reviewer had
        # any, and it silently retargeted the moment a second one did (#1187) —
        # the test then sent github-actions' spellings carrying CodeRabbit's
        # marker, and failed for a reason that had nothing to do with spelling.
        declared = next(r for r in registry["reviewers"] if r["login"] == "github-actions")
        marker = declared["review_markers"][0]
        assert classify(pr(comments=[comment(spelling, marker)]), registry).state == "attested"

    def test_a_review_outranks_a_simultaneous_decline(self, registry: dict) -> None:
        """Both are true when one reviewer works while another's quota is spent.

        The gate asks whether a review happened, so one that did outranks one
        that did not. Measured as a real state on this repo's PRs.
        """
        declined = registry["reviewers"][0]
        reviewer = next(r for r in registry["reviewers"] if r["review_markers"])
        payload = pr(
            comments=[
                comment(declined["login"], declined["declined_markers"][0]),
                comment(reviewer["login"], reviewer["review_markers"][0]),
            ]
        )
        assert classify(payload, registry).state == "attested"

    def test_a_non_review_comment_from_a_declared_reviewer_does_not_attest(self, registry: dict) -> None:
        """An auto-summary is not a review. Only a declared marker attests."""
        declared = next(r for r in registry["reviewers"] if r["review_markers"])
        payload = pr(comments=[comment(declared["login"], "## PR Code Suggestions\n\nnitpicks")])
        assert classify(payload, registry).state == "pending"


# --------------------------------------------------------------------------- #
# Exemption — the half that must not be borrowable
# --------------------------------------------------------------------------- #


class TestExempt:
    def test_each_declared_signature_is_exempt(self, registry: dict) -> None:
        for sig in registry["exempt"]["signatures"]:
            payload = pr(files=[{"path": p} for p in sig["files"]])
            v = classify(payload, registry)
            assert v.state == "exempt", f'{sig["name"]} classified as {v.state}'

    def test_the_release_shapes_actually_observed_are_all_covered(self, registry: dict) -> None:
        """Release tooling here opens PER-APP releases, so the file set varies.

        Measured before writing the registry: #767, #806 and #842 carried five
        paths and **#804 carried three**. Matching is exact set equality, so a
        single superset signature exempts the first three and REFUSES #804 —
        which is why each shape is declared. This test is what stops the
        registry being collapsed back into one entry.
        """
        observed = [
            {
                ".release-please-manifest.json",
                "apps/api/CHANGELOG.md",
                "apps/api/version.txt",
                "edge/errors/CHANGELOG.md",
                "edge/errors/version.txt",
            },
            {".release-please-manifest.json", "apps/api/CHANGELOG.md", "apps/api/version.txt"},
        ]
        for files in observed:
            v = classify(pr(files=[{"path": p} for p in sorted(files)]), registry)
            assert v.state == "exempt", f"{sorted(files)} classified as {v.state}"

    def test_the_delivery_shapes_actually_observed_are_all_covered(self, registry: dict) -> None:
        """The deploy/promote shapes, measured rather than assumed (DELIVERY-004).

        Same discipline as the release-please entries above and for the same
        reason: matching is exact set equality, so a shape nobody measured is a
        red PR asking for a signature, never a silent exemption. Five staging
        deploys (#1560, #1582, #1590, #1601, #1617) and one prod promote (#1618)
        were read from the API on 2026-09-04; all six carried exactly two paths.

        Both are SINGLE-APP shapes. A multi-app promotion would produce a
        different set and must be declared when one is first observed — which is
        the lesson `release-please (api only)` records, where one signature was
        assumed sufficient and #804 refuted it.
        """
        observed = [
            {
                "infra/config/values/staging.yaml",
                "infra/k8s/overlays/staging/generated/deployments.yaml",
            },
            {
                "infra/config/values/prod.yaml",
                "infra/k8s/overlays/prod/generated/deployments.yaml",
            },
        ]
        for files in observed:
            v = classify(pr(files=[{"path": p} for p in sorted(files)]), registry)
            assert v.state == "exempt", f"{sorted(files)} classified as {v.state}"

    def test_a_proper_subset_of_a_signature_is_not_exempt(self, registry: dict) -> None:
        """Half a signature is not a signature.

        This is the case a SUBSET comparison would wrongly exempt, and until it
        was written nothing in this file covered it: `test_one_extra_file...`
        catches a widening to superset, and the crossed-environment test below
        catches neither. Reachable in practice — someone edits
        `values/staging.yaml` by hand and does not regenerate the overlay. The
        drift gate would reject that PR, but this gate must not exempt it from
        review on the way, because the two answer different questions.
        """
        for sig in registry["exempt"]["signatures"]:
            files = sorted(sig["files"])
            assert len(files) >= 2, f'{sig["name"]} has one file; a proper subset is empty'
            for dropped in range(len(files)):
                partial = [f for i, f in enumerate(files) if i != dropped]
                v = classify(pr(files=[{"path": p} for p in partial]), registry)
                assert v.state == "pending", (
                    f'{sig["name"]} minus {files[dropped]!r} classified as {v.state}. '
                    f"A partial match is not a match: exemption requires the whole "
                    f"declared set, or a half-finished change rides in on it."
                )

    def test_the_two_environments_do_not_share_a_signature(self, registry: dict) -> None:
        """A staging path and a prod path must never exempt each other.

        The two shapes differ only in the substring `staging`/`prod`, which is
        exactly the kind of near-miss a prefix or substring comparison would
        collapse.

        What this does NOT do, stated because an earlier version of this
        docstring claimed it and pr-agent was right to call it out on #1628: it
        does not make a loosening of the comparison fail. Work it through — the
        crossed set is neither equal to, nor a superset of, nor a subset of
        either signature, so exact, `>=` and `<=` all return `pending` and this
        test reads identically under all three. The discrimination lives in
        `test_one_extra_file_ends_the_exemption` (catches `>=`) and
        `test_a_proper_subset_of_a_signature_is_not_exempt` (catches `<=`).

        It is kept because the near-miss it covers is a real one and cheap to
        assert; it is just not the guard the old docstring advertised.
        """
        crossed = [
            {
                "infra/config/values/staging.yaml",
                "infra/k8s/overlays/prod/generated/deployments.yaml",
            },
            {
                "infra/config/values/prod.yaml",
                "infra/k8s/overlays/staging/generated/deployments.yaml",
            },
        ]
        for files in crossed:
            v = classify(pr(files=[{"path": p} for p in sorted(files)]), registry)
            assert v.state == "pending", (
                f"{sorted(files)} mixes the two environments and classified as "
                f"{v.state}; no declared signature covers that set."
            )

    def test_one_extra_file_ends_the_exemption(self, registry: dict) -> None:
        """Nothing to borrow: no signature can be used to smuggle a change.

        Every declared signature, not `signatures[0]`. Reading one entry made
        this assert something weaker than its name: a signature added after the
        first was never tested against the case that decides whether an
        exemption is an exemption or a bypass, and adding one is precisely when
        that question is live. The entry it happened to read was also the oldest,
        so the guard got quieter with every signature declared.
        """
        signatures = registry["exempt"]["signatures"]
        # Floor on the collection being iterated, not on its source: an empty
        # list makes every assertion below vacuous while the test still passes.
        assert len(signatures) >= 3, (
            f"Only {len(signatures)} exempt signatures parsed from the registry. "
            f"At least the three release-please shapes are declared, so the parse "
            f"is broken and the loop below would assert nothing."
        )

        for sig in signatures:
            payload = pr(files=[{"path": p} for p in [*sig["files"], "toolkit/cli/tools.py"]])
            assert classify(payload, registry).state == "pending", (
                f'signature "{sig["name"]}" still classified as exempt with an extra '
                f"file in the diff — it can be used to carry an unreviewed change."
            )

    def test_an_empty_diff_is_not_exempt(self, registry: dict) -> None:
        assert classify(pr(files=[]), registry).state == "pending"


# --------------------------------------------------------------------------- #
# The escape — allowed, but never silent
# --------------------------------------------------------------------------- #


class TestDisclosed:
    def test_label_and_section_together_disclose(self, registry: dict) -> None:
        e = registry["escape"]
        payload = pr(labels=[{"name": e["label"]}], body=f'{e["section"]}\n\nQuota exhausted; shipping anyway.')
        assert classify(payload, registry).state == "disclosed"

    def test_the_label_alone_does_not(self, registry: dict) -> None:
        e = registry["escape"]
        assert classify(pr(labels=[{"name": e["label"]}]), registry).ok is False

    def test_the_section_alone_does_not(self, registry: dict) -> None:
        e = registry["escape"]
        assert classify(pr(body=f'{e["section"]}\n\nreason'), registry).ok is False

    def test_an_empty_section_is_not_a_disclosure(self, registry: dict) -> None:
        """A heading with nothing under it records the intent to disclose."""
        e = registry["escape"]
        payload = pr(labels=[{"name": e["label"]}], body=f'{e["section"]}\n\n\n## Next heading\n\nunrelated')
        assert classify(payload, registry).ok is False


# --------------------------------------------------------------------------- #
# Failing closed
# --------------------------------------------------------------------------- #


class TestFailsClosed:
    def test_a_missing_registry_raises(self, tmp_path: pathlib.Path) -> None:
        with pytest.raises(RegistryError):
            load_registry(tmp_path / "nope.json")

    def test_invalid_json_raises(self, tmp_path: pathlib.Path) -> None:
        bad = tmp_path / "r.json"
        bad.write_text("{not json", encoding="utf-8")
        with pytest.raises(RegistryError):
            load_registry(bad)

    @pytest.mark.parametrize(
        "payload",
        [
            {"reviewers": []},
            {"reviewers": [{"login": "x"}]},
            {"reviewers": [{"login": "", "declined_markers": [], "review_markers": []}], "escape": {}},
            [{"login": "x"}],
            {
                "reviewers": [{"login": "x", "declined_markers": [], "review_markers": []}],
                "escape": {"label": "l"},
            },
        ],
    )
    def test_valid_json_of_the_wrong_shape_raises(self, tmp_path: pathlib.Path, payload) -> None:
        """A malformed registry must not make the gate quietly more permissive.

        Every shape here parses as JSON and would otherwise produce empty
        strings downstream, classifying as "nobody declined" and "no escape
        configured" — permissive, the one direction this must never fail in.
        """
        bad = tmp_path / "r.json"
        bad.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(RegistryError):
            load_registry(bad)

    def test_a_non_object_payload_raises(self, registry: dict) -> None:
        with pytest.raises(PayloadError):
            classify(["not", "a", "pr"], registry)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Guard the guard
# --------------------------------------------------------------------------- #


def test_no_reviewer_is_named_in_the_module() -> None:
    """Every vendor string lives in the registry, including the prose.

    A vendor name in the module is how "the registry is authoritative" quietly
    stops being true — the next person adds a special case beside the name
    instead of an entry in the file, and the two drift.
    """
    source = (REPO_ROOT / "toolkit/features/review_attestation.py").read_text(encoding="utf-8").casefold()
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    for reviewer in registry["reviewers"]:
        login = reviewer["login"].casefold()
        assert login not in source, f"{reviewer['login']} is named in review_attestation.py; it belongs in the registry"
        for marker in reviewer["declined_markers"] + reviewer["review_markers"]:
            assert marker.casefold() not in source, f'the marker "{marker}" is hardcoded in the module'


def test_the_committed_registry_is_the_shape_the_gate_requires() -> None:
    """The shipped file, not a fixture. Otherwise it can rot while tests pass."""
    reg = load_registry(REGISTRY_PATH)
    assert len(reg["reviewers"]) >= 2, "this repo runs more than one reviewer; both must be declared"
    assert all(r.get("why") for r in reg["reviewers"]), "every entry carries its reason"
    assert all(s.get("why") for s in reg["exempt"]["signatures"]), "every exemption carries its reason"


def test_a_clean_coderabbit_review_attests(registry: dict) -> None:
    """CodeRabbit opens a formal review only when it has something to say.

    On #1187 it reviewed, found nothing, and posted its verdict as a comment —
    `reviews[]` stayed empty and the PR read as unreviewed. The gate could
    therefore attest from CodeRabbit only when CodeRabbit had complaints, which
    blocks the clean PRs and passes the ones with findings. A clean bill of
    health was indistinguishable from silence.
    """
    payload = pr(
        comments=[
            comment("coderabbitai", "No actionable comments were generated in the recent review. 🎉")
        ]
    )
    assert classify(payload, registry).state == "attested"


def test_the_walkthrough_alone_still_does_not_attest(registry: dict) -> None:
    """The distinction the marker rests on, and the reason it is safe.

    CodeRabbit posts a walkthrough whether or not a review ran, so counting it
    would attest a PR nobody read — the original registry reasoning, which
    stands. The clean verdict is different in kind: it asserts the review
    happened ("in the recent review"). Only the second is a marker.
    """
    payload = pr(comments=[comment("coderabbitai", "## Walkthrough\n\nThis PR changes ...")])
    assert classify(payload, registry).state != "attested"


def test_the_clean_verdict_marker_is_declared_not_hardcoded(registry: dict) -> None:
    """It lives in the registry, so the next reviewer-behaviour change is a
    config edit — the property `test_no_reviewer_is_named_in_the_module`
    protects, applied to what counts as a review rather than to who reviews."""
    entry = next(r for r in registry["reviewers"] if r["login"] == "coderabbitai")
    assert "No actionable comments were generated in the recent review" in entry["review_markers"]
