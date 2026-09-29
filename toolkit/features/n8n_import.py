"""Git+SOPS → n8n workflow/credential import (TOOL-009, surfaced by NOTIFY-001).

n8n stores workflows + credentials in an encrypted SQLite DB. A fresh cluster or a
wiped `n8n-data` PVC loses them. This module reconstructs the `notify-router`
workflow AND its Header Auth credential from git (the workflow JSON) + SOPS (the
webhook secret) without touching the n8n UI — "cattle, not pets" applied to n8n.

Pattern lineage:
  - SOPS → render → inject mirrors `k8s_middlewares.apply_middleware_secrets`
    (ADR-035): the secret is read in memory and never persisted to the repo.
  - `kubectl exec` into the pod mirrors `scripts/configure_oidc.py`.

Secret hygiene (acceptance criterion): the webhook secret travels into the pod via
stdin → a tmpfs file under `/dev/shm` (RAM, never persistent disk) → `n8n
import:credentials` → shredded. It is NEVER passed on argv (which `ps` and the
process table would leak) and NEVER written under the repo.

Idempotency: both ids are SSOT-ed inside the workflow JSON — the root `id`
(workflow upsert + `update:workflow --id`) and the node's `httpHeaderAuth.id`
(credential link + credential upsert). Re-running is an upsert, not a duplicate;
deleting the workflow in n8n and re-running restores it identically.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from toolkit.core.logging import logger
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.k8s_kubeconfig import output_path

# n8n Header Auth credential shape. The webhook node compares the incoming header
# byte-for-byte against `data.value`; the Bearer scheme (RFC 6750) is the contract
# every source must send (`Authorization: Bearer <secret>`).
_CREDENTIAL_TYPE = "httpHeaderAuth"
_HEADER_NAME = "Authorization"
_AUTH_SCHEME = "Bearer"

_NAMESPACE = "kubelab"
_DEPLOYMENT = "deploy/n8n"
# Mirrors `spec.selector.matchLabels` of the Deployment in
# `infra/k8s/base/services/n8n.yaml` (asserted by tests/test_n8n_import_restart.py).
_POD_SELECTOR = "app.kubernetes.io/name=n8n"


@dataclass(frozen=True)
class N8nImportSpec:
    """Declarative definition of a workflow to reconstruct from git + SOPS.

    Add one entry to N8N_IMPORT_CATALOG per versioned workflow. The MVP design
    imports a single workflow; iterating the catalog extends to many without
    rework.
    """

    workflow_path: Path
    """Workflow JSON path RELATIVE to project_root (the git-versioned source)."""

    secret_key_path: str
    """SOPS dotted path for the Header Auth secret (e.g. `apps.….webhook_secret`)."""

    credential_name: str
    """n8n credential name referenced by the workflow node (e.g. `notify-webhook`)."""

    envs: frozenset[str] = field(default_factory=lambda: frozenset({"staging"}))
    """Envs where this import applies. NOTIFY-001 MVP is staging-only."""

    namespace: str = _NAMESPACE
    """K8s namespace hosting the n8n deployment."""

    deployment: str = _DEPLOYMENT
    """The Deployment restarted once the run has imported everything (e.g. `deploy/n8n`)."""

    pod_selector: str = _POD_SELECTOR
    """Label selector for the Deployment's pods. Every exec targets one of them by
    name, never `deployment`, because kubectl may resolve a Deployment to a pod
    that is not Ready (#1863)."""


# ── Registry ──────────────────────────────────────────────────────────────────
# Single source of truth for which workflows get imported, and from where.

N8N_IMPORT_CATALOG: list[N8nImportSpec] = [
    N8nImportSpec(
        workflow_path=Path("infra/n8n/workflows/notify-router.json"),
        secret_key_path="apps.services.automation.notify.webhook_secret",
        credential_name="notify-webhook",
        envs=frozenset({"staging", "prod"}),
    ),
    N8nImportSpec(
        workflow_path=Path("infra/n8n/workflows/multi-forge-sync.json"),
        secret_key_path="apps.services.automation.notify.webhook_secret",
        credential_name="multi-forge-webhook",
        envs=frozenset({"staging", "prod"}),
    ),
    N8nImportSpec(
        workflow_path=Path("infra/n8n/workflows/slack-task-capture.json"),
        secret_key_path="apps.services.automation.notify.webhook_secret",
        credential_name="slack-webhook",
        envs=frozenset({"staging", "prod"}),
    ),
    N8nImportSpec(
        workflow_path=Path("infra/n8n/workflows/agent-dispatcher.json"),
        secret_key_path="apps.services.automation.notify.webhook_secret",
        credential_name="agent-dispatcher-webhook",
        envs=frozenset({"staging", "prod"}),
    ),
]


# ── Placeholders ──────────────────────────────────────────────────────────────
#
# A committed workflow may carry `RESOLVE_*` tokens filled from SSOT at import
# time, the same convention `cluster_bootstrap` uses for
# `RESOLVE_RPI4_TAILSCALE_IP` (ADR-047 D2, `k8s_render._PLACEHOLDER_RE`).
#
# Why not an env var on the pod: `n8n-config` is a plain ConfigMap, not a
# `configMapGenerator` entry, and n8n reads env once at container start. A
# changed key would leave the running pod on the old value while Argo CD reported
# Synced/Healthy — the silent no-op of lesson-404. Substituting into the imported
# document means there is no second place for the value to be stale in.

#: Every placeholder this module knows how to fill, mapped to its SSOT path.
#: Adding a token to a workflow without adding it here fails the import rather
#: than shipping the literal string — a workflow searching Vikunja for a project
#: whose title is the token itself would fail closed, but it would fail in
#: production instead of at the point the mistake was made.
#:
#: NOTE FOR ANYONE DOCUMENTING THIS: the scanner cannot tell a mention from a
#: use. Spelling another subsystem's token inside a workflow comment makes the
#: import demand a mapping for it — measured, by writing exactly that comment
#: and watching six tests go red. Refer to other placeholders by description,
#: not by name, inside any file this runs over.
PLACEHOLDER_SSOT: dict[str, str] = {
    "RESOLVE_VIKUNJA_DEFAULT_PROJECT": "apps.services.core.vikunja.default_project",
}

_PLACEHOLDER_RE = re.compile(r"RESOLVE_[A-Z0-9_]+")


class PlaceholderError(Exception):
    """A `RESOLVE_*` token is unknown, or its SSOT path holds nothing."""


def resolve_placeholders(text: str, cm: ConfigurationManager) -> str:
    """Fill every `RESOLVE_*` token from SSOT, or refuse.

    FAILS CLOSED on an unknown token and on a declared path that resolves to
    nothing. Substituting an empty string would be worse than not substituting:
    the workflow would look for a project titled `''`, match nothing, and answer
    a correct-looking 422 that names no cause.
    """
    found = set(_PLACEHOLDER_RE.findall(text))
    if not found:
        return text

    unknown = found - set(PLACEHOLDER_SSOT)
    if unknown:
        raise PlaceholderError(
            f"workflow carries unmapped placeholder(s) {sorted(unknown)}. Add each to "
            f"`PLACEHOLDER_SSOT` with the common.yaml path it reads, or remove it from "
            f"the workflow — an unsubstituted token reaches the running workflow as a "
            f"literal string."
        )

    config = cm.get_merged_config()
    for token in sorted(found):
        path = PLACEHOLDER_SSOT[token]
        node: Any = config
        for part in path.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        value = "" if node is None else str(node).strip()
        if not value:
            raise PlaceholderError(
                f"placeholder {token} maps to `{path}`, which is absent or empty in the "
                f"merged config. It is required rather than defaulted: a workflow that "
                f"substitutes an empty value fails in production and names no cause."
            )
        text = text.replace(token, value)
        logger.info(f"  Resolved {token} -> {value!r} (from {path})")

    return text


# ── Pure helpers ──────────────────────────────────────────────────────────────


def render_credential(credential_id: str, credential_name: str, secret: str) -> str:
    """Build the JSON file content for `n8n import:credentials` (pure function).

    Output is a JSON ARRAY of one credential object — the shape
    `export:credentials` emits and `import:credentials --input=FILE` (no
    `--separate`) consumes. `json.dumps` escapes the secret correctly even if it
    carries quotes/backslashes (a textual template would not).
    """
    payload = [
        {
            "id": credential_id,
            "name": credential_name,
            "type": _CREDENTIAL_TYPE,
            "data": {"name": _HEADER_NAME, "value": f"{_AUTH_SCHEME} {secret}"},
        }
    ]
    return json.dumps(payload, indent=2)


def read_workflow_ids(workflow: dict[str, Any]) -> tuple[str, str | None]:
    """Return `(workflow_id, credential_id)` read from the workflow JSON.

    Both ids are the single source of truth — fixed in the committed JSON so
    import is an idempotent upsert. If no node carries httpHeaderAuth credentials,
    returns (workflow_id, None) for workflows verifying signatures internally.
    """
    workflow_id = workflow.get("id")
    if not workflow_id:
        raise ValueError("workflow JSON has no root 'id' — required for idempotent upsert (TOOL-009)")

    for node in workflow.get("nodes", []):
        cred = (node.get("credentials") or {}).get(_CREDENTIAL_TYPE)
        if cred and cred.get("id"):
            return str(workflow_id), str(cred["id"])

    return str(workflow_id), None


def _kubeconfig_for(env: str) -> str:
    return str(output_path(env))


# A POSIX-sh snippet run inside the pod: read stdin into a tmpfs file under
# /dev/shm (RAM, never persistent disk), import it, then shred/rm it on exit.
# The secret arrives via stdin, so it never appears on argv. `shred` is absent on
# busybox/alpine images → fall back to rm (on tmpfs there are no physical blocks
# to scrub anyway).
_IMPORT_SCRIPT = (
    "set -eu\n"
    'f="$(mktemp /dev/shm/{prefix}.XXXXXX)"\n'
    'trap \'shred -u "$f" 2>/dev/null || rm -f "$f"\' EXIT\n'
    'cat > "$f"\n'
    'n8n {subcommand} --input="$f"\n'
)


# ── Public API ────────────────────────────────────────────────────────────────


def import_n8n_workflow(env: str, project_root: Path, dry_run: bool = False) -> bool:
    """Reconstruct every workflow in N8N_IMPORT_CATALOG that targets `env`.

    Returns True iff every applicable workflow imported + activated (or all were
    out of scope for `env`, a successful no-op). Fails loudly (returns False, no
    `kubectl`) if a precondition is unmet — missing SOPS secret, unreadable
    workflow, or absent ids.
    """
    logger.section(f"n8n workflow import — {env.upper()}")

    applicable = [s for s in N8N_IMPORT_CATALOG if env in s.envs]
    if not applicable:
        logger.info(f"No workflows registered for env={env} — nothing to do.")
        return True

    cm = ConfigurationManager(env, project_root)

    landed = [spec for spec in applicable if _process_spec(spec, env, project_root, cm, dry_run)]
    all_ok = len(landed) == len(applicable)

    # Restart ONCE, after every workflow is in. The CLI writes to SQLite, but the
    # running process caches workflows + the webhook registry in memory (same class
    # of gotcha as Gitea OIDC, CLAUDE.md): without a restart no imported webhook is
    # registered. A restart per workflow bounced the pod under the next workflow's
    # exec and failed it (#1863). The workflows that did land still need their
    # restart when another one failed, so a partial run restarts too.
    if landed and not dry_run:
        for spec in {(s.namespace, s.deployment): s for s in landed}.values():
            if not _restart_n8n(env, spec):
                logger.error(f"  {spec.deployment} restart failed — workflows imported but not live")
                all_ok = False

    if all_ok:
        logger.success(f"Imported {len(applicable)} workflow(s) for {env}")
    else:
        logger.error("One or more workflow imports failed — see errors above")
    return all_ok


# ── Internals ─────────────────────────────────────────────────────────────────


def _process_spec(
    spec: N8nImportSpec,
    env: str,
    project_root: Path,
    cm: ConfigurationManager,
    dry_run: bool,
) -> bool:
    """Import + activate a single workflow. Returns True on success."""
    logger.info(f"Processing workflow: {spec.workflow_path.name} (credential={spec.credential_name})")

    workflow_full = project_root / spec.workflow_path
    if not workflow_full.is_file():
        logger.error(f"  Workflow not found at '{workflow_full}' — aborting")
        return False

    try:
        workflow_text = workflow_full.read_text()
    except OSError as exc:
        logger.error(f"  Failed to read workflow '{workflow_full}': {exc}")
        return False

    try:
        workflow_text = resolve_placeholders(workflow_text, cm)
    except PlaceholderError as exc:
        logger.error(f"  {exc}")
        return False

    try:
        workflow_doc = json.loads(workflow_text)
    except json.JSONDecodeError as exc:
        logger.error(f"  Failed to parse workflow '{workflow_full}': {exc}")
        return False

    try:
        workflow_id, credential_id = read_workflow_ids(workflow_doc)
    except ValueError as exc:
        logger.error(f"  {exc}")
        return False

    credential_json = None
    if credential_id and spec.secret_key_path:
        secret = cm.get_secret_by_path(spec.secret_key_path)
        if not secret:
            logger.error(f"  Missing SOPS value at '{spec.secret_key_path}' — cannot import credential")
            return False
        credential_json = render_credential(credential_id, spec.credential_name, secret)

    if dry_run:
        logger.info(
            f"  [DRY-RUN] Would import credential '{spec.credential_name}' (id={credential_id}) "
            f"+ workflow id={workflow_id}, then activate it (cluster not touched)"
        )
        return True

    # 1. Credential — carries the secret; stdin → /dev/shm → import → shred.
    if credential_json:
        if not _exec_stdin_import(env, spec, "import:credentials", "n8n-cred", credential_json):
            logger.error("  Credential import failed — workflow not imported")
            return False

    # 2. Workflow — not secret, but absent from the PVC; pipe via stdin too.
    if not _exec_stdin_import(env, spec, "import:workflow", "n8n-wf", workflow_text):
        logger.error("  Workflow import failed — not activated")
        return False

    # 3. Publish (no API key needed). n8n deprecated `update:workflow --active`
    #    in favour of `publish:workflow --id` — we use the current command.
    if not _exec_publish(env, spec, workflow_id):
        logger.error(f"  Publish failed for workflow id={workflow_id}")
        return False

    # The restart that makes it live runs once per run, in `import_n8n_workflow`.
    logger.success(f"  Imported + published '{spec.workflow_path.name}' (workflow id={workflow_id})")
    return True


def _exec_stdin_import(env: str, spec: N8nImportSpec, subcommand: str, prefix: str, payload: str) -> bool:
    """`kubectl exec -i … -- sh -c <script>` with `payload` on stdin.

    The payload (credential JSON or workflow JSON) reaches the pod via stdin only,
    so it never lands on argv. `sh -c` writes it to /dev/shm, imports, shreds.
    """
    script = _IMPORT_SCRIPT.format(prefix=prefix, subcommand=subcommand)
    return _exec(env, spec, subcommand, ["sh", "-c", script], stdin=payload)


def _exec_publish(env: str, spec: N8nImportSpec, workflow_id: str) -> bool:
    return _exec(env, spec, "publish:workflow", ["n8n", "publish:workflow", f"--id={workflow_id}"])


def _exec(env: str, spec: N8nImportSpec, what: str, argv: list[str], stdin: str | None = None) -> bool:
    """Run `argv` in a live n8n pod, named, retrying once on a freshly resolved one.

    A liveness-probe restart (see #1009 — n8n gets CPU-throttled under its 1-core
    limit, `/healthz` times out, kubelet kills the container) SIGKILLs any exec
    session in flight, surfaced as exit 137. That is a transient condition, not a
    real import failure — retrying immediately would race the same restart, so
    wait for the deployment to report Ready again, then resolve the pod again.
    Every failure names the pod it ran against (#1863 AC3).
    """
    kc = _kubeconfig_for(env)
    for attempt in (1, 2):
        pod = _live_pod(env, spec)
        if pod is None:
            logger.error(f"  {what}: no Ready n8n pod matches '{spec.pod_selector}' in {spec.namespace}")
        else:
            stdin_flag = ["-i"] if stdin is not None else []
            cmd = ["kubectl", "exec", *stdin_flag, "-n", spec.namespace, f"pod/{pod}", "--kubeconfig", kc, "--", *argv]
            if _run(cmd, stdin=stdin, label=f"{what} in pod/{pod}"):
                return True
            logger.error(f"  pod/{pod} now: {_pod_record(env, spec, pod)}")
        if attempt == 1:
            logger.info(f"  Waiting for {spec.deployment} to be ready before retrying {what}...")
            _wait_rollout_ready(env, spec)
    return False


def _live_pod(env: str, spec: N8nImportSpec) -> str | None:
    """Name of a pod of `spec` that is Running, Ready and not being deleted."""
    pods = _list_pods(env, spec)
    return next((p["metadata"]["name"] for p in pods or [] if _is_live(p)), None)


def _pod_record(env: str, spec: N8nImportSpec, name: str) -> str:
    """What the pod says about itself after a failed exec.

    A container killed mid-exec (OOM, liveness) and a real import error both
    surface as a failed `kubectl exec`; only the pod's restart count and last
    termination tell them apart.
    """
    pod = next((p for p in _list_pods(env, spec) or [] if p["metadata"]["name"] == name), None)
    if pod is None:
        return "gone"
    parts = ["deleting"] if pod["metadata"].get("deletionTimestamp") else []
    for status in pod.get("status", {}).get("containerStatuses", []):
        last = status.get("lastState", {}).get("terminated") or {}
        died = f" last={last.get('reason')}/{last.get('exitCode')} at={last.get('finishedAt')}" if last else ""
        parts.append(f"{status.get('name')} restarts={status.get('restartCount', 0)}{died}")
    return ", ".join(parts) or "no container status"


def _list_pods(env: str, spec: N8nImportSpec) -> list[dict[str, Any]] | None:
    cmd = [
        "kubectl",
        "get",
        "pods",
        "-n",
        spec.namespace,
        "-l",
        spec.pod_selector,
        "--kubeconfig",
        _kubeconfig_for(env),
        "-o",
        "json",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        pods: list[dict[str, Any]] = json.loads(result.stdout).get("items", [])
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        logger.error(f"  Listing n8n pods failed: {(getattr(exc, 'stderr', None) or str(exc)).strip()}")
        return None
    return pods


def _is_live(pod: dict[str, Any]) -> bool:
    if pod.get("metadata", {}).get("deletionTimestamp"):
        return False
    status = pod.get("status", {})
    ready = any(c.get("type") == "Ready" and c.get("status") == "True" for c in status.get("conditions", []))
    return status.get("phase") == "Running" and ready


def _restart_n8n(env: str, spec: N8nImportSpec) -> bool:
    """Roll the n8n deployment so the imported workflow + webhook registry reload.

    CLI changes land in SQLite but the live process caches them; n8n prints
    "Changes will not take effect if n8n is running. Please restart n8n." We
    restart and wait for the rollout so a failed import surfaces immediately.
    """
    kc = _kubeconfig_for(env)
    restart = ["kubectl", "rollout", "restart", spec.deployment, "-n", spec.namespace, "--kubeconfig", kc]
    if not _run(restart):
        return False
    status = [
        "kubectl",
        "rollout",
        "status",
        spec.deployment,
        "-n",
        spec.namespace,
        "--kubeconfig",
        kc,
        "--timeout=120s",
    ]
    return _run(status)


def _run(cmd: list[str], stdin: str | None = None, label: str | None = None) -> bool:
    """Run a kubectl command; return True on success, log stderr on failure."""
    try:
        result = subprocess.run(cmd, input=stdin, capture_output=True, text=True, check=True)
        if result.stdout.strip():
            logger.info(f"  {result.stdout.strip()}")
        return True
    except subprocess.CalledProcessError as exc:
        logger.error(f"  {label or ' '.join(cmd[:6])} … failed: {(exc.stderr or str(exc)).strip()}")
        return False


def _wait_rollout_ready(env: str, spec: N8nImportSpec, timeout: str = "60s") -> bool:
    """Block until `spec.deployment` reports its rollout Ready, or `timeout` elapses."""
    cmd = [
        "kubectl",
        "rollout",
        "status",
        spec.deployment,
        "-n",
        spec.namespace,
        "--kubeconfig",
        _kubeconfig_for(env),
        f"--timeout={timeout}",
    ]
    return _run(cmd)
