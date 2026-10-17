"""The upgrade probes run inside the restored scratch server and fail closed (OPS-038).

A version bump can keep every repository and still break what clients call, so the
restore drill also checks the REST contract `dotf forge` relies on and that merge
settings are applied, not only accepted (TOOL-063).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from toolkit.features.gitea_upgrade_probe import run_probes

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
            out = "[E] schema mismatch\n" if self.broken.get("doctor") else "[I] all good\n"
            return 0, out, ""
        if "generate-access-token" in argv:
            return (1, "", "boom") if self.broken.get("mint") else (0, TOKEN + "\n", "")
        method = argv[argv.index("-X") + 1]
        path = argv[-1].split("/api/v1", 1)[1]
        if method == "GET" and path.count("/") == 3:
            return 0, json.dumps({"has_issues": not self.broken.get("no_issues"), "default_merge_style": self.merge_style}), ""
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
