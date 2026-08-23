"""Stop ONE hub from writing, without removing anything it holds.

The handover primitive for GCP-001 Phase 5, and the rollback that pairs with it.
Two hubs are live during the AWS->GCP migration and exactly one may write to any
given spoke at any moment; `unregister-spoke` enforces that by DELETING the
retiring hub's credential, which also destroys the ability to go back. Pausing
enforces the same invariant reversibly: the hub keeps its cluster secret, its
Applications and its history, and simply stops reconciling.

That is why the destroy is last and separate in the plan -- the paused hub IS
the rollback window, and `hub-resume` is the rollback, one command, no state to
rebuild.

WHAT "PAUSED" MEANS HERE, because the weak readings are the ones that bite.
Three candidates were available:

  (a) the scale command exited 0
  (b) `spec.replicas == 0`
  (c) no application-controller pod remains

Only (c) is a fact about the world. (a) and (b) are facts about what the API
server was *told*, and a controller in the middle of a reconcile keeps writing
to the spoke for as long as its pod lives. This migration has already produced
nine signals that read green over a broken hub -- `Synced` with `history: 0`, a
`healthy` container in front of a dead resolver -- so the wait is not a
convenience flag and there is no path through here that skips it.

WHY ONLY THE APPLICATION-CONTROLLER. It is the component that reconciles
Applications onto spokes. `argocd-server` is the UI/API, `repo-server` renders
manifests on request, `notifications-controller` only reads. Scaling those too
would make the pause louder without making it safer, and would take
`argo.kubelab.live` down -- which during a cutover is the one thing an operator
still wants to look at. The applicationset-controller is left alone for a
narrower reason, checked rather than assumed: this repo declares plain
Applications (`infra/k8s/argocd/applications/*.yaml`), not ApplicationSets, so
it generates nothing here.

Scaling the application-controller to 0 is already this repo's vocabulary --
`_deploy-argocd-helm` does it as an OOM mitigation before a Helm upgrade. What
was missing is the standalone primitive, which is why the plan's handover step
had no command behind it.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from toolkit.core.logging import logger

# The Argo CD component that reconciles Applications onto spokes. A StatefulSet,
# not a Deployment -- `kubectl scale deploy` silently matches nothing here, which
# would report success while the hub kept writing.
CONTROLLER_KIND = "statefulset"
CONTROLLER_NAME = "argocd-application-controller"
NAMESPACE = "argocd"

# Pod label the Argo CD chart puts on the controller's pods.
_POD_SELECTOR = f"app.kubernetes.io/name={CONTROLLER_NAME}"

_WAIT_TIMEOUT_S = 120.0
_WAIT_INTERVAL_S = 2.0


@dataclass(frozen=True)
class Step:
    """One planned action, printable before it runs."""

    what: str
    argv: list[str]


def _kubectl(argv: list[str]) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603 - argv list, no shell
        argv, capture_output=True, text=True, check=False
    )
    return proc.returncode, (proc.stdout or proc.stderr).strip()


def plan(hub_kubeconfig: Path, replicas: int) -> list[Step]:
    """The scale action for one hub. `replicas=0` pauses, `1` resumes."""
    hub = ["--kubeconfig", str(hub_kubeconfig)]
    verb = "pause" if replicas == 0 else "resume"
    return [
        Step(
            f"{verb} {CONTROLLER_NAME} on this hub (replicas={replicas}) — "
            "nothing is deleted; the cluster secrets and Applications stay",
            [
                "kubectl",
                *hub,
                "-n",
                NAMESPACE,
                "scale",
                CONTROLLER_KIND,
                CONTROLLER_NAME,
                f"--replicas={replicas}",
            ],
        )
    ]


def controller_pods(hub_kubeconfig: Path) -> list[str]:
    """Names of the live application-controller pods. Empty list == not writing."""
    code, output = _kubectl(
        [
            "kubectl",
            "--kubeconfig",
            str(hub_kubeconfig),
            "-n",
            NAMESPACE,
            "get",
            "pods",
            "-l",
            _POD_SELECTOR,
            "-o",
            "json",
        ]
    )
    if code != 0:
        raise RuntimeError(f"could not list {CONTROLLER_NAME} pods: {output}")
    items = json.loads(output).get("items", [])
    return [item["metadata"]["name"] for item in items]


def wait_for_pods(hub_kubeconfig: Path, expected_gone: bool, timeout_s: float = _WAIT_TIMEOUT_S) -> list[str]:
    """Block until the controller pods match the intent. Returns the final pod list.

    This is the half that makes the pause a fact rather than an instruction. A
    `scale --replicas=0` that returns 0 has changed the desired state and nothing
    else; the controller keeps reconciling until its pod is actually gone.

    Raises on timeout rather than returning a list the caller might not check --
    a pause that quietly did not take is worse than one that failed loudly, because
    the next step in a cutover assumes it held.
    """
    deadline = time.monotonic() + timeout_s
    pods = controller_pods(hub_kubeconfig)
    while time.monotonic() < deadline:
        if expected_gone and not pods:
            return pods
        if not expected_gone and pods:
            return pods
        time.sleep(_WAIT_INTERVAL_S)
        pods = controller_pods(hub_kubeconfig)

    state = "still running" if expected_gone else "never appeared"
    raise RuntimeError(
        f"timed out after {timeout_s:.0f}s: {CONTROLLER_NAME} pods {state} ({pods or 'none'}). "
        "Refusing to report a pause that did not take — the next step of a cutover "
        "assumes this hub has stopped writing."
    )


def set_hub_paused(
    hub_kubeconfig: Path,
    paused: bool,
    dry_run: bool = False,
    wait: bool = True,
) -> list[Step]:
    """Pause or resume one hub's reconciliation. Returns the plan, executed unless dry_run.

    Idempotent, and worth being precise about which sense (raised in review of
    #1299): the current replica count is deliberately NOT read before scaling.
    `kubectl scale --replicas=N` is declarative — it sets the desired count to N
    whatever it was, and exits 0 either way — so a read-then-write would add a
    race and buy nothing. Re-running is therefore always safe, and the wait then
    observes a state that is already true rather than one it caused.

    What that does NOT promise, stated because the word invites the assumption:
    nothing here detects that the hub was ALREADY paused by someone else. A
    second `hub-pause` is a no-op, not an error.
    """
    replicas = 0 if paused else 1
    steps = plan(hub_kubeconfig, replicas)
    if dry_run:
        return steps

    for step in steps:
        code, output = _kubectl(step.argv)
        if code != 0:
            raise RuntimeError(f"step failed: {step.what}\n  {output}")
        logger.info(f"  {step.what}")

    if wait:
        pods = wait_for_pods(hub_kubeconfig, expected_gone=paused)
        if paused:
            logger.success(f"hub paused — no {CONTROLLER_NAME} pod remains; it is not writing to any spoke")
        else:
            logger.success(f"hub resumed — {CONTROLLER_NAME} running ({', '.join(pods)})")
    return steps
