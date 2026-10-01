"""A restore window: stop Argo CD putting an app back while its data is replaced (BACKUP-070, #1998).

Restoring an app's data means stopping the app first, and on prod Argo CD runs
`selfHeal: true`: a `kubectl scale --replicas=0` is reverted within seconds,
so the app comes back up on the half-replaced data. Staging runs
`selfHeal: false`, which only holds until master moves (lesson-330).

The window pauses automated sync on the env's Application by setting
`spec.syncPolicy.automated.enabled: false` (verified on the hub's CRD,
2026-10-01). Argo CD has no per-resource switch, so the whole env stops
receiving merges while a window is open. That is why the window is a named,
held object rather than a flag:

- **Open** writes the pause and a holder annotation in one merge patch,
  under the read's `resourceVersion`, then scales the Deployment to zero and
  waits until no pod mounts its claims. A held window refuses a second open
  and names the holder; there is no force, because the way out is the close.
- **Close** restores the sync policy declared in git (the object
  `make deploy-apps` applies), never a copy taken at open, so a window cannot
  launder a hand edit into the cluster. Re-enabling sync alone does not bring
  the replicas back (with `selfHeal: false` a scale at an unchanged revision
  is never corrected), so the close also triggers one sync and waits for
  Synced/Healthy and ready replicas.

Every outcome other than "done" is an error that says whether the window is
still open, because an open window silently stops deploys to that env.
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

ANNOTATION = "kubelab.live/restore-window"
HUB_NAMESPACE = "argocd"
APP_NAMESPACE = "kubelab"

# One retry absorbs a status write between the read and the patch (Argo CD's
# controller bumps the resourceVersion on every one); a second conflict in a
# row is contention worth surfacing. Same rule as argo_manager.set_revision.
_PATCH_ATTEMPTS = 2
_POLL_SECONDS = 5.0

Run = Callable[[list[str]], "tuple[int, str, str]"]


class WindowError(Exception):
    """The window could not be opened or closed; the message says whether it is still open."""


class WindowHeldError(WindowError):
    """Another restore holds the window on this env."""


#: Seconds one kubectl call may take. The poll budgets cannot bound a call that never returns.
_CALL_TIMEOUT = 60


def _default_run(argv: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=_CALL_TIMEOUT)
    except subprocess.TimeoutExpired:
        return 124, "", f"kubectl timed out after {_CALL_TIMEOUT}s"
    return proc.returncode, proc.stdout, proc.stderr


def _kubectl(kubeconfig: str, namespace: str, *args: str) -> list[str]:
    return ["kubectl", "--kubeconfig", kubeconfig, "-n", namespace, *args]


def _json(run: Run, argv: list[str]) -> dict[str, Any]:
    rc, out, err = run(argv)
    if rc != 0:
        raise WindowError(f"`{' '.join(argv[5:8])}` failed: {err.strip()[:200]}")
    return json.loads(out)


def application_name(env: str) -> str:
    return f"kubelab-{env}"


def declared_sync_policy(applications_dir: Path, env: str) -> dict[str, Any]:
    """The `spec.syncPolicy` of the env's Application as committed, which `make deploy-apps` applies."""
    path = Path(applications_dir) / f"{env}.yaml"
    for doc in yaml.safe_load_all(path.read_text()):
        if isinstance(doc, dict) and doc.get("kind") == "Application":
            return doc["spec"]["syncPolicy"]
    raise WindowError(f"{path} declares no Application")


def _holder(app: dict[str, Any]) -> Optional[dict[str, Any]]:
    raw = ((app.get("metadata") or {}).get("annotations") or {}).get(ANNOTATION)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"deployment": "?", "by": "?", "since": "?", "raw": raw}


def _describe(holder: dict[str, Any]) -> str:
    return f"deployment '{holder.get('deployment')}', held by {holder.get('by')} since {holder.get('since')}"


def replace_with(live: Any, desired: Any) -> Any:
    """The merge patch that turns `live` into exactly `desired`.

    A merge patch only adds and overwrites; a key it does not mention survives.
    So every key live has and desired lacks is sent as null, which RFC 7386
    reads as "remove" (this is how the close drops `automated.enabled`).
    """
    if not (isinstance(live, dict) and isinstance(desired, dict)):
        return desired
    patch: dict[str, Any] = {key: None for key in live if key not in desired}
    for key, value in desired.items():
        if key in live and live[key] == value:
            continue
        patch[key] = replace_with(live.get(key), value)
    return patch


