"""#2552: the errors promotion PR commits every file `promote --app errors` writes.

#2436 made the promote regenerate `platform.json`, but the `promote-errors` job
still staged only `common.yaml` and the kustomization. The regenerated manifest
stayed in the runner's tree, and every promotion PR opened red on
`test_the_committed_manifest_matches_its_ssot` (#2542).
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

import yaml

from toolkit.features import promotion

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github/workflows/release.yml"


def _open_pr_step() -> dict[str, Any]:
    job = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["promote-errors"]
    return next(s for s in job["steps"] if s.get("name") == "Open errors promotion PR")


def _staged_paths() -> list[str]:
    adds = [line.strip() for line in _open_pr_step()["run"].splitlines() if line.strip().startswith("git add ")]
    # One `git add`: a second one could stage a file this test never compares.
    assert len(adds) == 1, adds
    return shlex.split(adds[0])[2:]


def test_the_promotion_pr_stages_every_file_promote_writes() -> None:
    assert sorted(_staged_paths()) == sorted(promotion.ERRORS_PROMOTION_FILES)


def test_every_declared_file_exists_in_the_repo() -> None:
    # A path that drifted from the tree would stage nothing and still pass the set compare.
    assert [p for p in promotion.ERRORS_PROMOTION_FILES if not (REPO / p).is_file()] == []
