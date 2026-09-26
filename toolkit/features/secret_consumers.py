"""Restart the workloads that consume a Secret `apply-secrets` just changed (#1804).

Applying a Secret is not the same as the workload using it:

- A value consumed as an env var is injected once, at container start.
- A value consumed as a file is re-read only if the app watches for it, and a
  watch keyed on the file name never fires on a Secret volume. The kubelet
  updates one by swapping the `..data` symlink and never touches the file's own
  name. Authelia 4.39.15 is exactly that case (`internal/service/file_watcher.go`),
  and it kept answering `user not found` for a user `apply-secrets` had added.

So a Secret that changed is followed by a rollout restart of every workload whose
pod template references it. The consumers are read from the live pod templates,
not listed, so a new consumer is covered the day it is deployed. Only Secrets
kubectl reports `configured` or `created` trigger anything, which keeps a re-run
a no-op.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Iterable
from typing import Any

from toolkit.core.logging import logger

#: Workload kinds whose pod template can reference a Secret and that
#: `kubectl rollout restart` accepts.
WORKLOAD_KINDS = ("deployment", "statefulset", "daemonset")

Kubectl = Callable[[str], list[str]]
Run = Callable[..., Any]


def secret_refs(pod_spec: dict[str, Any]) -> set[str]:
    """Names of every Secret a pod spec reads, through env, envFrom or a volume."""
    names: set[str] = set()
    for container in [*(pod_spec.get("initContainers") or []), *(pod_spec.get("containers") or [])]:
        for env in container.get("env") or []:
            ref = ((env.get("valueFrom") or {}).get("secretKeyRef") or {}).get("name")
            if ref:
                names.add(ref)
        for source in container.get("envFrom") or []:
            ref = (source.get("secretRef") or {}).get("name")
            if ref:
                names.add(ref)
    for volume in pod_spec.get("volumes") or []:
        ref = (volume.get("secret") or {}).get("secretName")
        if ref:
            names.add(ref)
        for source in (volume.get("projected") or {}).get("sources") or []:
            ref = (source.get("secret") or {}).get("name")
            if ref:
                names.add(ref)
    return names


def consumers(workloads: Iterable[dict[str, Any]], secrets: set[str]) -> list[str]:
    """`kind/name` of each workload whose pod template reads any of SECRETS."""
    found = []
    for item in workloads:
        spec = ((item.get("spec") or {}).get("template") or {}).get("spec") or {}
        if secret_refs(spec) & secrets:
            found.append(f"{item['kind'].lower()}/{item['metadata']['name']}")
    return sorted(found)


def restart_consumers(
    changed: set[tuple[str, str]],
    kubectl: Kubectl,
    run: Run = subprocess.run,
    timeout: int = 180,
    dry_run: bool = False,
) -> bool:
    """Restart and wait for every consumer of the (namespace, secret) pairs in CHANGED.

    Returns False if any restart or rollout fails: a Secret that is applied but
    not in use is the defect this exists to prevent, so it must not read as success.
    With DRY_RUN, names the workloads a real run would restart and touches none.
    """
    ok = True
    for namespace in sorted({ns for ns, _ in changed}):
        secrets = {name for ns, name in changed if ns == namespace}
        listed = run(
            [*kubectl(namespace), "get", ",".join(WORKLOAD_KINDS), "-o", "json"],
            capture_output=True,
            text=True,
            check=False,
        )
        if listed.returncode != 0:
            logger.error(f"  Could not list workloads in {namespace} to restart: {listed.stderr.strip()}")
            ok = False
            continue
        targets = consumers(json.loads(listed.stdout).get("items", []), secrets)
        if not targets:
            logger.info(f"  No workload in {namespace} reads {', '.join(sorted(secrets))}; nothing to restart")
        for target in targets:
            if namespace == "kube-system":
                # Traefik reads the CrowdSec bouncer key and is the only ingress:
                # its restart interrupts every route for the rollout (#1810).
                logger.warning(f"  Restarting {namespace}/{target} interrupts cluster ingress while it rolls out")
            if dry_run:
                logger.info(f"  [DRY-RUN] a real run would restart {namespace}/{target}")
                continue
            ok = _restart(target, namespace, kubectl, run, timeout) and ok
    return ok


def _restart(target: str, namespace: str, kubectl: Kubectl, run: Run, timeout: int) -> bool:
    restarted = run([*kubectl(namespace), "rollout", "restart", target], capture_output=True, text=True, check=False)
    if restarted.returncode != 0:
        logger.error(f"  Restart of {namespace}/{target} failed: {restarted.stderr.strip()}")
        return False
    rolled = run(
        [*kubectl(namespace), "rollout", "status", target, f"--timeout={timeout}s"],
        capture_output=True,
        text=True,
        check=False,
    )
    if rolled.returncode != 0:
        logger.error(f"  {namespace}/{target} did not become ready within {timeout}s: {rolled.stderr.strip()}")
        return False
    logger.success(f"  Restarted {namespace}/{target}: it now reads the changed Secret")
    return True