def _patch_application(
    run: Run,
    hub: str,
    name: str,
    build: Callable[[dict[str, Any]], Optional[dict[str, Any]]],
) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """Read, build a patch from the read, and send it under the read's resourceVersion.

    Returns (the object as read, the patch sent), or (read, None) when `build` decides there is nothing to do.
    """
    for attempt in range(_PATCH_ATTEMPTS):
        before = _json(run, _kubectl(hub, HUB_NAMESPACE, "get", "application", name, "-o", "json"))
        body = build(before)
        if body is None:
            return before, None
        body.setdefault("metadata", {})["resourceVersion"] = before["metadata"]["resourceVersion"]
        rc, _, err = run(
            _kubectl(hub, HUB_NAMESPACE, "patch", "application", name, "--type", "merge", "-p", json.dumps(body))
        )
        if rc == 0:
            return before, body
        if "conflict" not in err.lower() or attempt == _PATCH_ATTEMPTS - 1:
            raise WindowError(f"patching application/{name} failed: {err.strip()[:200]}")
    raise AssertionError("unreachable")


def _claims(deployment: dict[str, Any]) -> set[str]:
    volumes = deployment["spec"]["template"]["spec"].get("volumes") or []
    return {v["persistentVolumeClaim"]["claimName"] for v in volumes if v.get("persistentVolumeClaim")}


def _blocking_pods(pods: list[dict[str, Any]], labels: dict[str, str], claims: set[str]) -> list[str]:
    """Pods of the Deployment, or any pod that mounts one of its claims."""
    names = []
    for pod in pods:
        pod_labels = (pod.get("metadata") or {}).get("labels") or {}
        mounted = {
            v["persistentVolumeClaim"]["claimName"]
            for v in (pod.get("spec") or {}).get("volumes") or []
            if v.get("persistentVolumeClaim")
        }
        if all(pod_labels.get(k) == v for k, v in labels.items()) or mounted & claims:
            names.append(pod["metadata"]["name"])
    return names


def open_window(
    *,
    env: str,
    deployment: str,
    hub_kubeconfig: str,
    spoke_kubeconfig: str,
    holder: str,
    run: Run = _default_run,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    timeout: float = 300.0,
) -> dict[str, Any]:
    """Pause the env's auto-sync, take the window, scale `deployment` to zero. Returns the policy replaced."""
    name = application_name(env)
    since = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stamp = json.dumps({"deployment": deployment, "by": holder, "since": since}, sort_keys=True)

    def build(app: dict[str, Any]) -> dict[str, Any]:
        held = _holder(app)
        if held is not None:
            raise WindowHeldError(f"{name} already has a restore window open: {_describe(held)}. Close it first.")
        if not isinstance(app["spec"].get("syncPolicy", {}).get("automated"), dict):
            raise WindowError(f"{name} has no automated sync to pause; nothing would put {deployment} back")
        return {
            "metadata": {"annotations": {ANNOTATION: stamp}},
            "spec": {"syncPolicy": {"automated": {"enabled": False}}},
        }

    before, _ = _patch_application(run, hub_kubeconfig, name, build)
    replaced: dict[str, Any] = before["spec"]["syncPolicy"]

    still_open = f"The window stays open: close it with `make restore-window APP={deployment} ENV={env} END=1`."
    started = clock()
    # A sync Argo CD started before the pause keeps running, and it would put the
    # replicas back after the scale below. Pausing stops new ones only.
    while True:
        app = _json(run, _kubectl(hub_kubeconfig, HUB_NAMESPACE, "get", "application", name, "-o", "json"))
        phase = ((app.get("status") or {}).get("operationState") or {}).get("phase")
        if not app.get("operation") and phase != "Running":
            break
        if clock() - started >= timeout:
            raise WindowError(f"after {timeout:.0f}s {name} is still syncing; nothing was scaled. {still_open}")
        sleep(_POLL_SECONDS)

    rc, _, err = run(_kubectl(spoke_kubeconfig, APP_NAMESPACE, "scale", f"deployment/{deployment}", "--replicas=0"))
    if rc != 0:
        raise WindowError(f"scaling deployment/{deployment} to zero failed: {err.strip()[:200]}. {still_open}")

    spec = _json(run, _kubectl(spoke_kubeconfig, APP_NAMESPACE, "get", "deployment", deployment, "-o", "json"))
    selector = spec["spec"].get("selector") or {}
    labels = selector.get("matchLabels") or {}
    if selector.get("matchExpressions") or not labels:
        # Only matchLabels is evaluated; an empty set would match every pod in the namespace.
        raise WindowError(
            f"deployment/{deployment}'s selector is not plain matchLabels, which is all the window evaluates. "
            f"{still_open}"
        )
    claims = _claims(spec)
    while True:
        pods = _json(run, _kubectl(spoke_kubeconfig, APP_NAMESPACE, "get", "pods", "-o", "json"))["items"]
        blocking = _blocking_pods(pods, labels, claims)
        if not blocking:
            return replaced
        if clock() - started >= timeout:
            raise WindowError(
                f"after {timeout:.0f}s these pods still run or mount {sorted(claims)}: {blocking}. {still_open}"
            )
        sleep(_POLL_SECONDS)


