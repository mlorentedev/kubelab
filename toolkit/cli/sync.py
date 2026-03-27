"""Sync generated files from SSOT (common.yaml, SOPS).

Wraps standalone sync scripts under a unified CLI with drift detection (ADR-027).

Usage:
    toolkit sync homepage              Sync Homepage config
    toolkit sync images                Sync K8s image tags
    toolkit sync oidc --env staging    Sync OIDC hashes
    toolkit sync all --env staging     Run all syncs
    toolkit sync all --check           Check for drift (CI mode)
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer

from toolkit.config.settings import settings
from toolkit.core.logging import logger

app = typer.Typer(
    name="sync",
    help="Sync generated files from SSOT (common.yaml, SOPS).",
    no_args_is_help=True,
)

# Dynamic patterns to normalize before comparison (ADR-027).
# These values change between runs regardless of SSOT changes.
HOMEPAGE_DYNAMIC_PATTERNS: list[tuple[str, str]] = [
    (r"synced \d{4}-\d{2}-\d{2} \u00b7 [a-f0-9]{7,}", "synced DATE HASH"),
    (r'"today": "\d{4}-\d{2}-\d{2}"', '"today": "DATE"'),
    (r'"traefik_cluster_ip": "\d+\.\d+\.\d+\.\d+"', '"traefik_cluster_ip": "IP"'),
    # SVGs are base64-encoded from external Kroki service — not SSOT-derived
    (r'"data:image/svg\+xml;base64,[A-Za-z0-9+/=]+"', '"data:image/svg+xml;base64,SVG_BASE64"'),
]


def _normalize_content(content: bytes, patterns: list[tuple[str, str]]) -> bytes:
    """Replace dynamic values with placeholders for deterministic comparison."""
    try:
        text = content.decode()
    except UnicodeDecodeError:
        logger.warning("File contains non-UTF-8 bytes, comparing raw bytes")
        return content
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)
    return text.encode()


def _restore_snapshots(snapshots: dict[Path, bytes | None]) -> None:
    """Restore files to their snapshotted state."""
    for path, content in snapshots.items():
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(content)


def _run_with_check(
    output_files: list[Path],
    sync_fn: Callable[[], int],
    label: str,
    dynamic_patterns: list[tuple[str, str]] | None = None,
    output_dir: Path | None = None,
) -> bool:
    """Run a sync function with drift detection.

    Snapshots current files, runs sync, compares (with normalization),
    then restores originals. Returns True if in sync, False if drift detected.

    If output_dir is set, also detects NEW files created by sync (not in original list).
    """
    snapshots: dict[Path, bytes | None] = {}
    for f in output_files:
        snapshots[f] = f.read_bytes() if f.exists() else None

    try:
        sync_fn()
    except Exception:
        logger.debug(f"{label}: sync function failed during --check; restoring snapshots")
        try:
            _restore_snapshots(snapshots)
        except Exception as restore_err:
            logger.error(f"Failed to restore snapshots after sync error: {restore_err}")
        raise

    # Detect new files created by sync (not in original snapshot)
    if output_dir and output_dir.is_dir():
        for f in output_dir.iterdir():
            if f.is_file() and f not in snapshots:
                snapshots[f] = None  # didn't exist before

    new_contents: dict[Path, bytes | None] = {}
    for f in snapshots:
        new_contents[f] = f.read_bytes() if f.exists() else None

    _restore_snapshots(snapshots)

    patterns = dynamic_patterns or []
    drifted: list[Path] = []
    for f in snapshots:
        old = snapshots[f]
        new = new_contents[f]
        if old is None and new is None:
            continue
        if old is None or new is None:
            drifted.append(f)
            continue
        old_normalized = _normalize_content(old, patterns)
        new_normalized = _normalize_content(new, patterns)
        if old_normalized != new_normalized:
            drifted.append(f)

    if drifted:
        logger.error(f"{label}: drift detected in {len(drifted)} file(s):")
        for f in sorted(drifted):
            try:
                display = f.relative_to(settings.project_root)
            except ValueError:
                display = f
            logger.error(f"  {display}")
        logger.info(f"Run 'toolkit sync {label}' to update, then commit.")
        return False

    logger.success(f"{label}: in sync")
    return True


def _sops_available() -> bool:
    """Check if SOPS is installed and can decrypt secrets."""
    if not shutil.which("sops"):
        logger.debug("sops binary not found in PATH")
        return False
    try:
        from toolkit.features.configuration import ConfigurationManager

        cm = ConfigurationManager("staging", settings.project_root)
        sops_file = cm.secrets_path / "staging.enc.yaml"
        if not sops_file.exists():
            logger.debug(f"SOPS file not found: {sops_file}")
            return False
        result = cm._decrypt_sops(sops_file)
        return bool(result)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        logger.debug(f"SOPS decryption failed: {e}")
        return False


def _get_homepage_output_dir() -> Path:
    """Homepage config output directory."""
    return settings.project_root / "infra/k8s/base/services/homepage-config"


def _get_homepage_output_files() -> list[Path]:
    """Collect all files in the homepage-config directory."""
    output_dir = _get_homepage_output_dir()
    if not output_dir.exists():
        return []
    return sorted(f for f in output_dir.iterdir() if f.is_file())


def _get_oidc_output_files() -> list[Path]:
    """Target files for OIDC hash sync."""
    return [
        settings.project_root / "infra/k8s/base/services/authelia.yaml",
        settings.project_root / "infra/k8s/overlays/prod/patches.yaml",
    ]


def _run_oidc_sync(env: str) -> int:
    """Invoke sync_oidc_hashes.main() with the correct sys.argv for argparse.

    NOTE: Not thread-safe. sync_oidc_hashes uses argparse which reads sys.argv.
    """
    original_argv = sys.argv
    sys.argv = ["sync_oidc_hashes", "--env", env]
    try:
        from toolkit.scripts import sync_oidc_hashes

        return sync_oidc_hashes.main()
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    finally:
        sys.argv = original_argv


@app.command()
def homepage(
    check: Annotated[bool, typer.Option("--check", help="Check for drift without modifying files")] = False,
) -> None:
    """Sync Homepage config from common.yaml + templates."""
    from toolkit.scripts import sync_homepage_config

    if check:
        output_files = _get_homepage_output_files()
        if not output_files:
            logger.warning("homepage: no output files found — directory missing?")
            return
        if not _run_with_check(
            output_files,
            sync_homepage_config.main,
            "homepage",
            HOMEPAGE_DYNAMIC_PATTERNS,
            output_dir=_get_homepage_output_dir(),
        ):
            raise typer.Exit(1)
    else:
        result = sync_homepage_config.main()
        if result != 0:
            raise typer.Exit(result)


@app.command()
def images(
    check: Annotated[bool, typer.Option("--check", help="Check for drift without modifying files")] = False,
) -> None:
    """Sync K8s image tags from common.yaml to kustomization.yaml."""
    from toolkit.scripts import sync_k8s_images

    if check:
        output_files = [settings.project_root / "infra/k8s/base/kustomization.yaml"]
        if not _run_with_check(output_files, sync_k8s_images.main, "images"):
            raise typer.Exit(1)
    else:
        result = sync_k8s_images.main()
        if result != 0:
            raise typer.Exit(result)


@app.command()
def oidc(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")],
    check: Annotated[bool, typer.Option("--check", help="Check for drift without modifying files")] = False,
) -> None:
    """Sync OIDC client_secret hashes from SOPS to K8s manifests."""
    if check:
        if not _sops_available():
            logger.warning("oidc: SOPS unavailable — skipping drift check")
            return
        output_files = _get_oidc_output_files()
        if not _run_with_check(output_files, lambda: _run_oidc_sync(env), "oidc"):
            raise typer.Exit(1)
    else:
        result = _run_oidc_sync(env)
        if result != 0:
            raise typer.Exit(result)


@app.command("all")
def sync_all(
    env: Annotated[str, typer.Option("--env", "-e", help="Environment for OIDC sync")] = "staging",
    check: Annotated[bool, typer.Option("--check", help="Check for drift without modifying files")] = False,
) -> None:
    """Run all sync operations (homepage + images + oidc)."""
    failures: list[str] = []

    logger.section("Sync All" + (" — check mode" if check else ""))

    # 1. Homepage
    try:
        from toolkit.scripts import sync_homepage_config

        if check:
            output_files = _get_homepage_output_files()
            if not output_files:
                logger.warning("homepage: no output files found — directory missing?")
            elif not _run_with_check(
                output_files,
                sync_homepage_config.main,
                "homepage",
                HOMEPAGE_DYNAMIC_PATTERNS,
                output_dir=_get_homepage_output_dir(),
            ):
                failures.append("homepage")
        else:
            if sync_homepage_config.main() != 0:
                failures.append("homepage")
    except Exception as e:
        logger.error(f"homepage sync crashed: {e}")
        failures.append("homepage")

    # 2. Images
    try:
        from toolkit.scripts import sync_k8s_images

        if check:
            output_files = [settings.project_root / "infra/k8s/base/kustomization.yaml"]
            if not _run_with_check(output_files, sync_k8s_images.main, "images"):
                failures.append("images")
        else:
            if sync_k8s_images.main() != 0:
                failures.append("images")
    except Exception as e:
        logger.error(f"images sync crashed: {e}")
        failures.append("images")

    # 3. OIDC (SOPS-dependent)
    try:
        if check:
            if not _sops_available():
                logger.warning("oidc: SOPS unavailable — skipping drift check")
            else:
                output_files = _get_oidc_output_files()
                if not _run_with_check(output_files, lambda: _run_oidc_sync(env), "oidc"):
                    failures.append("oidc")
        else:
            result = _run_oidc_sync(env)
            if result != 0:
                failures.append("oidc")
    except Exception as e:
        logger.error(f"oidc sync crashed: {e}")
        failures.append("oidc")

    if failures:
        logger.error(f"Sync failures: {', '.join(failures)}")
        raise typer.Exit(1)

    if check:
        logger.success("All generated files in sync")
