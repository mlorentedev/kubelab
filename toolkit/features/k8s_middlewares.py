"""Traefik Middleware CRD rendering for API-key auth (ADR-035 Stage 1).

This module is the secret-injection plumbing for Traefik Middlewares whose body
must embed a SOPS-sourced API key (e.g. `dtomlinson91/traefik-api-key-middleware`).
Plain K8s Secrets (kind: Secret) live in `k8s_secrets.py`; Middleware CRDs are
a different beast (kind: Middleware, namespace-bound, Traefik-specific) and earn
their own module.

Flow per registered MiddlewareSpec:

  1. Read SOPS value at `spec.secret_key_path`.
  2. Read the template file at `spec.template_path` (gitignored output, committed
     `.tpl` source with `${API_KEY}`, `${NAME}`, `${NAMESPACE}`, `${SERVICE}` placeholders).
  3. Substitute placeholders.
  4. Write an audit copy to `infra/k8s/overlays/<env>/middlewares/.rendered/<spec.name>.yaml`
     (gitignored — the rendered file contains plaintext key). NOT the parallel
     `generated/` directory, which is committed for ArgoCD (ARGO-007).
  5. `kubectl apply -f -` with the rendered YAML on stdin.

Why kubectl-apply over Kustomize: the rendered Middleware contains a plaintext
API key. Persisting it in a git-tracked overlay is a no-go (secret in repo);
gitignoring it breaks `kubectl kustomize` in CI (resource not found). Imperative
apply with an audit copy threads both needles.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from toolkit.core.logging import logger
from toolkit.features.configuration import ConfigurationManager


@dataclass(frozen=True)
class MiddlewareSpec:
    """Declarative definition of a Traefik Middleware CRD that wraps a SOPS api_key.

    Add one entry to MIDDLEWARE_CATALOG per auth-protected service.
    """

    name: str
    """K8s metadata.name. Referenced from IngressRoute middleware list."""

    service: str
    """Logical service id. Cross-references SECRET_CATALOG and CLAUDE.md service list."""

    secret_key_path: str
    """SOPS dotted path (e.g. `apps.services.ai.ollama.api_key`)."""

    template_path: Path
    """Template file path RELATIVE to project_root."""

    envs: frozenset[str] = field(default_factory=lambda: frozenset({"prod"}))
    """Envs where this Middleware applies. Stage 1 (per ADR-035) is prod-only."""

    namespace: str = "kubelab"
    """Target K8s namespace. Traefik Middlewares are namespace-scoped."""


# ── Registry ──────────────────────────────────────────────────────────────────
# Single source of truth. Adding a new auth-protected service means a new row
# here PLUS a matching SECRET_CATALOG entry (toolkit/features/secrets_manager.py).

MIDDLEWARE_CATALOG: list[MiddlewareSpec] = [
    MiddlewareSpec(
        name="api-key-ollama",
        service="ollama",
        secret_key_path="apps.services.ai.ollama.api_key",
        template_path=Path("infra/k8s/overlays/prod/middlewares/api-key.yaml.tpl"),
    ),
]


# ── Public API ────────────────────────────────────────────────────────────────


def apply_middleware_secrets(
    env: str,
    project_root: Path,
    dry_run: bool = False,
) -> bool:
    """Render and apply every Middleware in MIDDLEWARE_CATALOG that targets `env`.

    Returns True iff every applicable Middleware was applied successfully (or all
    were out-of-scope for `env`, which is a successful no-op). False if any
    Middleware failed to render or apply — kubectl is NOT invoked for any
    Middleware whose precondition (SOPS value present, template readable) fails.
    """
    logger.section(f"Traefik Middleware secrets — {env.upper()}")

    applicable = [s for s in MIDDLEWARE_CATALOG if env in s.envs]
    if not applicable:
        logger.info(f"No middlewares registered for env={env} — nothing to do.")
        return True

    cm = ConfigurationManager(env, project_root)

    all_ok = True
    for spec in applicable:
        ok = _process_spec(spec, env, project_root, cm, dry_run)
        all_ok = all_ok and ok

    if all_ok:
        logger.success(f"Applied {len(applicable)} Middleware(s) for {env}")
    else:
        logger.error("One or more Middlewares failed — see errors above")
    return all_ok


# ── Internals ─────────────────────────────────────────────────────────────────


def _process_spec(
    spec: MiddlewareSpec,
    env: str,
    project_root: Path,
    cm: ConfigurationManager,
    dry_run: bool,
) -> bool:
    """Render + apply a single MiddlewareSpec. Returns True on success."""
    logger.info(f"Processing middleware: {spec.name} (service={spec.service})")

    api_key = cm.get_secret_by_path(spec.secret_key_path)
    if not api_key:
        logger.error(f"  Missing SOPS value at '{spec.secret_key_path}' — cannot render Middleware '{spec.name}'")
        return False

    template_full = project_root / spec.template_path
    if not template_full.is_file():
        logger.error(f"  Template not found at '{template_full}' — aborting")
        return False

    try:
        template_text = template_full.read_text()
    except OSError as exc:
        logger.error(f"  Failed to read template '{template_full}': {exc}")
        return False

    rendered = _render_middleware(spec, api_key, template_text)

    # Audit copy lives next to the template under `.rendered/` — explicitly
    # gitignored to keep plaintext keys out of git. We do NOT use the parallel
    # `generated/` directory because that one is committed (ARGO-007, reads
    # straight from Git via Argo CD).
    audit_path = project_root / "infra/k8s/overlays" / env / "middlewares/.rendered" / f"{spec.name}.yaml"
    try:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(rendered)
    except OSError as exc:
        logger.error(f"  Failed to write audit copy '{audit_path}': {exc}")
        return False

    if dry_run:
        logger.info(f"  [DRY-RUN] Rendered '{spec.name}' -> {audit_path} (cluster not touched)")
        return True

    return _kubectl_apply(env, spec.namespace, rendered, spec.name)


def _render_middleware(spec: MiddlewareSpec, api_key: str, template_text: str) -> str:
    """Substitute ${...} placeholders in the template. Pure function."""
    return (
        template_text.replace("${NAME}", spec.name)
        .replace("${NAMESPACE}", spec.namespace)
        .replace("${SERVICE}", spec.service)
        .replace("${API_KEY}", api_key)
    )


def _kubeconfig_for(env: str) -> str:
    import os

    return os.path.expanduser(f"~/.kube/kubelab-{env}-config")


def _kubectl_apply(env: str, namespace: str, rendered: str, spec_name: str) -> bool:
    """Server-side apply of the rendered Middleware + scrub legacy annotation.

    SEC-AI-002. Client-side `kubectl apply` persists the request body into the
    `kubectl.kubernetes.io/last-applied-configuration` annotation — for a
    Middleware whose body embeds a plaintext API key, that leaks the key into
    cluster state and any `kubectl get -o yaml` output. Server-side apply
    tracks managed fields via the API server instead, so the rendered body
    (with the key) is never echoed back into an annotation.

    `--force-conflicts` is required for the first apply when migrating a
    resource previously managed client-side: the legacy annotation still
    claims ownership of every field, so server-side rejects the apply as a
    conflict unless we explicitly take over. Subsequent applies stay clean.

    `--field-manager kubelab-toolkit` makes ownership traceable in
    `metadata.managedFields[*].manager` so other operators (Argo CD, hand
    edits) are distinguishable from this toolkit at audit time.
    """
    cmd = [
        "kubectl",
        "--kubeconfig",
        _kubeconfig_for(env),
        "-n",
        namespace,
        "apply",
        "--server-side",
        "--force-conflicts",
        "--field-manager",
        "kubelab-toolkit",
        "-f",
        "-",
    ]
    try:
        result = subprocess.run(
            cmd,
            input=rendered,
            capture_output=True,
            text=True,
            check=True,
        )
        logger.success(f"  {result.stdout.strip() or spec_name + ' applied'}")
        _scrub_legacy_annotation(env, namespace, spec_name)
        return True
    except subprocess.CalledProcessError as exc:
        logger.error(f"  kubectl apply failed for '{spec_name}': {exc.stderr.strip()}")
        return False


def _scrub_legacy_annotation(env: str, namespace: str, spec_name: str) -> None:
    """Strip `kubectl.kubernetes.io/last-applied-configuration` from a Middleware.

    Legacy from any pre-SEC-AI-002 client-side apply that embedded the
    plaintext API key into the annotation. Idempotent: `kubectl annotate
    name key-` succeeds with a warning when the annotation is absent.
    """
    cmd = [
        "kubectl",
        "--kubeconfig",
        _kubeconfig_for(env),
        "-n",
        namespace,
        "annotate",
        "middleware",
        spec_name,
        "kubectl.kubernetes.io/last-applied-configuration-",
        "--overwrite=true",
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        # Non-fatal — the apply already succeeded; scrub is a best-effort
        # cleanup. Surface the reason so a real failure (RBAC, missing
        # resource) is still visible.
        logger.warning(f"  legacy annotation scrub skipped for '{spec_name}': {exc.stderr.strip()}")
