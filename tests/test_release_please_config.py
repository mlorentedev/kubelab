"""VER-010 (#1786): only `feat` and `fix` may cut a release.

AGENTS.md states the policy: release-please cuts per-app semver tags, only
`fix:` (patch) and `feat:` (minor) trigger a release, and `chore:` does not. The
config contradicted it. A type listed in `changelog-sections` without
`hidden: true` is treated as releasable, so on 2026-09-23 a single `chore:`
commit (a70a7a5) opened a release PR bumping `errors` to 1.2.1 (#1779).

The assertion is on the invariant, not on the file's current shape: any type
that is not `feat` or `fix` must be hidden, whoever adds it later.
"""

from __future__ import annotations

import json
from pathlib import Path

RELEASING_TYPES = {"feat", "fix"}
CONFIG = Path(__file__).resolve().parents[1] / "release-please-config.json"


def test_only_feat_and_fix_are_visible_changelog_sections() -> None:
    sections = json.loads(CONFIG.read_text(encoding="utf-8"))["changelog-sections"]

    visible_non_releasing = [
        s["type"] for s in sections if s["type"] not in RELEASING_TYPES and not s.get("hidden", False)
    ]

    assert visible_non_releasing == [], (
        f"{visible_non_releasing} would cut releases; mark them `hidden: true` (AGENTS.md release policy)"
    )
