"""The `aws1-replace` target must complete the node's bring-up — ANSIBLE-041.

Static parse of the Makefile recipe: no AWS, no terraform, no live node, so
this runs under ``make test-fast`` with the homelab powered off and without
spending a Spot instance to learn the answer.

Why a *static* test is the right instrument here, when the defect it guards is
an integration gap: the bug in #1102 is not that a step misbehaves, it is that
a step is **absent**. Absence is exactly what a recipe parse can see and what
an end-to-end run can only reveal by costing a real replacement — which, at the
time of writing, would cancel a queued Spot restart and delete a live root
volume. The expensive test would also be the destructive one.

The gap this closes, in one line: `node_maintenance` lives in
`provision-aws1.yml`, and nothing in the replacement path ever ran that
playbook — so a replaced hub came up with no maintenance timer and no failure
notification, and neither absence announced itself.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MAKEFILE = REPO / "Makefile"

TARGET = "aws1-replace"


def _recipe(target: str) -> list[str]:
    """Return the recipe lines of a Makefile target.

    A recipe is the tab-indented block following ``target:``; it ends at the
    first line that is neither tab-indented nor blank. Prerequisites on the
    target line are deliberately excluded — they are tested separately, since
    `_aws1-cancel-spot-request` running as a prerequisite rather than as a
    recipe line is a real structural property worth pinning.
    """
    lines = MAKEFILE.read_text().splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if re.match(rf"^{re.escape(target)}:", ln)),
        None,
    )
    assert start is not None, f"target {target!r} not found in the Makefile"

    recipe: list[str] = []
    for ln in lines[start + 1 :]:
        if ln.startswith("\t"):
            recipe.append(ln.lstrip("\t"))
        elif ln.strip() == "":
            continue
        else:
            break
    return recipe


def _recipe_text() -> str:
    return "\n".join(_recipe(TARGET))


# --- the absence the ticket is about --------------------------------------


def test_replace_provisions_the_node_it_rebuilt():
    """The defect itself: nothing in the chain ran `provision-aws1.yml`.

    Matched on the playbook/target rather than on `node_maintenance`, because
    the role is reached *through* provisioning — asserting the role name here
    would pass the day someone invokes the role directly and skips the rest of
    day-2 provisioning, which is a different node and a different bug.
    """
    text = _recipe_text()
    assert re.search(r"provision.*aws1|NODE=aws1", text), (
        "aws1-replace rebuilds the hub without ever provisioning it — "
        "node_maintenance (the timer + failure-notify path) is never installed"
    )


def _executed_lines() -> list[str]:
    """Recipe lines that actually run something, with `echo` output excluded.

    Load-bearing distinction, caught by this test suite failing for the wrong
    reason: the pre-fix recipe *did* contain the string `deploy-argocd` — inside
    `@echo "... then run: make deploy-argocd"`. A naive substring assertion
    therefore passed against the exact bug it was written to catch. Printing the
    name of a step is the opposite of taking it.
    """
    out = []
    for ln in _recipe(TARGET):
        stripped = ln.lstrip("@-")
        if stripped.startswith(("echo ", "echo\t")):
            continue
        out.append(ln)
    return out


def test_replace_hands_off_to_argocd_itself():
    """`deploy-argocd` must be part of the chain, not a printed instruction."""
    assert any("deploy-argocd" in ln for ln in _executed_lines()), (
        "deploy-argocd is named but never invoked — printing a step is not running it"
    )


def test_replace_waits_for_readiness_before_provisioning():
    """Order matters: provisioning a node whose cloud-init has not finished
    fails confusingly — K3s and the Tailscale registration are cloud-init's.
    """
    text = _recipe_text()
    wait = re.search(r"wait-node-ready|wait_node_ready", text)
    assert wait, "no readiness wait in the chain"

    provision = re.search(r"provision.*aws1|NODE=aws1", text)
    assert provision, "no provisioning step in the chain"
    assert wait.start() < provision.start(), "provisioning starts before the wait"


# --- the shape of the fix, not just its presence ---------------------------


def test_replace_does_not_instruct_a_human_to_finish_the_job():
    """Standing Order #1 — automate, don't instruct.

    The pre-fix recipe ended with `Wait ~5 min for cloud-init, then run: make
    deploy-argocd`. An instruction is not a step: it was also incomplete, since
    it named `deploy-argocd` and never `provision-aws1`.
    """
    text = _recipe_text()
    offenders = [
        ln
        for ln in text.splitlines()
        if re.search(r"then run:|Wait ~|, then\s+make ", ln, re.IGNORECASE)
    ]
    assert not offenders, f"recipe tells a human to finish the job: {offenders}"


def test_no_stage_of_the_chain_swallows_its_failure():
    """A chain that continues past a failed stage reports success for a node
    that was never provisioned — the exact silence this ticket is about.

    `|| true` on the *spot-request cancellation* is legitimate (there may be no
    request), but that runs as a prerequisite target, not in this recipe.
    """
    offenders = [ln for ln in _recipe_text().splitlines() if "|| true" in ln]
    assert not offenders, f"stage swallows its own failure: {offenders}"


@pytest.mark.parametrize(
    "earlier,later",
    [
        ("terraform", "wait-node-ready"),
        ("wait-node-ready", "provision"),
        ("provision", "deploy-argocd"),
    ],
)
def test_chain_runs_in_dependency_order(earlier: str, later: str):
    """Each stage depends on the previous one having happened.

    Asserted pairwise rather than as one regex over the whole recipe so a
    failure names *which* edge broke, which is the thing a reader needs.
    """
    text = _recipe_text()
    first, second = text.find(earlier), text.find(later)
    assert first != -1, f"{earlier!r} missing from the chain"
    assert second != -1, f"{later!r} missing from the chain"
    assert first < second, f"{earlier!r} must run before {later!r}"
