"""The `gcp1-replace` target must leave prod's route pointing at the new hub.

Sibling of ``test_aws1_replace_chain.py`` and written because that module's
absence here was the whole defect: aws1's chain has been guarded since
ANSIBLE-041, gcp1 inherited the pattern's *shape* when the hub migrated to GCP
and not its guard. So the one property the aws1 tests pin — that a replacement
finishes the job rather than printing what a human should do next — went
unasserted on the hub that actually serves prod.

What that cost, measured 2026-08-23 (lesson-373): adopting the instance template
rolled gcp1, its Tailscale address moved ``.12 -> .13``, and
``argo.kubelab.live`` went dark while the hub itself answered HTTP 200. Prod's
``argocd-external`` EndpointSlice still held the old address, because an
EndpointSlice takes an IP and cannot take a DNS name. The manifest's own comment
said ``gcp1-replace`` already told you to run the target that re-resolves it. It
did not — it ran three steps and echoed a line about cloud-init.

Static parse of the Makefile recipe, for the same reason the aws1 module gives:
the defect is an **absent step**, absence is what a recipe parse sees, and the
end-to-end alternative costs a real hub replacement to learn the answer.

The helper below is duplicated from the aws1 module rather than shared. Two
call sites do not earn an abstraction, and the duplication is the point of
comparison — a reader diffing the two files should see two chains asserted the
same way, not one indirection.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MAKEFILE = REPO / "Makefile"

TARGET = "gcp1-replace"
REPOINT = "argocd-repoint"


def _recipe(target: str) -> list[str]:
    """Return the tab-indented recipe lines that follow ``target:``."""
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


def _executed_lines(target: str) -> list[str]:
    """Recipe lines that run something — ``echo`` and comments excluded.

    The exclusion is load-bearing and the aws1 module learned it the hard way:
    a recipe that merely *prints* the name of the next step contains the string
    a naive assertion looks for, so the test passes against the exact bug it was
    written to catch. Comments are dropped for the same reason — this recipe now
    carries one that names `argocd-repoint` in prose.
    """
    out = []
    for ln in _recipe(target):
        stripped = ln.lstrip("@-").lstrip()
        if stripped.startswith(("echo ", "echo\t", "#")):
            continue
        out.append(ln)
    return out


# --- the absence lesson-373 is about ---------------------------------------


def test_replace_repoints_the_route_at_the_hub_it_rebuilt():
    """The defect itself: a recreate rotates the address and nothing re-resolved it.

    Asserted against the executed lines, so a comment or an echo naming the
    target cannot satisfy it. That distinction is not hypothetical here: the
    manifest this protects spent months carrying a comment which claimed this
    very chain ran the step.
    """
    assert any(REPOINT in ln for ln in _executed_lines(TARGET)), (
        f"{TARGET} rebuilds the hub and leaves prod's Argo CD route pointing at the "
        "previous Tailscale address — the hub comes back healthy and "
        "argo.kubelab.live stays dark"
    )


def test_replace_does_not_instruct_a_human_to_finish_the_job():
    """Standing Order #1 — automate, don't instruct. An instruction is not a step."""
    offenders = [
        ln
        for ln in "\n".join(_recipe(TARGET)).splitlines()
        if re.search(r"then run:|Wait ~|, then\s+make ", ln, re.IGNORECASE)
    ]
    assert not offenders, f"recipe tells a human to finish the job: {offenders}"


@pytest.mark.parametrize(
    "earlier,later",
    [
        ("terraform", "wait-node-ready"),
        ("wait-node-ready", "provision"),
        ("provision", REPOINT),
    ],
)
def test_chain_runs_in_dependency_order(earlier: str, later: str):
    """Repointing last is not cosmetic: MagicDNS has to resolve the *new* node
    before the address is read, so this cannot run before the readiness wait.
    """
    text = "\n".join(_executed_lines(TARGET))
    first, second = text.find(earlier), text.find(later)
    assert first != -1, f"{earlier!r} missing from the chain"
    assert second != -1, f"{later!r} missing from the chain"
    assert first < second, f"{earlier!r} must run before {later!r}"


# --- the repoint target's own contract -------------------------------------


def test_repoint_refuses_to_pass_optional():
    """`--optional` makes `render-apply` report success on a failed render.

    Correct for a render that may legitimately be skipped — the RPi4 CoreDNS one
    is, when the homelab is off. Wrong for this one, whose entire purpose is
    repairing a dead route: a green tick over a failed resolve leaves prod down
    and says nothing. This exact flag already produced that outcome once, on the
    call this target was extracted from.
    """
    text = "\n".join(_executed_lines(REPOINT))
    assert "render-apply" in text, f"{REPOINT} no longer performs the render"
    assert "--optional" not in text, (
        f"{REPOINT} passes --optional: a failed resolve would report success and "
        "leave prod's Argo CD route pointing at a dead address"
    )


def test_repoint_resolves_from_magicdns_not_a_literal_address():
    """The address is the one value that must never be committed — it rotates on
    every recreate (.21 -> .24 -> .12 -> .13 across August 2026). A literal here
    would work exactly until the next preemption.
    """
    text = "\n".join(_executed_lines(REPOINT))
    assert "gcp1.kubelab.internal" in text, "repoint no longer resolves via MagicDNS"
    assert not re.search(r"100\.64\.\d+\.\d+", text), (
        "repoint carries a hardcoded Tailscale address; it rotates on every recreate"
    )
