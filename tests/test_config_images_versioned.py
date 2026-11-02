"""Every image the config declares pins a version (#2753).

A Compose stack that names its image as `${VAR}` takes it from these files, so
the check on literal `image:` lines under `infra/stacks/` never sees it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.image_versions import versioned

VALUES = Path(__file__).resolve().parent.parent / "infra/config/values"


def _images(node: object, path: str = "") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            if str(key).endswith("image") and isinstance(value, str) and value:
                found.append((child, value))
            found.extend(_images(value, child))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_images(value, f"{path}[{index}]"))
    return found


def _declared() -> list[tuple[str, str, str]]:
    return [
        (values.name, key, image)
        for values in sorted(VALUES.glob("*.yaml"))
        for key, image in _images(yaml.safe_load(values.read_text(encoding="utf-8")))
    ]


def test_the_walk_finds_the_images() -> None:
    """A walk that matches nothing passes on any tree."""
    assert len(_declared()) > 20


@pytest.mark.parametrize(("values", "key", "image"), _declared())
def test_the_image_pins_a_version(values: str, key: str, image: str) -> None:
    assert versioned(image), f"{values}: {key} uses the rolling image {image}"
