"""#2558: a failed API publish can be re-run, and says why it failed.

Every API release from 1.1.2 to 1.1.6 failed `publish-api` and left no image. The
step captured `toolkit deployment image-tag` with `$(...)`, and the toolkit logs to
stdout (#2536), so the reason went into the variable and the job log read only
`exit code 1`. The job was also gated on `release_created`, which only the run that
creates the GitHub release sees, so a missed release could never be published.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github/workflows/release.yml"


def _workflow() -> dict[str, Any]:
    # PyYAML reads the bare `on:` key as True.
    return yaml.safe_load(WORKFLOW.read_text())


def _job() -> dict[str, Any]:
    return _workflow()["jobs"]["publish-api"]


def _step(step_id: str) -> dict[str, Any]:
    return next(s for s in _job()["steps"] if s.get("id") == step_id)


def test_a_dispatch_can_republish_the_current_release() -> None:
    inputs = _workflow()[True]["workflow_dispatch"]["inputs"]
    # A flag, not a free-text version: a re-publish of an older version would move
    # `:latest` backwards, so the only version it can publish is the current release.
    assert inputs["republish_api"]["type"] == "boolean"
    condition = _job()["if"]
    assert "api_release_created == 'true'" in condition, "the normal release path is gone"
    assert "inputs.republish_api" in condition and "workflow_dispatch" in condition


def test_a_republish_takes_the_manifest_version_and_requires_its_release() -> None:
    script = _step("version")["run"]
    assert ".release-please-manifest.json" in script
    assert 'gh release view "api-v' in script, "a re-publish must refuse a version that was never released"
    assert _step("version")["env"]["GH_TOKEN"], "gh needs a token to read the release"


def test_the_publish_reads_the_resolved_version() -> None:
    assert "VERSION" not in _job().get("env", {}), "the version comes from the version step, not the job env"
    retag = next(s for s in _job()["steps"] if s.get("name", "").startswith("Re-tag"))
    assert retag["env"]["VERSION"] == "${{ steps.version.outputs.version }}"


def test_a_failed_tag_lookup_prints_its_reason() -> None:
    script = _step("sha")["run"]
    assert "if ! SHA=" in script, "a bare SHA=\"$(...)\" exits on failure with the reason inside the variable"
    assert "::error::" in script and "$SHA" in script.split("::error::", 1)[1].split("\n", 1)[0]


def test_only_masters_pin_can_become_a_semver_tag() -> None:
    """A dispatch can run on any ref, and the pin is read from the checked-out one (#2564 review)."""
    script = _step("version")["run"]
    guard = script.index('"$GITHUB_REF" != "refs/heads/master"')
    assert guard < script.index("gh release view"), "the ref check must run before anything is resolved"
    assert "exit 1" in script[guard : guard + 200], "a branch dispatch must fail, not skip"
