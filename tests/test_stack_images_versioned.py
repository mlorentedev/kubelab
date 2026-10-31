"""Every image a Compose stack names carries a version (#2726).

The dev stack ran Pi-hole as `pihole/pihole:latest` while the `coredns` role
pinned the edge's (#2724), so a developer's next pull could move dev to a
version the LAN's resolver never ran. The role check reads only Ansible roles;
this one reads every `image:` under `infra/stacks/`.

A `${VAR}` image comes from the config SSOT and is judged where it is declared,
not here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from tests.image_versions import versioned

REPO = Path(__file__).resolve().parents[1]
STACKS = REPO / "infra/stacks"
PIHOLE_STACK = STACKS / "services/core/pihole/compose.yml"
COREDNS_DEFAULTS = REPO / "infra/ansible/roles/coredns/defaults/main.yml"
IMAGE = re.compile(r"\s*image:\s*[\"']?([^\s\"']+)")


def _literal_images() -> dict[str, str]:
    images = {}
    for path in sorted(STACKS.rglob("*.y*ml")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if (m := IMAGE.match(line)) and "${" not in m.group(1):
                images[f"{path.relative_to(REPO)}:{number}"] = m.group(1)
    return images


def test_the_scan_reaches_the_pihole_stack() -> None:
    """The vacuity check: a moved file would otherwise leave nothing to test."""
    assert any(where.startswith(str(PIHOLE_STACK.relative_to(REPO))) for where in _literal_images())


@pytest.mark.parametrize(("where", "image"), sorted(_literal_images().items()))
def test_every_literal_stack_image_carries_a_version(where: str, image: str) -> None:
    assert versioned(image), f"{where} runs {image!r}, a tag that rolls in place, so any pull may upgrade it"


def test_the_dev_pihole_runs_the_image_the_edge_runs() -> None:
    """Two copies of one value: the role's default is the one a deploy reads."""
    role = yaml.safe_load(COREDNS_DEFAULTS.read_text(encoding="utf-8"))["pihole_image"]
    stack = yaml.safe_load(PIHOLE_STACK.read_text(encoding="utf-8"))["services"]["pihole"]["image"]
    assert stack == role, f"the dev stack runs {stack!r}, the edge {role!r}"
