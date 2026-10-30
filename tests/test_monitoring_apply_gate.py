"""`make monitoring-apply` shows its plan before it writes, and never deletes unasked (MON-012, #2078).

On 2026-10-06 an apply deleted `Leaving Denver` (id 503), a monitor made by hand
in the Kuma UI as another repository's runbook instructs, and its uptime history
with it. The sync plan was printed and executed in the same breath. These tests
drive `apply_monitors` against a fake instance that records every write.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from uptime_kuma_api import Timeout, UptimeKumaException

from toolkit.features import monitoring
from toolkit.features.monitoring_diff import embed_key

READS = {"get_monitors", "get_monitor", "get_tags", "get_notifications", "disconnect", "timeout"}


def _gone() -> UptimeKumaException:
    """What Kuma 2.2.1 answers `getMonitor` for an id it no longer has: it reads a null row."""
    return UptimeKumaException("Cannot read properties of null (reading 'id')")


class FakeKuma:
    """A live instance that answers reads and records every write."""

    timeout = 5

    def __init__(self, live: list[dict[str, Any]]) -> None:
        self.live = live
        self.writes: list[str] = []
        self.sio = self

    def get_monitors(self) -> list[dict[str, Any]]:
        return [m for m in self.live if m["id"] not in self._deleted()]

    def get_monitor(self, monitor_id: int) -> dict[str, Any]:
        if monitor_id in self._deleted():
            raise _gone()
        return next(m for m in self.live if m["id"] == monitor_id)

    def get_tags(self) -> list[dict[str, Any]]:
        return []

    def get_notifications(self) -> list[dict[str, Any]]:
        return []

    def disconnect(self) -> None:
        pass

    def _deleted(self) -> set[int]:
        return {int(w.split(":")[1]) for w in self.writes if w.startswith("delete_monitor:")}

    def delete_monitor(self, monitor_id: int) -> None:
        self.writes.append(f"delete_monitor:{monitor_id}")

    def add_tag(self, **_: Any) -> dict[str, int]:
        self.writes.append("add_tag")
        return {"id": 1}

    def edit_monitor(self, monitor_id: int, **_: Any) -> None:
        self.writes.append(f"edit_monitor:{monitor_id}")

    def _build_monitor_data(self, **params: Any) -> dict[str, Any]:
        return dict(params)

    def call(self, event: str, data: dict[str, Any], timeout: int) -> dict[str, Any]:
        self.writes.append(f"sio:{event}")
        return {"ok": True, "monitorID": 99}

    def add_monitor_tag(self, *_: Any) -> None:
        self.writes.append("add_monitor_tag")


def _monitor(key: str, monitor_id: int | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"key": key, "name": key, "type": "http", "url": f"https://{key}.example", "interval": 60}
    if monitor_id is not None:
        entry = {
            "id": monitor_id,
            "name": key,
            "type": "http",
            "url": f"https://{key}.example",
            "interval": 60,
            "description": embed_key("", key),
        }
    return entry


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    seed_dir = tmp_path / monitoring.EXPORT_DIR
    seed_dir.mkdir(parents=True)
    (seed_dir / monitoring.TAGS_FILE).write_text(json.dumps([{"name": "on-demand", "color": "#000"}]))

    def run(seed: list[dict[str, Any]], live: list[dict[str, Any]], **flags: bool) -> FakeKuma:
        (seed_dir / monitoring.MONITORS_FILE).write_text(json.dumps(seed))
        kuma = FakeKuma(live)
        run.last = kuma  # type: ignore[attr-defined]
        monkeypatch.setattr(monitoring, "_connect", lambda _root: (kuma, {}))
        monkeypatch.setattr(monitoring, "_get_muted_notification_tags", lambda _root: frozenset())
        monkeypatch.setattr(monitoring, "_get_push_tokens", lambda _root: {})
        monitoring.apply_monitors(tmp_path, **flags)
        return kuma

    return run


class Lines:
    """Stands in for the toolkit logger and keeps every message."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def __getattr__(self, _level: str):
        return lambda message, *_, **__: self.lines.append(str(message))


def test_check_writes_nothing_and_names_what_it_would_delete(project, monkeypatch) -> None:
    log = Lines()
    monkeypatch.setattr(monitoring, "logger", log)
    kuma = project([_monitor("keep"), _monitor("new")], [_monitor("keep", 1), _monitor("hand-made", 503)], check=True)
    lines = log.lines
    assert kuma.writes == [], "a check run must not touch the instance, tags included"
    assert any("hand-made" in line and "503" in line for line in lines), lines
    assert any("new" in line and "create" in line.lower() for line in lines), lines


