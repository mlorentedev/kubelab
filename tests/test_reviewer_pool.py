"""TOOL-082 AC1 (#1843): `harness/reviewer-pool.json` is one pool for two flows.

The adversarial review (`dotf spec review` / `dotf spec archive`) and the
PR-Agent CI draw read the same file, in the unified shape ported from
mlorentedev/dotfiles (ADR-046 there, adopted here by ADR-070). These tests hold
the invariants each flow depends on, statically, so a pool edit that breaks one
fails here rather than in a review that silently runs on the wrong member.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
POOL = json.loads((REPO_ROOT / "harness" / "reviewer-pool.json").read_text())
MEMBERS = POOL["pool"]
PR_AGENT_MEMBERS = [m for m in MEMBERS if "pr_agent" in m]
SIGNS = {"first", "second", "fallback"}


def _ids(members: list[dict]) -> list[str]:
    return [m["id"] for m in members]


@pytest.mark.parametrize("member", MEMBERS, ids=_ids(MEMBERS))
def test_every_member_names_its_vendor(member: dict) -> None:
    """The second signature must come from a different vendor than the first,
    and `dotf spec archive` compares this field. Inferring it from the id
    works for Anthropic only, so every member declares it."""
    assert member.get("vendor"), f"{member['id']} declares no vendor"


@pytest.mark.parametrize("member", MEMBERS, ids=_ids(MEMBERS))
def test_every_member_declares_exactly_one_credential_path(member: dict) -> None:
    """#1561: with neither field the launcher injects the whole secret store
    (`dotf secrets run --` with no `--only`), so a review runs with every
    credential in reach. A key-based member names its one secret; a login-based
    one says so."""
    declared = [k for k in ("secret_id", "auth") if member.get(k)]
    assert len(declared) == 1, f"{member['id']} declares {declared or 'neither secret_id nor auth'}"


@pytest.mark.parametrize("member", MEMBERS, ids=_ids(MEMBERS))
def test_an_anthropic_member_never_signs_first(member: dict) -> None:
    """Amendment B (ADR-070): Claude implements nearly every change here, so an
    Anthropic model may add a second signature or stand in when the first
    signers failed, never sign alone by draw. An absent `signs` means first."""
    signs = member.get("signs", "first")
    assert signs in SIGNS, f"{member['id']} declares signs={signs!r}"
    if member["vendor"].lower() == "anthropic":
        assert signs in {"second", "fallback"}, f"{member['id']} is Anthropic and would sign first"


def test_another_vendor_can_sign_first() -> None:
    """The other half of amendment B: with every Anthropic member barred from
    signing first, the pool still needs a first signer from another vendor, or
    the adversarial draw has no candidate and fails at launch rather than here."""
    first = [m["id"] for m in MEMBERS if m.get("signs", "first") == "first" and m["vendor"].lower() != "anthropic"]
    assert first, "no member outside Anthropic signs first"


def test_the_ci_draw_has_drawable_members() -> None:
    weights = [m["pr_agent"]["weight"] for m in PR_AGENT_MEMBERS if "weight" in m["pr_agent"]]
    assert weights, "no pool member carries a PR-Agent weight"
    assert all(isinstance(w, int) and w > 0 for w in weights), weights


@pytest.mark.parametrize("member", PR_AGENT_MEMBERS, ids=_ids(PR_AGENT_MEMBERS))
def test_a_pr_agent_member_is_either_drawn_or_routed_never_both(member: dict) -> None:
    """A risk-route member reviews first on a large or labelled PR and is never
    drawn: at Sonnet's price a weighted share would spend the month in a week."""
    block = member["pr_agent"]
    assert block.get("model"), f"{member['id']} has a pr_agent block with no model"
    routed = block.get("route") == "risk"
    assert routed != ("weight" in block), f"{member['id']} must have exactly one of weight or route: risk"


def test_exactly_one_member_takes_the_risk_route() -> None:
    routed = [m["id"] for m in PR_AGENT_MEMBERS if m["pr_agent"].get("route") == "risk"]
    assert len(routed) == 1, routed


def test_the_risk_predicate_is_the_owner_decided_one() -> None:
    """1,500 changed lines (owner, 2026-10-09, dotfiles#2188) or the exact label.
    Lowering the threshold is the budget lever: 900 lines cost about $106 a
    month in dotfiles' measurement, so a change here is a budget decision."""
    risk = POOL["pr_agent_risk"]
    assert risk["min_changed_lines"] == 1500
    assert risk["label"] == "deep-review"
