"""#1847 (TOOL-083): the platform manifest publishes only what someone measured.

The web site renders `platform.json` on `/lab`. It carried a `metrics` block and a
`cluster.uptime` string that nobody had measured, per-service URLs and health
endpoints the site no longer renders, and the VPS in Falkenstein while the Hetzner
API reports it in Nuremberg. The site dropped those fields from its copy, so the
next sync would have brought them back.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from toolkit.features import platform_manifest

REPO = Path(__file__).resolve().parents[1]
VARIABLES_TF = REPO / "infra/terraform/compute/variables.tf"

# Hetzner location codes to the name the site shows. A new code fails the lookup
# below instead of publishing a guess.
HETZNER_LOCATIONS = {"nbg1": "Nuremberg (Germany)"}

# Fields that state a measurement or an endpoint nobody keeps checked.
UNMEASURED_FIELDS = {"metrics", "uptime", "url", "healthEndpoint", "isPublic"}


@pytest.fixture(scope="module")
def manifest() -> dict[str, object]:
    return platform_manifest.generate_manifest()


def _terraform_default_location() -> str:
    block = re.search(r'variable "server_location" \{(.*?)\n\}', VARIABLES_TF.read_text(encoding="utf-8"), re.S)
    assert block, f"no server_location variable in {VARIABLES_TF.relative_to(REPO)}"
    default = re.search(r'default\s*=\s*"([^"]+)"', block.group(1))
    assert default, "server_location has no default"
    return default.group(1)


def test_the_vps_location_is_the_one_terraform_creates_it_in(manifest: dict[str, object]) -> None:
    vps = next(n for n in manifest["nodes"] if n["id"] == "vps")  # type: ignore[index, union-attr]
    assert vps["location"] == HETZNER_LOCATIONS[_terraform_default_location()]


def _keys(node: object) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for v in node.values() for k in _keys(v)}
    if isinstance(node, list):
        return {k for v in node for k in _keys(v)}
    return set()


def test_no_unmeasured_field_is_published(manifest: dict[str, object]) -> None:
    assert not _keys(manifest) & UNMEASURED_FIELDS
