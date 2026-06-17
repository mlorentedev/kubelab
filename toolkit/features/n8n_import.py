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
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from toolkit.core.logging import logger
from toolkit.features.configuration import ConfigurationManager

# n8n Header Auth credential shape. The webhook node compares the incoming header
# byte-for-byte against `data.value`; the Bearer scheme (RFC 6750) is the contract
# every source must send (`Authorization: Bearer <secret>`).
_CREDENTIAL_TYPE = "httpHeaderAuth"
_HEADER_NAME = "Authorization"
_AUTH_SCHEME = "Bearer"

_NAMESPACE = "kubelab"
_DEPLOYMENT = "deploy/n8n"


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
    """`kubectl exec` target (e.g. `deploy/n8n`)."""


# ── Registry ──────────────────────────────────────────────────────────────────
# Single source of truth for which workflows get imported, and from where.

N8N_IMPORT_CATALOG: list[N8nImportSpec] = [
    N8nImportSpec(
        workflow_path=Path("infra/n8n/workflows/notify-router.json"),
        secret_key_path="apps.services.automation.notify.webhook_secret",
        credential_name="notify-webhook",
        envs=frozenset({"staging", "prod"}),
    ),
]


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


def read_workflow_ids(workflow: dict[str, Any]) -> tuple[str, str]:
    """Return `(workflow_id, credential_id)` read from the workflow JSON.

    Both ids are the single source of truth — fixed in the committed JSON so
    import is an idempotent upsert. Raises ValueError if either is absent (a
    missing id would make import non-idempotent → silent duplicates).
    """
    workflow_id = workflow.get("id")
    if not workflow_id:
        raise ValueError("workflow JSON has no root 'id' — required for idempotent upsert (TOOL-009)")

    for node in workflow.get("nodes", []):
        cred = (node.get("credentials") or {}).get(_CREDENTIAL_TYPE)
        if cred and cred.get("id"):
            return str(workflow_id), str(cred["id"])

    raise ValueError(f"no node carries a {_CREDENTIAL_TYPE} credential id — cannot link credential")


def _kubeconfig_for(env: str) -> str:
    return os.path.expanduser(f"~/.kube/kubelab-{env}-config")


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

    all_ok = True
    for spec in applicable:
        all_ok = _process_spec(spec, env, project_root, cm, dry_run) and all_ok

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

    secret = cm.get_secret_by_path(spec.secret_key_path)
    if not secret:
        logger.error(f"  Missing SOPS value at '{spec.secret_key_path}' — cannot import credential")
        return False

    workflow_full = project_root / spec.workflow_path
    if not workflow_full.is_file():
        logger.error(f"  Workflow not found at '{workflow_full}' — aborting")
        return False

    try:
        workflow_text = workflow_full.read_text()
        workflow_doc = json.loads(workflow_text)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error(f"  Failed to read/parse workflow '{workflow_full}': {exc}")
        return False

    try:
        workflow_id, credential_id = read_workflow_ids(workflow_doc)
    except ValueError as exc:
        logger.error(f"  {exc}")
        return False

    credential_json = render_credential(credential_id, spec.credential_name, secret)

    if dry_run:
        logger.info(
            f"  [DRY-RUN] Would import credential '{spec.credential_name}' (id={credential_id}) "
            f"+ workflow id={workflow_id}, then activate it (cluster not touched)"
        )
        return True

    # 1. Credential — carries the secret; stdin → /dev/shm → import → shred.
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

    # 4. Restart n8n. The CLI writes to SQLite, but the running process caches
    #    workflows + the webhook registry in memory (same class of gotcha as
    #    Gitea OIDC, CLAUDE.md). Without a restart the /webhook/notify trigger is
    #    never registered and the route stays dead — n8n itself warns about this.
    if not _restart_n8n(env, spec):
        logger.error("  n8n restart failed — workflow imported but not live")
        return False

    logger.success(f"  Imported + published + restarted '{spec.workflow_path.name}' (workflow id={workflow_id})")
    return True


def _exec_stdin_import(env: str, spec: N8nImportSpec, subcommand: str, prefix: str, payload: str) -> bool:
    """`kubectl exec -i … -- sh -c <script>` with `payload` on stdin.

    The payload (credential JSON or workflow JSON) reaches the pod via stdin only,
    so it never lands on argv. `sh -c` writes it to /dev/shm, imports, shreds.
    """
    script = _IMPORT_SCRIPT.format(prefix=prefix, subcommand=subcommand)
    cmd = [
        "kubectl",
        "exec",
        "-i",
        "-n",
        spec.namespace,
        spec.deployment,
        "--kubeconfig",
        _kubeconfig_for(env),
        "--",
        "sh",
        "-c",
        script,
    ]
    return _run(cmd, stdin=payload)


def _exec_publish(env: str, spec: N8nImportSpec, workflow_id: str) -> bool:
    cmd = [
        "kubectl",
        "exec",
        "-n",
        spec.namespace,
        spec.deployment,
        "--kubeconfig",
        _kubeconfig_for(env),
        "--",
        "n8n",
        "publish:workflow",
        f"--id={workflow_id}",
    ]
    return _run(cmd)


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


def _run(cmd: list[str], stdin: str | None = None) -> bool:
    """Run a kubectl command; return True on success, log stderr on failure."""
    try:
        result = subprocess.run(cmd, input=stdin, capture_output=True, text=True, check=True)
        if result.stdout.strip():
            logger.info(f"  {result.stdout.strip()}")
        return True
    except subprocess.CalledProcessError as exc:
        logger.error(f"  {' '.join(cmd[:6])} … failed: {(exc.stderr or str(exc)).strip()}")
        return False
