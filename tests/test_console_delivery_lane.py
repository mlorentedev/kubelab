"""console's staging lane is api's lane for its own app (ADR-074 sequence step 3, ADR-046, ADR-056).

`staging-deploy.yml` builds each in-tree app's `sha-<short>` image on a push to master and keeps one
long-lived deploy pull request per app. console got its own build job and its own copy of the
`open-pr` job rather than a matrix, because the tests that execute that job's scripts look it up
by name (tests/test_staging_deploy_forward_only.py, tests/test_receiver_pr_step.py). A copy can
drift from what it copies, and that drift would be invisible: the lane would still run. So this
file holds the two jobs to each other, apart from the names that must differ.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _staging() -> dict[str, Any]:
    return yaml.safe_load((ROOT / ".github/workflows/staging-deploy.yml").read_text(encoding="utf-8"))


def _as_api(job: dict[str, Any]) -> str:
    """console's job with its app's name replaced by api's, minus its display name.

    Only console's side is rewritten: api's job holds `gh api` and "API failure" in prose, which
    a rewrite in that direction would turn into something the console job does not say.
    """
    body = {k: v for k, v in job.items() if k != "name"}
    return json.dumps(body, sort_keys=True).replace("console", "api").replace("CONSOLE", "API")


def _plain(job: dict[str, Any]) -> str:
    return json.dumps({k: v for k, v in job.items() if k != "name"}, sort_keys=True)


def test_the_console_job_is_the_api_job_for_another_app() -> None:
    jobs = _staging()["jobs"]
    assert _as_api(jobs["open-pr-console"]) == _plain(jobs["open-pr"])


def test_the_two_lanes_do_not_share_a_writer() -> None:
    """One concurrency group and one branch per app: a shared one would let console's push replace api's offer."""
    jobs = _staging()["jobs"]
    assert jobs["open-pr"]["concurrency"]["group"] != jobs["open-pr-console"]["concurrency"]["group"]
    script = next(s for s in jobs["open-pr-console"]["steps"] if s.get("id") == "open-pr")["run"]
    assert 'BRANCH="deploy/staging-${APP}"' in script
    assert "deploy/staging-api" not in json.dumps(jobs["open-pr-console"])


def test_a_console_change_builds_the_console_image_and_only_it() -> None:
    wf = _staging()
    detect = wf["jobs"]["detect-changes"]
    assert detect["outputs"]["console"] == "${{ steps.filter.outputs.console }}"
    filters = yaml.safe_load(next(s for s in detect["steps"] if s.get("id") == "filter")["with"]["filters"])
    assert filters["console"] == ["apps/console/**"]
    assert filters["api"] == ["apps/api/**"], "api's filter must not pick up console files"

    build = wf["jobs"]["build-console"]
    assert build["if"] == "needs.detect-changes.outputs.console == 'true'"
    assert build["uses"] == "./.github/workflows/ci-publish.yml"
    assert build["with"]["app"] == "console"
    assert build["with"]["context"] == "./apps/console"
    assert build["with"]["tag"] == "${{ needs.detect-changes.outputs.sha }}"


def test_console_has_no_deploy_pull_request_without_its_own_successful_build() -> None:
    job = _staging()["jobs"]["open-pr-console"]
    assert job["needs"] == ["detect-changes", "build-console"]
    assert "needs.build-console.result == 'success'" in " ".join(job["if"].split())
    assert "build-api" not in json.dumps(job)


def test_the_release_job_for_console_is_api_s_for_another_app() -> None:
    """The re-tag copies a manifest list, so the two copies must stay equal apart from the app and `:latest`."""
    jobs = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))["jobs"]
    api = _plain(jobs["publish-api"])
    console = _as_api(jobs["publish-console"])
    # api's re-tag also writes `:latest`; console's does not (tests/test_release_publish_api.py).
    api = api.replace(' -t \\"${REGISTRY}:latest\\" \\\\\\n', "")
    api_steps = json.loads(api)["steps"]
    console_steps = json.loads(console)["steps"]
    retag = next(i for i, s in enumerate(api_steps) if s.get("name", "").startswith("Re-tag"))
    for step in (api_steps, console_steps):
        step[retag]["run"] = " ".join(
            line.strip()
            for line in step[retag]["run"].splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    assert api_steps == console_steps


def test_release_please_hands_the_release_job_console_s_own_outputs() -> None:
    """The job's `if:` reads these outputs, so an output wired to another package publishes nothing or the wrong tag."""
    outputs = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))["jobs"][
        "release-please"
    ]["outputs"]
    assert outputs["console_release_created"] == "${{ steps.release.outputs['apps/console--release_created'] }}"
    assert outputs["console_version"] == "${{ steps.release.outputs['apps/console--version'] }}"
