"""The scripts hermes-kubelab's jobs run inside the gateway (spec AI-012 AC5).

Each runs in the gateway container, which sees `HERMES_HOME` and nothing of the
vault or the host, so what it can say is decided by `state.db`. The tests build a
database with the columns Hermes v0.22.1 creates (measured from `hermes_state`) and
run the script's report function over it; whether Hermes accepts the script is the
live row of `verification.md`.
"""

from __future__ import annotations

import json
import sqlite3
import types
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/agent_stack"
SCRIPTS = ROLE / "files/hermes-scripts"
COMMON = REPO / "infra/config/values/common.yaml"
NOW = 1_800_000_000.0
HOUR = 3600.0
# Hermes injects at most this much of a script's output into a turn (`_MAX_CONTEXT_CHARS`
# in cron/scheduler_prompt.py, v0.22.1) and cuts the rest.
HERMES_CONTEXT_LIMIT = 8000


def _script(name: str) -> types.ModuleType:
    """Compiled from source, never imported: an import writes a .pyc into the role's
    files/, which other tests read as text."""
    path = SCRIPTS / name
    module = types.ModuleType(name.removesuffix(".py").replace("-", "_"))
    exec(compile(path.read_text(), str(path), "exec"), module.__dict__)  # noqa: S102
    return module


