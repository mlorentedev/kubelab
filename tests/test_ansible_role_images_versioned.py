"""Every image an Ansible role runs carries a version (#2716).

The `coredns` role ran Pi-hole as `pihole/pihole:latest` and pulls on every
deploy, so any `make deploy TARGET=dns` could move the LAN's resolver to an
image nobody chose, and the pull reports `changed=false`. The Beelink's stack
has its own check (`test_beelink_images_versioned.py`). This one covers what
every role declares in its defaults, and refuses an image written anywhere
else in a role.

An empty default is one the playbook fills from the config SSOT, which the
per-stack checks cover. A `:local` image is built on the node and never pulled.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from tests.image_versions import versioned

ROLES = Path(__file__).resolve().parents[1] / "infra/ansible/roles"
LOCAL_BUILD = ":local"


def _default_images() -> dict[str, str]:
    images = {}
    for defaults in sorted(ROLES.glob("*/defaults/main.yml")):
        for var, value in (yaml.safe_load(defaults.read_text(encoding="utf-8")) or {}).items():
            if var.endswith("_image") and value:
                images[f"{defaults.parts[-3]}.{var}"] = str(value)
    return images


def test_the_roles_declare_images() -> None:
    """The vacuity check: a renamed var would otherwise leave nothing to test."""
    assert "coredns.pihole_image" in _default_images()


@pytest.mark.parametrize(("var", "image"), sorted(_default_images().items()))
def test_every_role_default_image_carries_a_version(var: str, image: str) -> None:
    assert image.endswith(LOCAL_BUILD) or versioned(image), (
        f"{var} is {image!r}, a tag that rolls in place, so any deploy may upgrade it"
    )


# Every file of a role but its defaults, at any depth: templates, tasks, handlers,
# vars, files. An image key is `image:` or one ending in `_image:`, such as the
# `docker_image` module's.
IMAGE_KEY = re.compile(r"\s*(?:\w+_)?image:\s*(\S+)")


def _outside_defaults() -> list[Path]:
    return sorted(p for p in ROLES.rglob("*") if p.is_file() and p.relative_to(ROLES).parts[1] != "defaults")


def test_the_scan_reaches_nested_files_and_skips_the_defaults() -> None:
    scanned = [path.relative_to(ROLES).parts for path in _outside_defaults()]
    assert any(len(parts) > 3 for parts in scanned), "no nested file scanned"
    assert not any(parts[1] == "defaults" for parts in scanned)


def test_no_role_names_an_image_outside_a_var() -> None:
    """A literal image anywhere else would run without passing the check above."""
    literal = [
        f"{path.relative_to(ROLES)}:{number}"
        for path in _outside_defaults()
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1)
        if (m := IMAGE_KEY.match(line)) and "{{" not in m.group(1)
    ]
    assert not literal, f"images written outside a default: {literal}"