def close_window(
    *,
    env: str,
    applications_dir: Path,
    hub_kubeconfig: str,
    spoke_kubeconfig: str,
    run: Run = _default_run,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    timeout: float = 600.0,
) -> Optional[dict[str, Any]]:
    """Restore git's sync policy, release the window, sync, and wait for the app. None if no window was open."""
    name = application_name(env)
    declared = declared_sync_policy(applications_dir, env)
    held: dict[str, Any] = {}

    def build(app: dict[str, Any]) -> Optional[dict[str, Any]]:
        found = _holder(app)
        if found is None:
            return None
        held.update(found)
        return {
            "metadata": {"annotations": {ANNOTATION: None}},
            "spec": {"syncPolicy": replace_with(app["spec"].get("syncPolicy") or {}, declared)},
        }

    before, sent = _patch_application(run, hub_kubeconfig, name, build)
    if sent is None:
        return None
    named = held.get("deployment")
    deployment = named if isinstance(named, str) and named not in ("", "?") else ""

    # Re-enabling auto-sync can start a sync by itself (it does whenever git
    # moved since the last one, measured on staging 2026-10-01). Writing
    # `operation` over one already running would replace it, so the sync is
    # sent only when none is pending or running, under the read's
    # resourceVersion. Otherwise Argo CD is already syncing; the wait below
    # judges the outcome either way.
    def build_sync(app: dict[str, Any]) -> Optional[dict[str, Any]]:
        running = ((app.get("status") or {}).get("operationState") or {}).get("phase") == "Running"
        if app.get("operation") or running:
            return None
        revision = app["spec"]["source"]["targetRevision"]
        return {"operation": {"initiatedBy": {"username": "restore-window"}, "sync": {"revision": revision}}}

    try:
        _patch_application(run, hub_kubeconfig, name, build_sync)
    except WindowError as exc:
        raise WindowError(
            f"the window is closed, but triggering the sync failed: {exc}. "
            f"Run `make sync-app APP={name}` and check {deployment or 'the app'} comes back."
        ) from exc
    if not deployment:
        raise WindowError(
            f"the window is closed and the sync requested, but its annotation names no deployment, "
            f"so nothing was waited for. Check {name} is Synced/Healthy and the restored app's replicas are ready."
        )

    started = clock()
    while True:
        app = _json(run, _kubectl(hub_kubeconfig, HUB_NAMESPACE, "get", "application", name, "-o", "json"))
        dep = _json(run, _kubectl(spoke_kubeconfig, APP_NAMESPACE, "get", "deployment", deployment, "-o", "json"))
        sync = (app.get("status") or {}).get("sync", {}).get("status", "Unknown")
        health = (app.get("status") or {}).get("health", {}).get("status", "Unknown")
        want = int(dep["spec"].get("replicas") or 0)
        ready = int((dep.get("status") or {}).get("readyReplicas") or 0)
        if sync == "Synced" and health == "Healthy" and want > 0 and ready == want:
            return before["spec"]["syncPolicy"]
        if clock() - started >= timeout:
            raise WindowError(
                f"the window is closed, but after {timeout:.0f}s {name} is {sync}/{health} and "
                f"deployment/{deployment} has {ready}/{want} replicas ready"
            )
        sleep(_POLL_SECONDS)


def held_windows(hub_kubeconfig: str, run: Run = _default_run) -> list[tuple[str, str]]:
    """Every Application on the hub that holds a restore window, as (name, description)."""
    apps = _json(run, _kubectl(hub_kubeconfig, HUB_NAMESPACE, "get", "applications", "-o", "json"))["items"]
    held = []
    for app in apps:
        found = _holder(app)
        if found is not None:
            held.append((app["metadata"]["name"], _describe(found)))
    return held
