"""#2558: a failed API publish can be re-run, and says why it failed.

Every API release from 1.1.2 to 1.1.6 failed `publish-api` and left no image. The
step captured `toolkit deployment image-tag` with `$(...)`, and the toolkit logs to
stdout (#2536), so the reason went into the variable and the job log read only
`exit code 1`. The job was also gated on `release_created`, which only the run that
creates the GitHub release sees, so a missed release could never be published.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github/workflows/release.yml"


def _workflow() -> dict[str, Any]:
    # PyYAML reads the bare `on:` key as True.
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


# The two apps that re-tag a staging digest (ADR-056). Every guard below holds for both, so
# a lane added for console cannot be missing the ones #2558 and #2564 added for api.
APPS = ("api", "console")


@pytest.fixture(params=APPS)
def app(request: pytest.FixtureRequest) -> str:
    return request.param


def _job(app: str) -> dict[str, Any]:
    return _workflow()["jobs"][f"publish-{app}"]


def _step(app: str, step_id: str) -> dict[str, Any]:
    return next(s for s in _job(app)["steps"] if s.get("id") == step_id)


def test_a_dispatch_can_republish_the_current_release(app: str) -> None:
    inputs = _workflow()[True]["workflow_dispatch"]["inputs"]
    # A flag, not a free-text version: a re-publish of an older version would move
    # `:latest` backwards, so the only version it can publish is the current release.
    assert inputs[f"republish_{app}"]["type"] == "boolean"
    # The whole expression, not its parts: an `&&` in place of the `||` keeps every
    # substring and disables the re-publish path (#2564 review).
    assert " ".join(_job(app)["if"].split()) == (
        f"needs.release-please.outputs.{app}_release_created == 'true' || "
        f"(github.event_name == 'workflow_dispatch' && inputs.republish_{app})"
    )


def test_a_republish_takes_the_manifest_version_and_requires_its_release(app: str) -> None:
    script = _step(app, "version")["run"]
    assert ".release-please-manifest.json" in script
    assert f'gh release view "{app}-v' in script, "a re-publish must refuse a version that was never released"
    assert _step(app, "version")["env"]["GH_TOKEN"], "gh needs a token to read the release"


def test_the_publish_reads_the_resolved_version(app: str) -> None:
    assert "VERSION" not in _job(app).get("env", {}), "the version comes from the version step, not the job env"
    retag = next(s for s in _job(app)["steps"] if s.get("name", "").startswith("Re-tag"))
    assert retag["env"]["VERSION"] == "${{ steps.version.outputs.version }}"


def test_a_failed_tag_lookup_prints_its_reason(app: str) -> None:
    script = _step(app, "sha")["run"]
    assert "if ! SHA=" in script, 'a bare SHA="$(...)" exits on failure with the reason inside the variable'
    assert "::error::" in script and "$SHA" in script.split("::error::", 1)[1].split("\n", 1)[0]


def test_only_masters_pin_can_become_a_semver_tag(app: str) -> None:
    """A dispatch can run on any ref, and the pin is read from the checked-out one (#2564 review)."""
    script = _step(app, "version")["run"]
    guard = script.index('"$GITHUB_REF" != "refs/heads/master"')
    assert guard < script.index("gh release view"), "the ref check must run before anything is resolved"
    assert "exit 1" in script[guard : guard + 200], "a branch dispatch must fail, not skip"


def test_each_job_reads_its_own_apps_release_and_staging_pin(app: str) -> None:
    """A copy that kept the other app's names would pass every check above and publish the wrong image."""
    other = "console" if app == "api" else "api"
    text = json.dumps(_job(app))
    for own, foreign in (
        (f"--app {app}", f"--app {other}"),
        (f"apps/{app}", f"apps/{other}"),
        (f"{app}-v", f"{other}-v"),
        (f"${{REGISTRY_PREFIX}}-{app}", f"${{REGISTRY_PREFIX}}-{other}"),
    ):
        assert own in text and foreign not in text, f"{app}: expected {own!r} and not {foreign!r}"


def test_the_console_retag_leaves_no_mutable_alias() -> None:
    """api's re-tag also writes `:latest`; nothing deploys it, so a new lane does not add one."""
    script = next(s for s in _job("console")["steps"] if s.get("name", "").startswith("Re-tag"))["run"]
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    assert ":latest" not in code
