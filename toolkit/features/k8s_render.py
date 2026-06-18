"""Render-and-apply primitive for the cluster-wide bootstrap layer (ADR-047 / TOOL-009).

Cluster-scoped foundations (CRDs, controllers, kube-system config) are applied
OUTSIDE the Argo CD overlay: the spoke RBAC is least-privilege and structurally
cannot create them (ADR-041). Some carry ``RESOLVE_*`` placeholders for Tailscale
IPs that rotate on node re-registration (ADR-025); those are resolved at deploy
time via MagicDNS.

Before this module that logic was inline ``dig | sed | kubectl`` shell duplicated
across three Makefile sites (coredns/rpi4, uptime-kuma/rpi3, argocd/aws1). Centralising
it here makes it testable once and gives every cluster-wide apply the same
dry-run-first, server-side, traceable-field-manager behavior as the rest of the
toolkit (cf. ``k8s_middlewares``).
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from toolkit.core.logging import logger

# Field manager string so this toolkit's ownership is distinguishable from Argo CD
# or hand edits in ``metadata.managedFields[*].manager`` at audit time.
FIELD_MANAGER = "kubelab-toolkit"

# Deploy-time placeholders carry this prefix (e.g. RESOLVE_RPI4_TAILSCALE_IP).
_PLACEHOLDER_RE = re.compile(r"RESOLVE_[A-Z0-9_]+")

Resolver = Callable[[str], "str | None"]
Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class RenderError(Exception):
    """A ``RESOLVE_*`` placeholder is unmapped, or its MagicDNS target did not resolve."""


@dataclass(frozen=True)
class BootstrapEntry:
    """One ``cluster_bootstrap`` SSOT entry (ADR-047 D2).

    ``version`` is set only for vendored *operators* (drives ``make sync-operators``).
    ``render`` maps each ``RESOLVE_*`` placeholder to a MagicDNS hostname resolved at
    deploy time. ``optional`` lets an entry be skipped (not failed) when a render
    target is unreachable — e.g. RPi4 is an on-demand node and may be powered off.
    """

    name: str
    namespace: str
    manifest: str
    version: str | None = None
    optional: bool = False
    render: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> BootstrapEntry:
        """Build an entry from a parsed ``cluster_bootstrap`` list item."""
        return cls(
            name=str(raw["name"]),
            namespace=str(raw["namespace"]),
            manifest=str(raw["manifest"]),
            version=(str(raw["version"]) if raw.get("version") is not None else None),
            optional=bool(raw.get("optional", False)),
            render={str(k): str(v) for k, v in dict(raw.get("render") or {}).items()},
        )


def resolve_magicdns(hostname: str) -> str | None:
    """Resolve a MagicDNS hostname to an IP via ``dig +short``.

    Mirrors the prior Makefile behavior exactly (same system resolver MagicDNS feeds),
    so node re-registration IP churn is absorbed at deploy time. Returns the first
    answer line, or ``None`` if ``dig`` is missing / fails / returns nothing.
    """
    try:
        result = subprocess.run(
            ["dig", "+short", hostname],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        logger.error("dig not found on PATH — cannot resolve MagicDNS names")
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def render_text(
    text: str,
    render_map: dict[str, str],
    *,
    resolver: Resolver = resolve_magicdns,
) -> str:
    """Substitute every ``RESOLVE_*`` placeholder in ``text`` with its resolved IP.

    Fail-closed by design: raises :class:`RenderError` if the manifest contains a
    ``RESOLVE_*`` placeholder with no mapping (typo / config drift) **or** if a mapped
    hostname does not resolve. A half-substituted manifest is never returned — applying
    one would push a broken CoreDNS forward zone (or similar) to the cluster.
    """
    present = set(_PLACEHOLDER_RE.findall(text))
    unmapped = present - set(render_map)
    if unmapped:
        raise RenderError(f"unmapped RESOLVE_* placeholder(s) in manifest: {sorted(unmapped)}")
    for placeholder, hostname in render_map.items():
        if placeholder not in text:
            continue
        ip = resolver(hostname)
        if not ip:
            raise RenderError(f"{hostname} did not resolve via MagicDNS (for {placeholder})")
        text = text.replace(placeholder, ip)
    return text


def render_and_apply(
    entry: BootstrapEntry,
    *,
    kubeconfig: str,
    project_root: Path,
    dry_run: bool = False,
    resolver: Resolver = resolve_magicdns,
    runner: Runner = subprocess.run,
) -> bool:
    """Render an entry's ``RESOLVE_*`` placeholders, then server-side apply it.

    Steps: read the vendored manifest at ``project_root / entry.manifest`` → resolve
    placeholders via MagicDNS → client-side validate → server-side apply (unless ``dry_run``).

    For an ``optional`` entry a render/resolve failure is a logged SKIP returning
    ``True`` (mirrors the on-demand-node semantics the Makefile had for coredns/RPi4);
    for a required entry it is a hard failure. Returns ``True`` on apply / successful
    skip, ``False`` on a hard failure (missing manifest, required render failure, or
    kubectl error).
    """
    manifest_path = project_root / entry.manifest
    if not manifest_path.exists():
        logger.error(f"[{entry.name}] manifest not found: {manifest_path}")
        return False

    text = manifest_path.read_text()
    if entry.render:
        try:
            text = render_text(text, entry.render, resolver=resolver)
        except RenderError as exc:
            if entry.optional:
                logger.warning(f"[{entry.name}] skipped (optional): {exc}")
                return True
            logger.error(f"[{entry.name}] render failed: {exc}")
            return False

    # Always client-validate first; only apply if validation passes.
    if not _kubectl_apply(text, kubeconfig, entry.name, dry_run=True, runner=runner):
        return False
    if dry_run:
        logger.success(f"[{entry.name}] dry-run OK")
        return True
    return _kubectl_apply(text, kubeconfig, entry.name, dry_run=False, runner=runner)


def _kubectl_apply(
    text: str,
    kubeconfig: str,
    name: str,
    *,
    dry_run: bool,
    runner: Runner,
) -> bool:
    """Server-side ``kubectl apply -f -`` of rendered YAML (stdin).

    ``--server-side --force-conflicts --field-manager kubelab-toolkit`` matches the
    established toolkit convention (see ``k8s_middlewares``): server-side apply tracks
    ownership via managedFields, ``--force-conflicts`` cleanly migrates a resource
    previously managed client-side (e.g. coredns-custom applied by the old Makefile
    path), and a named field manager keeps ownership traceable.

    Namespace is NOT passed on the CLI — the manifest's ``metadata.namespace`` is
    authoritative (operator manifests span cluster-scoped + multiple namespaces).
    """
    cmd = ["kubectl", "--kubeconfig", kubeconfig, "apply"]
    if dry_run:
        # Client-side validation only. A `--dry-run=server` of a manifest that creates
        # its own namespace AND namespaced resources fails with "namespace not found"
        # (server dry-run never actually creates the ns). Client validation has no such
        # dependency, so it validates self-namespacing operator manifests cleanly.
        cmd += ["--dry-run=client", "-f", "-"]
    else:
        cmd += ["--server-side", "--force-conflicts", "--field-manager", FIELD_MANAGER, "-f", "-"]
    result = runner(cmd, input=text, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        stage = "dry-run" if dry_run else "apply"
        logger.error(f"[{name}] kubectl {stage} failed: {(result.stderr or '').strip()}")
        return False
    if not dry_run:
        logger.success(f"[{name}] {(result.stdout or '').strip() or 'applied'}")
    return True
