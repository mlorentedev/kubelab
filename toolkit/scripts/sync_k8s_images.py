"""Sync K8s kustomization.yaml images from common.yaml SSOT.

Reads image versions from common.yaml and updates the `images:` section
in infra/k8s/base/kustomization.yaml. Preserves file formatting by only
replacing the images block (regex-based, not full yaml.dump).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

from toolkit.core.io import write_text_lf

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMMON_YAML = PROJECT_ROOT / "infra/config/values/common.yaml"
KUSTOMIZATION = PROJECT_ROOT / "infra/k8s/base/kustomization.yaml"
# A manifest declared ONLY in the prod overlay (never base) needs its `images:`
# override in THAT kustomization -- a transformer applies only to the resource
# set assembled at its own layer, so base's own `images:` block never reaches
# something `overlays/prod/*.yaml` adds directly (TOOL-080).
PROD_KUSTOMIZATION = PROJECT_ROOT / "infra/k8s/overlays/prod/kustomization.yaml"

# Dotted paths into common.yaml that hold "name:tag" image strings.
# Only third-party services -- custom apps are per-environment (overlays).
IMAGE_SOURCES = [
    # gitea deliberately absent: it left K3s for the Beelink (ADR-061), so its
    # image is no longer a Kustomize concern. The pin lives where the workload
    # does — `roles/beelink_services` reads apps.services.core.gitea.image
    # straight from this same SSOT, so the value is still single-sourced.
    "apps.services.automation.n8n.image",
    "apps.services.automation.apprise.image",
    "apps.services.observability.grafana.image",
    "apps.services.observability.loki.image",
    "apps.services.observability.loki.vector_image",
    "apps.services.observability.homepage.image",
    "apps.services.security.authelia.image",
    "apps.services.security.authelia.redis_image",
    "apps.services.security.crowdsec.image",
    "infra.postgres.image",
    # BACKUP-055: the R2 watcher; its tag is tied to backup.r2.restic_version.
    "backup.watcher.image",
]

# Third-party images whose manifest lives ONLY in the prod overlay (TOOL-080's
# pr-agent.yaml). Kept as a separate list rather than folded into IMAGE_SOURCES
# above: those all target KUSTOMIZATION (base), and mixing the two would put a
# prod-only image's override where nothing it matches is ever assembled.
PROD_IMAGE_SOURCES = [
    "apps.services.automation.pr_agent.image",
]

# Marker comments kept above the images block.
IMAGES_HEADER = (
    "# Image tags synced from infra/config/values/common.yaml (SSOT).\n"
    "# Run `make sync-k8s-images` to refresh after bumping versions.\n"
)


def resolve_path(data: dict[str, object], path: str) -> str | None:
    """Resolve dotted path in nested dict."""
    current: object = data
    for key in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(key, {})
    return str(current) if isinstance(current, str) else None


def parse_image(image_str: str) -> tuple[str, str]:
    """Split 'name:tag' into (name, tag). Handles registry prefixes like quay.io/..."""
    last_colon = image_str.rfind(":")
    if last_colon == -1:
        return image_str, ""
    return image_str[:last_colon], image_str[last_colon + 1 :]


def resolve_errors_image(config: dict[str, object]) -> tuple[str, str] | None:
    """Build the `errors` image (name, tag) from the structured `edge.errors` SSOT.

    Unlike third-party images (single `name:tag` strings), `errors` is pinned by
    separate keys — `registry` + `edge.errors.image_name` + `edge.errors.version`
    — the same string Ansible renders for the VPS. This is the one custom app on
    the sync lane: a semver shared across envs (DELIVERY-003), not a per-env tag.
    Returns ``None`` if any key is missing.
    """
    edge = config.get("edge")
    registry = config.get("registry")
    if not isinstance(edge, dict) or not isinstance(registry, str):
        return None
    errors = edge.get("errors")
    if not isinstance(errors, dict):
        return None
    image_name = errors.get("image_name")
    version = errors.get("version")
    if not isinstance(image_name, str) or not version:
        return None
    return f"{registry}/{image_name}", str(version)


def collect_images(
    config: dict[str, object], sources: list[str] = IMAGE_SOURCES, include_errors: bool = True
) -> list[tuple[str, str]]:
    """Resolve every synced image (third-party +, by default, the `errors` custom app).

    `sources`/`include_errors` let a caller target a different kustomization —
    PROD_IMAGE_SOURCES has no `errors` counterpart of its own, so the base sync
    (the default call) is the only one that should ever include it.
    """
    images: list[tuple[str, str]] = []
    for path in sources:
        image_str = resolve_path(config, path)
        if not image_str or ":" not in image_str:
            continue
        name, tag = parse_image(image_str)
        if tag and tag != "latest":
            images.append((name, tag))
    if include_errors:
        errors_image = resolve_errors_image(config)
        if errors_image:
            images.append(errors_image)
    return images


def build_images_block(images: list[tuple[str, str]]) -> str:
    """Build the YAML text for the images: section."""
    lines = [IMAGES_HEADER, "images:\n"]
    for name, tag in images:
        lines.append(f"  - name: {name}\n")
        lines.append(f"    newTag: {tag}\n")
    return "".join(lines)


def sync(
    common_yaml: Path = COMMON_YAML,
    kustomization: Path = KUSTOMIZATION,
    sources: list[str] = IMAGE_SOURCES,
    include_errors: bool = True,
) -> int:
    """Rewrite the ``images:`` block in ``kustomization`` from ``common_yaml``.

    Paths are injectable so callers (e.g. ``deployment promote --app errors``) can
    re-sync a working tree other than the module default, and so `main()` can
    target the prod overlay's own kustomization with its own source list.
    Returns 0 on success.
    """
    with open(common_yaml, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    content = kustomization.read_text(encoding="utf-8")

    images = collect_images(config, sources=sources, include_errors=include_errors)

    if not images:
        print("WARNING: No images resolved from common.yaml", file=sys.stderr)
        return 1

    new_block = build_images_block(images)

    # Replace existing images block: header comments + images key + entries.
    # Match any run of comment lines immediately before `images:`, then the entries.
    pattern_with_comments = r"(?m)(?:^#[^\n]*\n)*^images:\n(?:(?:  - |\s{4}).*\n)*"
    pattern_bare = r"(?m)^images:\n(?:(?:  - |\s{4}).*\n)*"

    if re.search(pattern_with_comments, content):
        content = re.sub(pattern_with_comments, new_block, content)
    elif re.search(pattern_bare, content):
        content = re.sub(pattern_bare, new_block, content)
    else:
        # No images section yet -- append
        content = content.rstrip("\n") + "\n\n" + new_block

    write_text_lf(kustomization, content)
    print(f"Synced {len(images)} image tags from common.yaml -> kustomization.yaml")
    return 0


def main() -> int:
    """CLI entrypoint — sync base, then the prod overlay's own prod-only images.

    Paths/sources are passed explicitly (not left to `sync`'s own defaults):
    a default parameter value binds once at import time, so a test that
    monkeypatches the module-level constants would silently miss it if `main`
    relied on `sync()`'s defaults instead of re-reading the globals here.
    """
    base_rc = sync(common_yaml=COMMON_YAML, kustomization=KUSTOMIZATION)
    prod_rc = sync(
        common_yaml=COMMON_YAML,
        kustomization=PROD_KUSTOMIZATION,
        sources=PROD_IMAGE_SOURCES,
        include_errors=False,
    )
    return base_rc or prod_rc


if __name__ == "__main__":
    sys.exit(main())