def _database(tmp_path: Path, sessions: list[dict], messages: list[tuple]) -> Path:
    path = tmp_path / "state.db"
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT,
            started_at REAL NOT NULL, message_count INTEGER DEFAULT 0);
        CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
            role TEXT NOT NULL, content TEXT, timestamp REAL NOT NULL, active INTEGER NOT NULL DEFAULT 1);
        """
    )
    for s in sessions:
        db.execute(
            "INSERT INTO sessions (id, source, title, started_at, message_count) VALUES (?, ?, ?, ?, ?)",
            (s["id"], s["source"], s.get("title"), s["started_at"], s.get("message_count", 0)),
        )
    db.executemany("INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)", messages)
    db.commit()
    db.close()
    return path


def _chat(sid: str, source: str = "slack", age_hours: float = 2.0, **session: object) -> tuple[dict, list[tuple]]:
    started = NOW - age_hours * HOUR
    return (
        {"id": sid, "source": source, "started_at": started, **session},
        [(sid, "user", "what is the state of the backup?", started), (sid, "assistant", "It is fine.", started + 5)],
    )


def _report(tmp_path: Path, *chats: tuple[dict, list[tuple]]) -> str:
    sessions = [s for s, _ in chats]
    messages = [m for _, ms in chats for m in ms]
    return _script("session-activity.py").report(_database(tmp_path, sessions, messages), NOW)


# --------------------------------------------------------------------------- session-activity


def test_a_day_without_activity_stops_the_turn_before_it_starts(tmp_path: Path) -> None:
    """Hermes skips the agent, the delivery and the token spend on this last line."""
    old = _chat("old", age_hours=30)
    out = _report(tmp_path, old)
    assert json.loads(out.strip().splitlines()[-1]) == {"wakeAgent": False}


def test_no_database_means_no_activity(tmp_path: Path) -> None:
    out = _script("session-activity.py").report(tmp_path / "missing.db", NOW)
    assert json.loads(out.strip().splitlines()[-1]) == {"wakeAgent": False}


def test_operator_sessions_are_reported_with_what_was_said(tmp_path: Path) -> None:
    out = _report(tmp_path, _chat("s1", title="Backups"))
    assert "Backups" in out
    assert "slack" in out
    assert "what is the state of the backup?" in out
    assert "It is fine." in out
    assert "wakeAgent" not in out


@pytest.mark.parametrize("source", ["cron", "subagent", "tool", "recovered", "kanban"])
def test_automated_sessions_are_not_the_operators_day(tmp_path: Path, source: str) -> None:
    """The job's own run, a delegated child, a recovered turn: none of them is activity,
    and counting them would make the record describe itself."""
    out = _report(tmp_path, _chat("auto", source=source))
    assert json.loads(out.strip().splitlines()[-1]) == {"wakeAgent": False}


def test_only_the_last_day_is_reported(tmp_path: Path) -> None:
    out = _report(tmp_path, _chat("recent", age_hours=3, title="Recent"), _chat("old", age_hours=40, title="Stale"))
    assert "Recent" in out
    assert "Stale" not in out


def test_a_long_message_is_cut_and_the_report_fits_what_hermes_injects(tmp_path: Path) -> None:
    started = NOW - HOUR
    messages = [("big", "user", "x" * 50_000, started + i) for i in range(200)]
    out = _script("session-activity.py").report(
        _database(tmp_path, [{"id": "big", "source": "slack", "started_at": started}], messages), NOW
    )
    assert len(out) < HERMES_CONTEXT_LIMIT, "Hermes cuts the context at its limit, mid-sentence"
    assert "more message" in out, "what was left out is said, not silently dropped"


@pytest.mark.parametrize(
    "secret",
    [
        "sk-ant-api03-" + "a" * 30,
        # Assembled, or the push protection takes the fixture for a real token.
        "xox" + "b-" + "1234567890-" + "abcdefghijklmnop",
        "ghp_" + "b" * 36,
        "github_pat_" + "c" * 40,
        "Authorization: Bearer " + "d" * 30,
        "xox" + "e-" + "1-" + "abcdefghijklmnop",
        "eyJ" + "hbGciOiJIUzI1NiJ9." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0." + "dozjgNryP4J3jVmNHl0w5N",
    ],
)
def test_a_credential_pasted_into_a_conversation_does_not_reach_the_record(tmp_path: Path, secret: str) -> None:
    started = NOW - HOUR
    chat = (
        {"id": "s", "source": "slack", "started_at": started},
        [("s", "user", f"here is my token {secret} please keep it", started)],
    )
    out = _report(tmp_path, chat)
    assert secret not in out
    assert secret.split()[-1] not in out
    assert "please keep it" in out


def test_the_database_is_opened_read_only(tmp_path: Path) -> None:
    """A report must not be able to change the gateway's session store: the
    connection it opens refuses a write, whatever the code around it does."""
    path = _database(tmp_path, [{"id": "s", "source": "slack", "started_at": NOW}], [])
    db = _script("session-activity.py")._connect(path)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        db.execute("INSERT INTO sessions (id, source, started_at) VALUES ('x', 'slack', 1)")
    db.close()


# --------------------------------------------------------------------------- the declaration


def _declared_jobs() -> dict:
    hermes = yaml.safe_load(COMMON.read_text())["apps"]["services"]["ai"]["hermes_kubelab"]
    return hermes["cron"]["jobs"]


def test_every_script_a_job_names_ships_with_the_role() -> None:
    """A missing file is found at the job's first fire, by a failure notice nobody asked for."""
    for key, job in _declared_jobs().items():
        script = job.get("script")
        if script:
            assert (SCRIPTS / script).is_file(), f"job {key!r} names {script!r}, which the role does not ship"


def test_every_shipped_script_is_used_by_a_job_and_parses() -> None:
    named = {job["script"] for job in _declared_jobs().values() if job.get("script")}
    shipped = {p.name for p in SCRIPTS.iterdir()}
    assert shipped == named, f"shipped but unused: {shipped - named}"
    for name in shipped:
        compile((SCRIPTS / name).read_text(), name, "exec")


def test_the_session_record_runs_on_the_scripts_data_and_writes_where_the_zone_is() -> None:
    hermes = yaml.safe_load(COMMON.read_text())["apps"]["services"]["ai"]["hermes_kubelab"]
    job = hermes["cron"]["jobs"]["session-record"]
    assert job["mode"] == "agent"
    assert job["script"] == "session-activity.py"
    zone = f"{hermes['vault_sync']['mount']}/{hermes['vault_zone']}/sessions/"
    assert zone in job["prompt"], "the prompt must name the one place the sandbox can write"
    assert "/vault/" not in job["prompt"].replace(zone, ""), "it names no other vault path"
