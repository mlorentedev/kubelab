"""`toolkit infra argo wait-status`: read the commit status Argo CD posts per sync (GITOPS-003 AC2, #1478).

The GitHub API is simulated: `fetch` is a scripted callable and the clock is
fake, so every verdict is reached without a network or a real wait.
"""

from __future__ import annotations

from typing import Any

import pytest

from toolkit.features.argo_manager import (
    StatusFetchError,
    WaitStatus,
    latest_status,
    wait_status,
)

CONTEXT = "argocd/kubelab-staging"


def _status(state: str, context: str = CONTEXT, description: str = "", updated: str = "2026-10-21T10:00:00Z"):
    return {"state": state, "context": context, "description": description, "updated_at": updated}


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def _run(script: list[Any], timeout: float = 60, poll: float = 10):
    """Run wait_status against scripted answers; the last answer repeats. An exception instance is raised."""
    clock = FakeClock()
    calls = {"n": 0}

    def fetch() -> list[dict[str, Any]]:
        answer = script[min(calls["n"], len(script) - 1)]
        calls["n"] += 1
        if isinstance(answer, Exception):
            raise answer
        return answer

    verdict, line = wait_status(
        context=CONTEXT, fetch=fetch, timeout=timeout, poll=poll, now=clock.now, sleep=clock.sleep
    )
    return verdict, line, clock.t, calls["n"]


class TestLatestStatus:
    def test_the_newest_status_of_the_context_wins(self) -> None:
        # GitHub lists a commit's statuses newest first; a later success
        # supersedes an earlier pending of the same context.
        statuses = [_status("success", updated="2026-10-21T10:05:00Z"), _status("pending")]
        assert latest_status(statuses, CONTEXT)["state"] == "success"

    def test_the_newest_by_timestamp_wins_whatever_the_list_order(self) -> None:
        statuses = [_status("pending", updated="2026-10-21T10:00:00Z"), _status("success", updated="2026-10-21T10:05:00Z")]
        assert latest_status(statuses, CONTEXT)["state"] == "success"

    def test_other_contexts_are_ignored(self) -> None:
        statuses = [_status("success", context="argocd/kubelab-prod"), _status("failure")]
        assert latest_status(statuses, CONTEXT)["state"] == "failure"

    def test_no_status_for_the_context_is_none(self) -> None:
        assert latest_status([_status("success", context="ci/tests")], CONTEXT) is None
        assert latest_status([], CONTEXT) is None


class TestWaitStatus:
    def test_success_is_zero_at_once(self) -> None:
        verdict, line, t, _ = _run([[_status("success", description="Synced at 49638d3")]])
        assert verdict is WaitStatus.SUCCESS and int(verdict) == 0
        assert "Synced at 49638d3" in line
        assert t == 0

    def test_failure_is_red_at_once_with_its_description(self) -> None:
        msg = "one or more synchronization tasks are not valid"
        verdict, line, t, _ = _run([[_status("failure", description=msg)]])
        assert verdict is WaitStatus.FAILED and int(verdict) == 1
        assert msg in line
        # Red without waiting: a failed sync at this revision is final.
        assert t == 0 and "no status arrived" not in line

    def test_error_state_is_red_like_failure(self) -> None:
        verdict, _, t, _ = _run([[_status("error", description="panic")]])
        assert verdict is WaitStatus.FAILED and t == 0

    def test_pending_then_success_waits_for_the_outcome(self) -> None:
        verdict, _, t, calls = _run([[_status("pending")], [_status("success")]])
        assert verdict is WaitStatus.SUCCESS
        assert calls == 2 and t == 10

    def test_no_status_by_the_deadline_says_none_arrived(self) -> None:
        verdict, line, t, _ = _run([[]], timeout=60)
        assert verdict is WaitStatus.FAILED
        assert "no status arrived" in line and CONTEXT in line
        assert t >= 60

    def test_still_pending_at_the_deadline_is_red_and_says_so(self) -> None:
        verdict, line, _, _ = _run([[_status("pending", description="syncing")]], timeout=30)
        assert verdict is WaitStatus.FAILED
        assert "still pending" in line and "no status arrived" not in line

    def test_an_api_outage_through_the_deadline_cannot_check(self) -> None:
        verdict, line, _, _ = _run([StatusFetchError("HTTP 502")], timeout=30)
        assert verdict is WaitStatus.CANNOT_CHECK and int(verdict) == 2
        assert "HTTP 502" in line

    def test_an_outage_after_pending_says_what_was_last_read(self) -> None:
        verdict, line, _, _ = _run([[_status("pending", description="syncing")], StatusFetchError("HTTP 502")], timeout=30)
        assert verdict is WaitStatus.CANNOT_CHECK
        assert "HTTP 502" in line and "still pending: syncing" in line

    def test_a_transient_api_error_is_retried(self) -> None:
        verdict, _, _, calls = _run([StatusFetchError("HTTP 502"), [_status("success")]])
        assert verdict is WaitStatus.SUCCESS and calls == 2


@pytest.mark.parametrize("state", ["success", "failure", "error", "pending"])
def test_every_github_status_state_has_a_verdict(state: str) -> None:
    # GitHub's four states, and nothing else: an unhandled one must not fall
    # through to a silent wait.
    verdict, _, _, _ = _run([[_status(state)]], timeout=0)
    assert isinstance(verdict, WaitStatus)


class TestFetchStatuses:
    def _fake_gh(self, monkeypatch: pytest.MonkeyPatch, returncode: int, stdout: str, stderr: str = "") -> list:
        import subprocess

        from toolkit.features import argo_manager

        seen: list = []

        def run(argv, **_kwargs):
            seen.append(argv)
            return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

        monkeypatch.setattr(argo_manager.subprocess, "run", run)
        return seen

    def test_reads_the_per_commit_list_not_the_combined_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The combined /status answers `pending` for a commit with no statuses,
        # which would turn "Argo never posted" into an endless wait.
        from toolkit.features.argo_manager import fetch_statuses

        seen = self._fake_gh(monkeypatch, 0, '[{"state": "success", "context": "c"}]')
        assert fetch_statuses("o/r", "abc") == [{"state": "success", "context": "c"}]
        assert seen[0][-1].startswith("repos/o/r/commits/abc/statuses")

    def test_a_gh_failure_raises_and_never_reads_as_no_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from toolkit.features.argo_manager import fetch_statuses

        self._fake_gh(monkeypatch, 1, "", "HTTP 502: Bad Gateway")
        with pytest.raises(StatusFetchError, match="502"):
            fetch_statuses("o/r", "abc")

    def test_a_non_list_answer_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from toolkit.features.argo_manager import fetch_statuses

        self._fake_gh(monkeypatch, 0, '{"state": "pending", "statuses": []}')
        with pytest.raises(StatusFetchError):
            fetch_statuses("o/r", "abc")
