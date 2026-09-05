"""The unbound-PVC drill, whose teardown is not a step anyone has to remember.

`obs015-pvc-unbound-failure` can only be proven to work by *creating* the
condition it watches: an unbindable PersistentVolumeClaim. That is the whole
difficulty. A verification that works by creating a condition has **no natural
end** -- the condition goes on being true, and the state that was evidence one
minute becomes residue the next with no event marking the transition.

That is not hypothetical. `ac2-drill-unbound` was created 2026-08-25 to exercise
this rule, and it was still there ten days later, still Pending, with the alert
correctly firing the whole time and being read as homelab noise (#1583).

So the teardown here is not a second command and not a runbook line. Those are
reminders, and a reminder fails exactly when the situation arrives. It is a
`finally` in the same call that makes the assertion: the claim's lifetime is
bounded by the drill's lifetime, by construction. Ctrl-C at minute twenty still
removes it. The one case this cannot cover is SIGKILL, which no in-process
mechanism can.

Idempotent in both directions, which is what lets the drill be the thing that
clears an existing leftover rather than needing a hand-run `kubectl delete`
first: the claim is deleted before it is created (so a residue from an earlier
run is absorbed, not collided with), and the delete tolerates absence.

And it refuses to measure while the alert is already firing. That is not
caution, it is the first run of this drill reporting `FIRING after 0.0m` on the
ten-day-old instance it had just absorbed the claim for -- proof of nothing,
indistinguishable in the output from proof of something. The alert instance is
keyed by (namespace, pvc), so a fresh claim under the same name RESUMES the
existing one rather than starting a distinguishable one; there is no `startsAt`
that advances and no label that differs, which makes attribution after the fact
impossible and refusal before the fact the only honest option.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

#: The claim's name is the one that already exists in staging, deliberately.
#: `ac2` names an acceptance criterion of the spec that first needed it, which
#: is a poor durable name -- but renaming it here would leave the original
#: object behind for exactly the same reason this module exists, and the first
#: real run is meant to absorb it. A rename is a separate, safe change once the
#: drill owns the lifecycle.
DRILL_PVC_NAME = "ac2-drill-unbound"
DRILL_NAMESPACE = "kubelab"

#: A storage class that cannot exist is what makes the claim *stay* Pending.
#: A claim on a real class would bind as soon as anything consumed it, and a
#: drill whose condition can resolve itself proves nothing.
UNBINDABLE_STORAGE_CLASS = "this-storage-class-does-not-exist"

#: What the drill waits to see. Matched on the alert's title, which is the
#: field `GrafanaAlertClient.get_alerts()` returns as `name`.
DRILL_ALERT_NAME = "PersistentVolumeClaim unbound or failed"

#: `for: 15m` on a group with `interval: 15m`, reading a `[30m]` window, and the
#: claim only enters Loki on the next disk-watcher run (also 15m). Worst case is
#: therefore around 45 minutes; the default gives it one interval of headroom.
DEFAULT_TIMEOUT_S = 3600
DEFAULT_POLL_S = 60


class DrillTeardownError(Exception):
    """The claim could not be removed -- residue is live and needs a human.

    Raised from the `finally`, so it can replace a failure from the drill body.
    That is deliberate: a failed assertion is a result, while a failed teardown
    is the exact defect this module exists to prevent, and it must not be
    reduced to a log line under a more interesting exception.
    """


@dataclass(frozen=True)
class DrillResult:
    """What the drill observed. `fired` is the assertion; the rest is evidence."""

    fired: bool
    waited_s: float
    absorbed_residue: bool  #: a claim from an earlier run was present at start
    polls: int
    #: Whether the drill was in a position to measure anything at all. False
    #: when the alert was already firing before the claim was created, which
    #: makes `fired` unattributable rather than false -- a distinction the
    #: caller must not collapse, since collapsing it is how a borrowed firing
    #: gets reported as proof.
    measured: bool = True


def drill_pvc_manifest(
    name: str = DRILL_PVC_NAME,
    namespace: str = DRILL_NAMESPACE,
    storage_class: str = UNBINDABLE_STORAGE_CLASS,
) -> dict[str, Any]:
    """The claim, as a manifest. Pure, so the shape is testable without a cluster."""
    return {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app.kubernetes.io/name": "obs-drill",
                "app.kubernetes.io/component": "observability",
                "app.kubernetes.io/part-of": "kubelab",
            },
            "annotations": {
                # For whoever finds this object without this repo in front of
                # them. The previous one carried nothing and read as production.
                "kubelab.live/purpose": (
                    "Transient drill claim for obs015-pvc-unbound-failure. "
                    "Owned by `make drill-pvc-unbound`, which removes it in a "
                    "finally. If you are reading this, a drill was killed "
                    "(SIGKILL) -- re-run the drill to clear it. See #1583."
                ),
            },
        },
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "storageClassName": storage_class,
            "resources": {"requests": {"storage": "1Mi"}},
        },
    }


def kubectl_delete_argv(kubeconfig: str, name: str, namespace: str) -> list[str]:
    """`--ignore-not-found` is what makes teardown safe to run unconditionally.

    Without it the `finally` raises when the body already removed the claim, or
    when creation never got that far -- turning a clean exit into a spurious
    teardown failure.
    """
    return [
        "kubectl",
        "--kubeconfig",
        kubeconfig,
        "-n",
        namespace,
        "delete",
        "pvc",
        name,
        "--ignore-not-found",
        "--wait=false",
    ]


def kubectl_get_argv(kubeconfig: str, name: str, namespace: str) -> list[str]:
    return [
        "kubectl",
        "--kubeconfig",
        kubeconfig,
        "-n",
        namespace,
        "get",
        "pvc",
        name,
        "-o",
        "json",
    ]


def kubectl_apply_argv(kubeconfig: str, namespace: str) -> list[str]:
    return ["kubectl", "--kubeconfig", kubeconfig, "-n", namespace, "apply", "-f", "-"]


def alert_is_firing(alerts: list[dict[str, Any]], name: str = DRILL_ALERT_NAME) -> bool:
    """True when the drill's rule has an alerting instance.

    Compares on `state`, not on presence: the endpoint returns resolved
    instances too for a while, and "the alert exists" is a weaker claim than
    "the alert is firing".
    """
    return any(a.get("name") == name and a.get("state") == "alerting" for a in alerts)


def run_drill(
    *,
    exists: Callable[[], bool],
    create: Callable[[], None],
    delete: Callable[[], None],
    fetch_alerts: Callable[[], list[dict[str, Any]]],
    timeout_s: float = DEFAULT_TIMEOUT_S,
    poll_s: float = DEFAULT_POLL_S,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    log: Callable[[str], None] = print,
) -> DrillResult:
    """Create the condition, wait for the alert, and remove the condition. Always.

    Every side effect is injected so the whole control flow -- including the
    teardown-on-interrupt path, which is the reason this function exists -- is
    exercised without a cluster or a Grafana.
    """
    absorbed = exists()
    if absorbed:
        log(f"{DRILL_PVC_NAME}: residue from an earlier run is present -- absorbing it")
    # Delete-then-create rather than create-and-tolerate-conflict: a claim left
    # by an earlier run may differ in spec, and a drill that silently reuses a
    # foreign object is measuring that object's history, not this run.
    delete()

    # The alert must be QUIET before the claim is created, or a firing seen
    # afterwards cannot be attributed to it.
    #
    # Measured on staging 2026-09-04, by running this drill for real: the alert
    # had been firing for ten days on the residue absorbed one line above, and
    # the first poll after `create()` reported `FIRING after 0.0m (1 polls)`.
    # The drill passed without its claim having caused anything. The instance is
    # keyed by (namespace, pvc), so a fresh claim under the same name RESUMES
    # the existing alert instead of starting a distinguishable one -- there is
    # no `startsAt` to compare and no label that differs.
    #
    # Level-triggered where the claim being tested is edge-triggered. Refusing
    # is the only honest answer available: it is not a failure of the rule, it
    # is the drill saying it cannot measure right now.
    if alert_is_firing(fetch_alerts()):
        log(
            f"{DRILL_ALERT_NAME}: already firing before this drill created anything.\n"
            "  Refusing to measure -- a firing seen now could not be attributed to\n"
            "  this run, and reporting it as proof is the false green this drill exists\n"
            "  to remove. The claim is cleared either way; the existing alert instance\n"
            "  resolves in roughly 30-45m (a [30m] window on a 15m interval). Re-run then."
        )
        return DrillResult(
            fired=False,
            waited_s=0.0,
            absorbed_residue=absorbed,
            polls=0,
            measured=False,
        )

    started = now()
    polls = 0
    fired = False
    try:
        create()
        log(f"{DRILL_PVC_NAME}: created; waiting up to {timeout_s / 60:.0f}m for the alert")
        while now() - started < timeout_s:
            polls += 1
            if alert_is_firing(fetch_alerts()):
                fired = True
                break
            sleep(poll_s)
        waited = now() - started
        if fired:
            log(f"{DRILL_ALERT_NAME}: FIRING after {waited / 60:.1f}m ({polls} polls)")
        else:
            log(f"{DRILL_ALERT_NAME}: did NOT fire within {waited / 60:.1f}m ({polls} polls)")
        return DrillResult(fired=fired, waited_s=waited, absorbed_residue=absorbed, polls=polls)
    finally:
        try:
            delete()
            log(f"{DRILL_PVC_NAME}: removed")
        except Exception as exc:  # noqa: BLE001 -- re-raised as DrillTeardownError below
            raise DrillTeardownError(
                f"{DRILL_PVC_NAME} could not be removed and is LIVE in the cluster. "
                f"Clear it before it starts alerting: kubectl delete pvc "
                f"{DRILL_PVC_NAME} -n {DRILL_NAMESPACE}"
            ) from exc


def pvc_exists(kubeconfig: str, name: str, namespace: str) -> bool:
    proc = subprocess.run(kubectl_get_argv(kubeconfig, name, namespace), capture_output=True, text=True)
    return proc.returncode == 0


def apply_pvc(kubeconfig: str, manifest: dict[str, Any], namespace: str) -> None:
    subprocess.run(
        kubectl_apply_argv(kubeconfig, namespace),
        input=json.dumps(manifest),
        capture_output=True,
        text=True,
        check=True,
    )


def delete_pvc(kubeconfig: str, name: str, namespace: str) -> None:
    subprocess.run(
        kubectl_delete_argv(kubeconfig, name, namespace),
        capture_output=True,
        text=True,
        check=True,
    )
