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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMMON_YAML = PROJECT_ROOT / "infra/config/values/common.yaml"
KUSTOMIZATION = PROJECT_ROOT / "infra/k8s/base/kustomization.yaml"

# Dotted paths into common.yaml that hold "name:tag" image strings.
# Only third-party services -- custom apps are per-environment (overlays).
IMAGE_SOURCES = [
    "apps.services.core.gitea.image",
    "apps.services.automation.n8n.image",
    "apps.services.automation.apprise.image",
    "apps.services.observability.loki.image",
    "apps.services.observability.loki.vector_image",
    "apps.services.security.authelia.image",
    "apps.services.security.authelia.redis_image",
    "apps.services.security.crowdsec.image",
    "apps.services.data.minio.image",
    "infra.postgres.image",
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


def collect_images(config: dict[str, object]) -> list[tuple[str, str]]:
    """Resolve every synced image (third-party + the `errors` custom app)."""
    images: list[tuple[str, str]] = []
    for path in IMAGE_SOURCES:
        image_str = resolve_path(config, path)
        if not image_str or ":" not in image_str:
            continue
        name, tag = parse_image(image_str)
        if tag and tag != "latest":
            images.append((name, tag))
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


def sync(common_yaml: Path = COMMON_YAML, kustomization: Path = KUSTOMIZATION) -> int:
    """Rewrite the ``images:`` block in ``kustomization`` from ``common_yaml``.

    Paths are injectable so callers (e.g. ``deployment promote --app errors``) can
    re-sync a working tree other than the module default. Returns 0 on success.
    """
    with open(common_yaml) as f:
        config = yaml.safe_load(f)

    content = kustomization.read_text()

    images = collect_images(config)

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

    kustomization.write_text(content)
    print(f"Synced {len(images)} image tags from common.yaml -> kustomization.yaml")
    return 0


def main() -> int:
    """CLI entrypoint — sync the repo's default common.yaml -> kustomization.yaml."""
    return sync()


if __name__ == "__main__":
    sys.exit(main())
