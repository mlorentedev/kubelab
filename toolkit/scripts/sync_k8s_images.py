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
    "apps.services.core.n8n.image",
    "apps.services.observability.loki.image",
    "apps.services.observability.loki.vector_image",
    "apps.services.security.authelia.image",
    "apps.services.security.authelia.redis_image",
    "apps.services.security.crowdsec.image",
    "apps.services.data.minio.image",
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


def build_images_block(images: list[tuple[str, str]]) -> str:
    """Build the YAML text for the images: section."""
    lines = [IMAGES_HEADER, "images:\n"]
    for name, tag in images:
        lines.append(f"  - name: {name}\n")
        lines.append(f"    newTag: {tag}\n")
    return "".join(lines)


def main() -> int:
    with open(COMMON_YAML) as f:
        config = yaml.safe_load(f)

    content = KUSTOMIZATION.read_text()

    images: list[tuple[str, str]] = []
    for path in IMAGE_SOURCES:
        image_str = resolve_path(config, path)
        if not image_str or ":" not in image_str:
            continue
        name, tag = parse_image(image_str)
        if tag and tag != "latest":
            images.append((name, tag))

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

    KUSTOMIZATION.write_text(content)
    print(f"Synced {len(images)} image tags from common.yaml -> kustomization.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
