"""Detach ONE hub from ONE spoke, without pruning the spoke or disarming the rest.

The Makefile recipe this replaces was written when exactly one hub existed:

    kubectl delete secret cluster-$(ENV) -n argocd --kubeconfig $(HUB_KUBECONFIG)
    kubectl delete -f infra/k8s/argocd/spoke-rbac.yaml --kubeconfig $(KUBECONFIG_PATH)

Two hubs exist during the AWS->GCP migration, and in that world it is wrong
three times over:

1. `HUB_KUBECONFIG` is a single global default that now resolves to gcp1 -- the
   hub being migrated TO. Running it to detach aws1 deletes the credential of
   the hub you are keeping.
2. `spoke-rbac.yaml` lives on the SPOKE and is shared by every hub reconciling
   it. Deleting it to detach one hub revokes the other's access at the same
   time.
3. It never removes the Application, so the hub is left holding one whose
   cluster secret is gone: `Unknown` forever, firing `on-sync-failed` every
   minute. That is exactly the state gcp1 was found in on 2026-08-22.

AND THE OBVIOUS CORRECTION IS A TRAP. An Argo CD Application carries
`resources-finalizer.argocd.argoproj.io`, so deleting it CASCADES: every
resource it manages is pruned from the spoke. Measured on aws1's live object:

    finalizers: ["resources-finalizer.argocd.argoproj.io"]
    syncPolicy: {"automated":{"prune":true,"selfHeal":false}}

Deleting that to "detach a hub" would have destroyed the whole staging
namespace. So the finalizer is stripped FIRST, and the order is asserted by a
test rather than left to whoever edits this next.

The shared RBAC removal stays available, because it IS correct when the LAST hub
detaches -- but it is opt-in, never the default. Default-safe, explicit-dangerous.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


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


def application_name(env: str) -> str:
    """The Application an env's manifest declares (`infra/k8s/argocd/applications/`)."""
    return f"kubelab-{env}"


def plan(env: str, hub_kubeconfig: Path, remove_shared_rbac: bool = False) -> list[Step]:
    """Every action, in the order safety requires.

    Step 1 before step 2 is the entire point: patch-then-delete detaches,
    delete-then-patch destroys.
    """
    app = application_name(env)
    hub = ["--kubeconfig", str(hub_kubeconfig)]
    steps = [
        Step(
            f"strip the cascade finalizer from {app} (MUST precede the delete)",
            [
                "kubectl",
                *hub,
                "-n",
                "argocd",
                "patch",
                "application",
                app,
                "--type=merge",
                "-p",
                '{"metadata":{"finalizers":[]}}',
            ],
        ),
        Step(
            f"delete Application {app} — now inert, the spoke's workloads stay",
            ["kubectl", *hub, "-n", "argocd", "delete", "application", app, "--ignore-not-found"],
        ),
        Step(
            f"delete this hub's cluster-{env} credential",
            ["kubectl", *hub, "-n", "argocd", "delete", "secret", f"cluster-{env}", "--ignore-not-found"],
        ),
    ]
    if remove_shared_rbac:
        # Deliberately last, and deliberately opt-in: correct only when no other
        # hub reconciles this spoke.
        steps.append(
            Step(
                "delete the SHARED spoke RBAC — only correct if no other hub reconciles this spoke",
                ["kubectl", "delete", "-f", "infra/k8s/argocd/spoke-rbac.yaml", "--ignore-not-found"],
            )
        )
    return steps


def unregister_spoke(
    env: str,
    hub_kubeconfig: Path,
    remove_shared_rbac: bool = False,
    dry_run: bool = False,
) -> list[Step]:
    """Detach one hub from one spoke. Returns the plan, executed unless dry_run."""
    steps = plan(env, hub_kubeconfig, remove_shared_rbac)
    if dry_run:
        return steps
    for step in steps:
        _kubectl(step.argv)
    return steps
