"""The upgrade probes run inside the restored scratch server and fail closed (OPS-038).

A version bump can keep every repository and still break what clients call, so the
restore drill also checks the REST contract `dotf forge` relies on and that merge
settings are applied, not only accepted (TOOL-063).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.features.gitea_upgrade_probe import KNOWN_BASELINE_FAILURES, run_probes

COMMON = Path(__file__).resolve().parent.parent / "infra/config/values/common.yaml"

TOKEN = "PROBE-TOKEN-THAT-MUST-NOT-PRINT"


class FakeServer:
    """Answers `docker exec` calls the way a healthy upgraded Gitea does, with one knob per failure."""

    def __init__(self, **broken: Any) -> None:
        self.broken = broken
        self.calls: list[list[str]] = []
        self.merge_style = "merge"

    def __call__(self, argv: list[str], **_: Any) -> tuple[int, str, str]:
        self.calls.append(argv)
        if "doctor" in argv:
            out = "[1] Garbage collect LFS\nERROR\n[2] Check schema\n- [I] fine\nOK\n"
            if self.broken.get("doctor"):
                out += "[3] Check tables\n- [E] schema mismatch\nERROR\n"
            stale = self.broken.get("stale_merge_bases")
            if stale is True:  # the count line is worded differently: the ceiling cannot be read
                out += "[4] Recalculate merge bases\n- [E] 5 pull requests are stale of 370\nERROR\n"
            elif stale:
                out += f"[4] Recalculate merge bases\n- [E] {stale} PRs with incorrect mergebases of 370\nERROR\n"
            return 0, out, ""
        if "generate-access-token" in argv:
            return (1, "", "boom") if self.broken.get("mint") else (0, TOKEN + "\n", "")
        method = argv[argv.index("-X") + 1]
        path = argv[-1].split("/api/v1", 1)[1]
        if method == "GET" and path.count("/") == 3:
            return (
                0,
                json.dumps({"has_issues": not self.broken.get("no_issues"), "default_merge_style": self.merge_style}),
                "",
            )
        if method == "POST" and path.endswith("/issues"):
            return (22, "", "") if self.broken.get("issue") else (0, json.dumps({"number": 7}), "")
        if method == "POST" and path.endswith("/comments"):
            return 0, json.dumps({} if self.broken.get("html_url") else {"html_url": "http://x/c/1"}), ""
        if method == "PATCH" and "/issues/" in path:
            return (22, "", "") if self.broken.get("issue_edit") else (0, "{}", "")
        if method == "PATCH":  # repository settings
            if not self.broken.get("not_applied"):
                self.merge_style = "squash"
            return (22, "", "") if self.broken.get("patch") else (0, "{}", "")
        raise AssertionError(argv)


def _run(server: FakeServer) -> bool:
    return run_probes(server, "scratch", "admin", ["o/r"])


def test_a_healthy_upgraded_server_passes() -> None:
    assert _run(FakeServer())


@pytest.mark.parametrize(
    "broken",
    ["doctor", "mint", "no_issues", "issue", "html_url", "issue_edit", "patch", "not_applied"],
)
def test_every_broken_behaviour_fails_the_drill(broken: str) -> None:
    assert not _run(FakeServer(**{broken: True}))


def test_a_patch_that_answers_2xx_without_applying_is_not_a_pass() -> None:
    """The failure TOOL-063 measured: the endpoint says 200 and the settings are unchanged."""
    assert not _run(FakeServer(not_applied=True))


def test_the_token_is_only_ever_sent_to_the_scratch_container(caplog: pytest.LogCaptureFixture) -> None:
    server = FakeServer()
    _run(server)
    assert all(argv[:2] == ["docker", "exec"] for argv in server.calls)
    assert TOKEN not in caplog.text


def test_a_failing_doctor_check_is_named_in_the_output(capsys: pytest.CaptureFixture[str]) -> None:
    _run(FakeServer(doctor=True))
    assert "schema mismatch" in "".join(capsys.readouterr())


def test_the_lfs_collection_error_the_deployed_version_also_has_is_not_a_failure() -> None:
    """Measured on 1.25.5 with the same data: it errors there too, so it cannot be blamed on an upgrade."""
    assert _run(FakeServer())


def test_a_failing_doctor_check_is_named_by_its_header(capsys: pytest.CaptureFixture[str]) -> None:
    """Doctor lists its checks as `[N] Name`; the drill must say which one failed, not only the row."""
    _run(FakeServer(doctor=True))
    assert "failing doctor check: Check tables" in "".join(capsys.readouterr())


def test_a_stale_merge_base_fails_the_drill() -> None:
    """OPS-039: 23 stale merge bases measured on 1.25.5 were gone from the first snapshot taken on 1.27.3, so the
    check is no longer excused. Any stale row on the restored copy now fails."""
    assert not _run(FakeServer(stale_merge_bases=1))


def test_the_baseline_exclusions_do_not_widen() -> None:
    """A doctor check excused here never fails the drill, so a new entry would quiet a corrupt
    migrated database. Only a check measured failing on the old version with the same data
    belongs here, with its reason (TOOL-124)."""
    assert set(KNOWN_BASELINE_FAILURES) == {"Garbage collect LFS"}
    assert all(reason.strip() for reason in KNOWN_BASELINE_FAILURES.values())


def test_the_forge_runs_a_gitea_with_workflow_concurrency() -> None:
    """OPS-038 upgraded the forge for `concurrency` with `cancel-in-progress` (go-gitea/gitea#32751).
    The floor is the version it rehearsed, 1.27.3, not 1.26.0 where the feature first shipped:
    1.26.x leaked groups across branches, deadlocked and regressed, and only 1.27.3 stops an
    unapproved fork run from cancelling a trusted one (GHSA-4j4g-m7mr-hp5j; OPS-038 proposal).
    Raise the floor with each upgrade that is rehearsed."""
    image = yaml.safe_load(COMMON.read_text(encoding="utf-8"))["apps"]["services"]["core"]["gitea"]["image"]
    version = re.search(r":(\d+)\.(\d+)\.(\d+)", image)
    assert version, f"{image}: the pin names no version, so the floor cannot be read"
    assert tuple(map(int, version.groups())) >= (1, 27, 3), image
