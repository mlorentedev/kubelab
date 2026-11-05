"""The Renovate engine version has one home: `ci.renovate.image` in common.yaml.

IDP-036 runs Renovate on two forges: the GitHub workflow here, and a timer on
the Beelink node for Gitea. Two literals would drift, and a drift between
engines reads as a difference between forges, not a version skew. So the
workflow carries no literal `renovate-version`: a step reads the tag from the
key, and the `common.yaml` image manager in renovate.json bumps that key like
every other pinned image.
"""

from __future__ import annotations

import json
import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github/workflows/renovate.yml"
COMMON = REPO / "infra/config/values/common.yaml"
RENOVATE = REPO / "renovate.json"
ENGINE = "ghcr.io/renovatebot/renovate"
STEP_OUTPUT = re.compile(r"^\$\{\{\s*steps\.(?P<id>[A-Za-z0-9_-]+)\.outputs\.[A-Za-z0-9_-]+\s*\}\}$")


def _steps() -> list[dict]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["renovate"]["steps"]


def _action_step() -> dict:
    (step,) = [s for s in _steps() if str(s.get("uses", "")).startswith("renovatebot/github-action@")]
    return step


def _engine_image() -> str:
    common = yaml.safe_load(COMMON.read_text(encoding="utf-8"))
    return common["ci"]["renovate"]["image"]


def test_engine_image_is_declared_in_common() -> None:
    name, _, tag = _engine_image().rpartition(":")
    assert name == ENGINE
    assert re.fullmatch(r"\d+\.\d+\.\d+", tag), tag


def test_workflow_carries_no_literal_engine_version() -> None:
    inputs = _action_step()["with"]
    for key in ("renovate-version", "renovate-image"):
        assert STEP_OUTPUT.match(str(inputs[key])), f"{key} is a literal: {inputs[key]!r}"


def test_the_step_feeding_the_action_reads_the_common_key() -> None:
    inputs = _action_step()["with"]
    ids = {STEP_OUTPUT.match(str(inputs[k])).group("id") for k in ("renovate-version", "renovate-image")}
    assert len(ids) == 1
    (source,) = [s for s in _steps() if s.get("id") in ids]
    script = source["run"]
    assert ".ci.renovate.image" in script
    assert "infra/config/values/common.yaml" in script


def test_renovate_bumps_the_engine_key() -> None:
    """The key is only a home if a manager reads it; a regex that misses is silent."""
    config = json.loads(RENOVATE.read_text(encoding="utf-8"))
    text = COMMON.read_text(encoding="utf-8")
    found = set()
    for manager in config["customManagers"]:
        if not any("common" in p for p in manager["managerFilePatterns"]):
            continue
        for pattern in manager["matchStrings"]:
            for m in re.finditer(pattern.replace("(?<", "(?P<"), text):
                groups = m.groupdict()
                if groups.get("depName") == ENGINE:
                    found.add(groups["currentValue"])
    assert found == {_engine_image().rpartition(":")[2]}