def test_an_apply_that_would_delete_refuses_before_any_write(project) -> None:
    with pytest.raises(SystemExit) as refused:
        project([_monitor("keep"), _monitor("new")], [_monitor("keep", 1), _monitor("hand-made", 503)])
    assert refused.value.code == 1
    assert project.last.writes == [], "refused after a partial write leaves a half-applied seed"


def test_prune_deletes_what_the_seed_dropped(project) -> None:
    kuma = project([_monitor("keep")], [_monitor("keep", 1), _monitor("hand-made", 503)], prune=True)
    assert "delete_monitor:503" in kuma.writes


def test_an_apply_with_nothing_to_delete_needs_no_prune(project) -> None:
    kuma = project([_monitor("keep"), _monitor("new")], [_monitor("keep", 1)])
    assert "sio:add" in kuma.writes
    assert not [w for w in kuma.writes if w.startswith("delete_monitor")]


@pytest.mark.parametrize(
    ("value", "flag"),
    [("PRUNE=1", "--prune"), ("PRUNE=0", None), ("PRUNE=no", None), ("CHECK=1", "--check"), ("CHECK=0", None)],
)
def test_only_a_1_turns_a_make_flag_on(value: str, flag: str | None) -> None:
    """`PRUNE=0`, written to be safe, must not delete every unseeded monitor."""
    root = Path(__file__).resolve().parent.parent
    out = subprocess.run(
        ["make", "-n", "-C", str(root), "monitoring-apply", value], capture_output=True, text=True, check=True
    ).stdout
    line = next(text for text in out.splitlines() if "monitoring apply" in text)
    passed = {arg for arg in line.split() if arg in {"--prune", "--check"}}
    assert passed == ({flag} if flag else set())


def test_an_edit_attaches_the_tags_the_seed_added(project) -> None:
    """#1974: a tag added to the seed of an existing monitor reaches it live."""
    kuma = project([{**_monitor("keep"), "tags": ["on-demand"]}], [_monitor("keep", 1)])
    assert kuma.writes[-2:] == ["edit_monitor:1", "add_monitor_tag"], kuma.writes


def test_a_create_attaches_the_seed_tags(project) -> None:
    kuma = project([{**_monitor("new"), "tags": ["on-demand"]}], [])
    assert kuma.writes[-2:] == ["sio:add", "add_monitor_tag"], kuma.writes


@pytest.mark.parametrize("live", [[_monitor("broken", 1)], []], ids=["edit", "create"])
def test_a_monitor_that_fails_to_converge_fails_the_apply(project, live) -> None:
    """#2292: a failure used to be a warning, and `make monitoring-apply` exited 0."""
    seed = [{**_monitor("broken"), "tags": ["undeclared"]}, {**_monitor("fine"), "tags": ["on-demand"]}]
    with pytest.raises(SystemExit) as failed:
        project(seed, [*live, _monitor("fine", 2)])
    assert failed.value.code == 1
    # The failure does not stop the monitors after it.
    assert "edit_monitor:2" in project.last.writes, project.last.writes


class Lingering:
    """An instance whose read of a deleted monitor finds it, or fails with `error`."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.reads = 0

    def get_monitor(self, monitor_id: int) -> dict[str, Any]:
        self.reads += 1
        if self.error is not None:
            raise self.error
        return {"id": monitor_id}


def test_a_monitor_still_present_past_the_deadline_refuses_the_creates(monkeypatch) -> None:
    """The guard behind #925: creating while a deleted monitor is still there duplicates it (#2506)."""
    monkeypatch.setattr(monitoring.time, "sleep", lambda _seconds: None)
    kuma = Lingering()
    with pytest.raises(RuntimeError, match="still present"):
        monitoring._assert_deleted(kuma, [503], timeout=0.05)
    assert kuma.reads > 1, "refused without polling"


@pytest.mark.parametrize(
    "error",
    [
        Timeout("Timed out while waiting for event getMonitor"),
        UptimeKumaException("You are not logged in."),
        ConnectionError("socket closed"),
    ],
    ids=["timeout", "logged-out", "socket"],
)
def test_only_kumas_not_found_answer_counts_as_deleted(error: Exception) -> None:
    """A read that failed says nothing about the delete, so it must not confirm one (#2506)."""
    with pytest.raises(type(error)):
        monitoring._assert_deleted(Lingering(error), [503], timeout=5)


def test_a_delete_confirmed_at_the_first_read_waits_for_nothing(project, monkeypatch) -> None:
    """No fixed sleep on the apply path (OPS-016 f3): the bounded poll replaced a `time.sleep(3)` (#925)."""

    def refuse(seconds: float) -> None:
        raise AssertionError(f"slept {seconds}s on an apply whose delete was already confirmed")

    monkeypatch.setattr(monitoring.time, "sleep", refuse)
    kuma = project([_monitor("keep")], [_monitor("keep", 1), _monitor("hand-made", 503)], prune=True)
    assert "delete_monitor:503" in kuma.writes
