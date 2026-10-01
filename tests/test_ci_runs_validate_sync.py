"""The required Tests job runs every sync target's drift check (#1990).

`make validate-sync` (`toolkit sync all --check`) ran in CI only in the Windows
job of the Config Drift Gate, which is not required. On 2026-10-01 two merges
changed `common.yaml` without regenerating `infra/config/platform.json`, every
required check stayed green, and the stale file sat on master until a later PR
noticed the red Windows job. `sync all` enumerates its targets itself, so running
it in a required job covers a target added tomorrow without editing this file.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
CI = REPO / ".github/workflows/ci.yml"


def _steps(job: str) -> list[dict]:
    return yaml.safe_load(CI.read_text())["jobs"][job]["steps"]


def test_the_required_tests_job_runs_validate_sync() -> None:
    runs = [str(step.get("run", "")) for step in _steps("tests")]
    assert any("make validate-sync" in run for run in runs), "the Tests job must run `make validate-sync`"


def test_the_local_definition_of_done_still_names_it() -> None:
    """CI mirrors `make check`; if the local gate drops validate-sync, revisit this one."""
    check = next(line for line in (REPO / "Makefile").read_text().splitlines() if line.startswith("check:"))
    assert "validate-sync" in check, check
