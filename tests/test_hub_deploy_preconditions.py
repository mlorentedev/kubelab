"""TOOL-042: the hub deploy must ask whether the cluster is there before acting.

`_deploy-argocd-helm` scales every Argo CD workload to zero before a Helm
upgrade, and swallows the failures with `|| true`. That guard was written for
"there is nothing to scale" and it also swallows "I cannot talk to the cluster",
which are the same silence and opposite situations.

Measured 2026-08-23: a MIG recreate left the hub kubeconfig carrying the previous
cluster's CA. Every scale silently no-op'd, the wait no-op'd, and the run failed
several steps later at Helm with `Kubernetes cluster unreachable` -- a message
that names neither the recreate nor the stale CA. It happened to end well, because
nothing was scaled down and Argo CD kept serving; the same silence would equally
have hidden a half-completed scale-down.

The fix is to ask first and fail loudly there. These tests pin all three halves of
it: that the precondition is wired as a prerequisite (not merely defined), that
the `|| true` survived -- removing it would turn an empty namespace into a hard
failure, which is the bug in the other direction -- and that the step's banner
does not name a provider, since the text outlived the instance twice already.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

MAKEFILE = Path(__file__).resolve().parents[1] / "Makefile"
TARGET = "_deploy-argocd-helm"
PRECONDITION = "_require-hub-reachable"


def _makefile() -> str:
    return MAKEFILE.read_text(encoding="utf-8")


def _recipe(name: str) -> str:
    """The recipe body of a Make target: its rule line plus indented lines."""
    text = _makefile()
    match = re.search(rf"^{re.escape(name)}:.*$", text, re.MULTILINE)
    assert match, f"target {name!r} no longer exists in the Makefile"
    rest = text[match.start() :].splitlines()
    body = [rest[0]]
    for line in rest[1:]:
        if line and not line.startswith(("\t", " ")):
            break
        body.append(line)
    return "\n".join(body)


class TestPrecondition:
    def test_the_helm_step_declares_the_reachability_check_as_a_prerequisite(self) -> None:
        """Defining the check is not enough -- it has to run before the scale."""
        rule = _recipe(TARGET).splitlines()[0]
        assert PRECONDITION in rule, (
            f"{TARGET} no longer depends on {PRECONDITION}. Defining the check without "
            "wiring it leaves the scale-to-zero exactly as silent as it was in #1340."
        )

    def test_the_precondition_target_exists_and_fails_loudly(self) -> None:
        text = _makefile()
        assert f"\n{PRECONDITION}:" in text, f"{PRECONDITION} target is gone"
        assert "exit 1" in _recipe("_hub-unreachable"), (
            "the unreachable path must exit non-zero; a diagnostic that returns 0 "
            "lets the deploy continue into the failure it was meant to prevent"
        )

    def test_the_operator_is_told_how_to_recover(self) -> None:
        """A guard that stops without naming the fix just moves the confusion."""
        assert "fetch-kubeconfig" in _recipe("_hub-unreachable"), (
            "the error must name the command that refreshes the kubeconfig"
        )


class TestTheSwallowSurvives:
    def test_scale_to_zero_still_tolerates_an_empty_namespace(self) -> None:
        """The `|| true` is correct for its original purpose and must not be 'fixed'.

        With the precondition in place the swallow is no longer ambiguous, so
        removing it would only convert a namespace with nothing to scale into a
        hard failure -- the same defect pointing the other way.
        """
        recipe = _recipe(TARGET)
        scales = [ln for ln in recipe.splitlines() if "--replicas=0" in ln]
        assert scales, "the scale-to-zero lines vanished"
        for line in scales:
            assert "|| true" in line, (
                "scale-to-zero lost its `|| true`; an empty argocd namespace would "
                "now fail the deploy outright"
            )


class TestBannerNamesNoProvider:
    @pytest.mark.parametrize("stale", ["aws1", "t4g.micro", "gcp1"])
    def test_the_step_banner_does_not_pin_an_instance(self, stale: str) -> None:
        """It said 'on hub (aws1)' and 't4g.micro OOM mitigation' months after both were false.

        The hub has now moved providers once and will move instance types again;
        a banner that names the machine is a claim that goes stale silently and
        misleads whoever is reading the log during an incident.
        """
        assert stale not in _recipe(TARGET), (
            f"{TARGET} banner names {stale!r}. The step is provider-agnostic -- "
            "the hub identity lives in clusters.hub in common.yaml, not in an echo."
        )
