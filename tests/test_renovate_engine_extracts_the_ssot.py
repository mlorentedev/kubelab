"""Renovate's own engine extracts every dependency the SSOT declares (#3440).

`test_renovate_image_coverage.py` checks Python copies of the regex managers, and
a copy can match where Renovate does not: a pattern ending in `$` passed there
while Renovate extracted nothing and reported success (lesson-691). This runs the
pinned engine with `--platform=local --dry-run=extract` and compares its report
with the dependencies read straight from the YAML, with no regex involved. A
manager that stops matching, or a file pattern that stops selecting its file,
shows up here as a missing dependency.

Extraction only: whether a datasource resolves is a lookup, which needs network
and a token, and is not asserted here (without a token the GitHub-sourced deps
come back with `skipReason: github-token-required`, by design). Only what is
declared is asserted. A dependency the engine finds beyond these is not a
failure here.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from toolkit.features import renovate_dry_run as dry

REPO = Path(__file__).resolve().parents[1]
COMMON = "infra/config/values/common.yaml"
PRE_COMMIT = ".pre-commit-config.yaml"
GALAXY = "infra/ansible/requirements.yml"


def _load(path: str) -> object:
    return yaml.safe_load((REPO / path).read_text(encoding="utf-8"))


def _images(node: object) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key.endswith("image") and isinstance(value, str):
                found.append(value)
            found += _images(value)
    elif isinstance(node, list):
        for item in node:
            found += _images(item)
    return found


def _declared() -> dict[tuple[str, str, str, str], str]:
    """Each declared dependency, mapped to where it is declared."""
    common = _load(COMMON)
    assert isinstance(common, dict)
    ignored = set(json.loads((REPO / "renovate.json").read_text(encoding="utf-8")).get("ignoreDeps", []))
    want: dict[tuple[str, str, str, str], str] = {}
    for image in _images(common):
        if ":" not in image.rsplit("/", 1)[-1]:
            continue  # test_every_declared_image_carries_a_tag reports it
        name, tag = image.rsplit(":", 1)
        if name not in ignored:
            want[("regex", COMMON, name, tag)] = "an image in common.yaml"
    for operator in common.get("cluster_bootstrap", []):
        repo = (operator.get("source") or {}).get("repo")
        if repo:
            want[("regex", COMMON, repo, operator["version"])] = f"cluster_bootstrap operator {operator['name']}"
    want[("regex", COMMON, "mlorentedev/ci-workflows", common["ci"]["renovate"]["preset_tag"])] = (
        "ci.renovate.preset_tag"
    )
    pre_commit = _load(PRE_COMMIT)
    assert isinstance(pre_commit, dict)
    want[("regex", PRE_COMMIT, "node", pre_commit["default_language_version"]["node"])] = "pre-commit's node"
    galaxy = _load(GALAXY)
    assert isinstance(galaxy, dict)
    for collection in galaxy["collections"]:
        want[("ansible-galaxy", GALAXY, collection["name"], collection["version"])] = "an Ansible collection"
    return want


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


@pytest.fixture(scope="module")
def engine_report() -> Iterator[Path]:
    if not _docker_ready():
        if os.environ.get("CI"):
            pytest.fail("docker is required in CI to run the Renovate engine")
        pytest.skip("docker not available: cannot run the Renovate engine (a skip is CANNOT CHECK, not OK)")
    image = dry.engine_image(REPO / COMMON)
    # Under $HOME, not tmp_path: Colima and Docker Desktop share only $HOME with their VM.
    base = Path.home() / ".cache" / "kubelab-tests"
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base) as out:
        try:
            yield dry.run_extract(REPO, Path(out), image)
        except subprocess.TimeoutExpired as e:
            pytest.fail(f"the Renovate engine did not finish: {e}")


def test_every_declared_image_carries_a_tag() -> None:
    """An untagged image would drop out of the derivation below, and out of Renovate."""
    common = _load(COMMON)
    untagged = [image for image in _images(common) if ":" not in image.rsplit("/", 1)[-1]]
    assert not untagged, f"images in {COMMON} with no tag, which nothing pins or updates: {untagged}"


def test_the_declared_set_is_not_empty() -> None:
    """The vacuity check for the derivation itself: an empty want proves nothing."""
    managers = {key[0] for key in _declared()}
    assert managers == {"regex", "ansible-galaxy"}
    assert len(_declared()) > 20


def test_the_engine_extracts_every_declared_dependency(engine_report: Path) -> None:
    got = dry.extracted(engine_report)
    missing = sorted(
        f"{where}: {dep} {value} ({manager}, {path})"
        for (manager, path, dep, value), where in _declared().items()
        if (manager, path, dep, value) not in got
    )
    assert not missing, (
        "Renovate's engine did not extract these declared dependencies, so nothing would ever "
        "update them, and the run would still report success:\n" + "\n".join(missing)
    )
