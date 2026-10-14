"""#2033 (ANSIBLE-062): every image the Beelink's Compose stack runs carries a version.

`github-runner` was `myoung34/github-runner:ubuntu-noble`, a tag that rolls in
place. A provision run only to change act_runner's cache dir pulled a new runner
image nobody chose and recreated the container. The role was idempotent; the tag
was not, so an unrelated change silently upgraded CI.

The images are read the way `provision-bee.yml` reads them: each `*_image` var the
playbook passes to the role names a path in the config SSOT, resolved with every
environment's overrides merged over `common.yaml`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
PLAYBOOK = REPO / "infra/ansible/playbooks/provision-bee.yml"
VALUES = REPO / "infra/config/values"
# `config` and `gitea_config` are both `common | combine(<env>.yaml)` in the playbook.
IMAGE_VAR = re.compile(r"^\{\{\s*(?:config|gitea_config)\.([\w.]+)\s*\}\}$")


def _image_vars() -> dict[str, str]:
    """Every `<name>_image` var the playbook sets, as `name -> SSOT path`."""
    found: dict[str, str] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(key, str) and key.endswith("_image") and isinstance(value, str):
                    match = IMAGE_VAR.match(value.strip())
                    assert match, f"{key} is not read from the SSOT: {value!r}"
                    found[key] = match.group(1)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8")))
    return found


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _resolve(config: dict[str, Any], path: str) -> str:
    node: Any = config
    for key in path.split("."):
        node = node[key]
    return node


def _versioned(image: str) -> bool:
    """A digest, or a tag that carries a version number and is not `latest`."""
    if "@sha256:" in image:
        return True
    name = image.split("/")[-1]
    tag = name.split(":", 1)[1] if ":" in name else ""
    return tag not in ("", "latest") and any(ch.isdigit() for ch in tag)


ENVS = sorted(p.stem for p in VALUES.glob("*.yaml") if p.stem != "common")


def test_the_playbook_passes_the_runner_image() -> None:
    """The vacuity check: a playbook rename would otherwise leave nothing to test."""
    names = _image_vars()
    assert "runner_image" in names and len(names) >= 3, names


@pytest.mark.parametrize("env", ENVS)
def test_every_beelink_image_carries_a_version(env: str) -> None:
    common = yaml.safe_load((VALUES / "common.yaml").read_text(encoding="utf-8"))
    overrides = yaml.safe_load((VALUES / f"{env}.yaml").read_text(encoding="utf-8")) or {}
    config = _merge(common, overrides)
    rolling = {var: image for var, path in _image_vars().items() if not _versioned(image := _resolve(config, path))}
    assert not rolling, f"{env}: these images roll in place, so any provision may upgrade them: {rolling}"


@pytest.mark.parametrize(
    ("image", "expected"),
    [
        ("myoung34/github-runner:ubuntu-noble", False),
        ("myoung34/github-runner:latest", False),
        ("myoung34/github-runner", False),
        ("registry.example:5000/runner", False),
        ("myoung34/github-runner:2.338.0-ubuntu-noble", True),
        ("gitea/gitea@sha256:" + "0" * 64, True),
    ],
)
def test_the_version_check(image: str, expected: bool) -> None:
    assert _versioned(image) is expected
