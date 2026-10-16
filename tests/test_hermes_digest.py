"""The daily health and consumption digest, and the memory mount (spec AI-012 AC5).

The digest is a no-agent job: Hermes delivers the script's stdout to Slack as it
is, and a script that prints nothing sends nothing. So the tests hold it to two
things a status report is for: it never goes quiet (a dead gateway must read as a
message, not as silence), and what it says about spend is arithmetic over rows the
gateway wrote, which they build with the columns Hermes v0.22.1 creates.
"""

from __future__ import annotations

import sqlite3
import types
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/agent_stack"
SCRIPT = ROLE / "files/hermes-scripts/daily-digest.py"
COMMON = REPO / "infra/config/values/common.yaml"
NOW = datetime(2026, 10, 16, 8, 5, tzinfo=UTC).timestamp()
MONTH_START = datetime(2026, 10, 1, tzinfo=UTC).timestamp()
GB = 1024**3

GATEWAY = ("hermes-kubelab", "running", "Up 3 days")
SIDECAR = ("hermes-kubelab-tailscale", "running", "Up 3 days")
SANDBOX = ("hermes-28206a30", "running", "Up 2 minutes")


def _digest() -> types.ModuleType:
    """Compiled from source, never imported: an import writes a .pyc into the role's
    files/, which other tests read as text."""
    module = types.ModuleType("daily_digest")
    exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), module.__dict__)  # noqa: S102
    return module


def _usage_db(tmp_path: Path, rows: list[tuple]) -> Path:
    path = tmp_path / "state.db"
    db = sqlite3.connect(path)
    db.execute(
        """CREATE TABLE session_model_usage (session_id TEXT NOT NULL, model TEXT NOT NULL,
            billing_provider TEXT, task TEXT NOT NULL DEFAULT '', api_call_count INTEGER DEFAULT 0,
            input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,
            estimated_cost_usd REAL DEFAULT 0, actual_cost_usd REAL DEFAULT 0,
            first_seen REAL NOT NULL, last_seen REAL NOT NULL)"""
    )
    db.executemany(
        "INSERT INTO session_model_usage (session_id, model, billing_provider, api_call_count, input_tokens,"
        " output_tokens, estimated_cost_usd, actual_cost_usd, first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    db.commit()
    db.close()
    return path


def _row(model: str, provider: str, calls: int, tin: int, tout: int, cost: float = 0.0, seen: float = NOW - 3600):
    return ("s", model, provider, calls, tin, tout, cost, 0.0, seen, seen)


def _report(
    db: Path | None, containers=(GATEWAY, SIDECAR, SANDBOX), disk=(100 * GB, 40 * GB), tmp: Path | None = None
) -> str:
    path = db if db is not None else (tmp or Path("/nonexistent")) / "missing.db"
    return _digest().report(path, NOW, list(containers) if containers is not None else None, disk)


def test_a_healthy_day_names_each_part_and_the_month(tmp_path: Path) -> None:
    out = _report(_usage_db(tmp_path, [_row("qwen3.6", "custom", 12, 175_880, 4_723)]))
    assert "2026-10-16" in out
    assert "hermes-kubelab" in out
    assert "tailscale" in out.lower()
    assert "1 sandbox" in out
    assert "qwen3.6" in out
    assert "custom" in out
    assert "175,880" in out, "tokens are read at a glance with their thousands separated"


def test_a_stopped_gateway_is_the_first_thing_the_digest_says(tmp_path: Path) -> None:
    down = ("hermes-kubelab", "exited", "Exited (1) 5 minutes ago")
    out = _report(_usage_db(tmp_path, []), containers=(down, SIDECAR))
    first = out.splitlines()[0]
    assert "hermes-kubelab" in first
    assert "NOT running" in first


def test_the_digest_never_goes_quiet(tmp_path: Path) -> None:
    """A no-agent job with empty stdout sends nothing, which on a dead stack would
    read as a quiet day."""
    out = _report(None, containers=None, tmp=tmp_path)
    assert out.strip()
    assert "docker" in out.lower(), "an unreachable Docker is said, not skipped"
    assert "no usage" in out.lower(), "a missing database is said, not skipped"


def test_only_the_current_month_counts(tmp_path: Path) -> None:
    rows = [
        _row("qwen3.6", "custom", 4, 1_000, 10, seen=MONTH_START + 3600),
        _row("old-model", "custom", 9, 999_999, 99, seen=MONTH_START - 3600),
    ]
    out = _report(_usage_db(tmp_path, rows))
    assert "old-model" not in out
    assert "999,999" not in out


def test_usage_is_summed_per_model_and_provider(tmp_path: Path) -> None:
    rows = [
        _row("qwen3.6", "custom", 4, 1_000, 10),
        _row("qwen3.6", "custom", 6, 2_000, 20),
        _row("claude-haiku-5-5", "anthropic", 2, 500, 50, cost=0.01),
    ]
    out = _report(_usage_db(tmp_path, rows))
    assert "3,000" in out, "the two qwen rows are one line"
    assert out.count("qwen3.6") == 1


def test_the_fallback_spend_is_its_own_line_in_dollars(tmp_path: Path) -> None:
    """The fallback is capped at 20 USD in the provider (spec AI-012 AC2): the digest
    shows the spend that eats that cap, whatever the model's name."""
    rows = [
        _row("claude-haiku-5-5", "anthropic", 2, 500, 50, cost=0.0123),
        _row("claude-sonnet-5-5", "anthropic", 1, 100, 10, cost=0.0200),
        _row("qwen3.6", "custom", 4, 1_000, 10),
    ]
    out = _report(_usage_db(tmp_path, rows))
    line = next(line for line in out.splitlines() if "fallback" in line.lower())
    assert "0.03" in line


def test_a_session_with_no_cost_recorded_does_not_crash_the_sum(tmp_path: Path) -> None:
    path = _usage_db(tmp_path, [_row("m", "anthropic", 1, 1, 1)])
    db = sqlite3.connect(path)
    db.execute("UPDATE session_model_usage SET estimated_cost_usd = NULL, actual_cost_usd = NULL")
    db.commit()
    db.close()
    assert "m" in _report(path)


@pytest.mark.parametrize(("free", "warned"), [(40, False), (10, True), (2, True)])
def test_a_filling_disk_is_flagged(tmp_path: Path, free: int, warned: bool) -> None:
    out = _report(_usage_db(tmp_path, []), disk=(100 * GB, free * GB))
    assert ("low" in out.lower()) is warned


def test_the_report_fits_a_slack_message(tmp_path: Path) -> None:
    rows = [_row(f"model-{i}", "custom", 1, 1, 1) for i in range(60)]
    assert len(_report(_usage_db(tmp_path, rows))) < 3500


def test_the_database_is_opened_read_only(tmp_path: Path) -> None:
    path = _usage_db(tmp_path, [])
    db = _digest()._connect(path)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        db.execute("DELETE FROM session_model_usage")
    db.close()


# --------------------------------------------------------------------------- the declaration


def _hermes() -> dict:
    return yaml.safe_load(COMMON.read_text())["apps"]["services"]["ai"]["hermes_kubelab"]


def test_the_digest_job_is_a_script_job_with_no_agent_and_runs_in_the_morning() -> None:
    job = _hermes()["cron"]["jobs"]["digest"]
    assert job["mode"] == "script"
    assert job["script"] == "daily-digest.py"
    minute, hour, *_ = job["schedule"].split()
    assert minute.isdigit()
    # Cron runs in UTC; the operator is in Denver (UTC-6 or -7).
    assert 13 <= int(hour) <= 16, "read over breakfast in Denver, not at 2 AM"


# --------------------------------------------------------------------------- memory capture


def test_the_gateways_memories_are_the_zones_memories_directory() -> None:
    """The host user that syncs the zone cannot read the gateway's data directory
    (0700, a subuid), so the memories are written where it can: the zone's own
    `memories/`, mounted over the data directory's. The sync then commits them with
    nothing else changed, and no new privilege is given to the user that holds the
    vault token."""
    compose = (ROLE / "templates/compose-hermes.yml.j2").read_text()
    wanted = (
        "{{ agent_stack_vault_clone }}/{{ agent_stack_vault_zone }}/memories:{{ agent_stack_hermes_home }}/memories"
    )
    assert wanted in compose
    before = compose.split(wanted)[0]
    opened = before.rfind("{% if")
    assert opened != -1 and "{% endif" not in before[opened:], "the mount sits inside a condition"
    assert "agent_stack_vault_configured" in before[opened:], "and the condition is that the vault is configured"


def test_the_memories_directory_exists_before_the_gateway_mounts_it() -> None:
    """A missing source is created by Docker, owned by root, and the gateway could not write it."""
    zone = (ROLE / "tasks/vault_zone.yml").read_text()
    tasks = yaml.safe_load(zone)

    def flat(items: list[dict]) -> list[dict]:
        out = []
        for t in items:
            out.append(t)
            out.extend(flat(t.get("block", [])))
        return out

    [task] = [t for t in flat(tasks) if "memories" in str(t.get("ansible.builtin.file", {}).get("path", ""))]
    assert task["ansible.builtin.file"]["state"] == "directory"
    assert task["ansible.builtin.file"]["mode"] in ("0777", "01777"), "the gateway's user is not the clone's owner"


def test_the_scripts_cleanup_refuses_to_run_on_an_empty_glob() -> None:
    """Remove what the role no longer ships, but never from a checkout that ships
    nothing: an empty glob would clear the node's scripts and every job would fail."""
    tasks = yaml.safe_load((ROLE / "tasks/hermes.yml").read_text())

    def flat(items: list[dict]) -> list[dict]:
        out = []
        for t in items:
            out.append(t)
            out.extend(flat(t.get("block", [])))
        return out

    ordered = flat(tasks)
    names = [t.get("name", "") for t in ordered]
    cleanup = names.index("Remove job scripts the role no longer ships")
    guards = [i for i, t in enumerate(ordered) if "ansible.builtin.assert" in t and "hermes-scripts" in str(t)]
    assert guards, "no assertion on the shipped scripts"
    assert guards[0] < cleanup, "the guard comes before the removal"


def test_the_sync_skips_the_gateways_unreadable_plumbing_in_the_memories(tmp_path: Path) -> None:
    """Hermes creates its lock files and the temporaries of an atomic write 0600 as a
    subuid the sync user cannot read, and git fails the whole add on one of them
    (seen on ace2: the zone, the session record included, stopped syncing). The sync
    leaves those out with a root-owned ignore file, passed as configuration like the
    rest: exclude pathspecs were tried first and, on git 2.43, stage nothing at all."""
    import os
    import re
    import shlex
    import subprocess

    template = (ROLE / "templates/vault-sync.sh.j2").read_text()
    assert "-c 'core.excludesFile={{ agent_stack_vault_ignore }}'" in template
    assert ":(exclude" not in re.sub(r"^#.*$", "", template, flags=re.MULTILINE), "no exclude pathspec in the sync"
    [line] = re.findall(r"^vgit add --all -- .*$", template, re.MULTILINE)
    args = shlex.split(line.replace("$zone", "zone"))[1:]

    tasks = yaml.safe_load((ROLE / "tasks/vault_zone.yml").read_text())
    [task] = [t for t in tasks if t.get("name") == "Install the vault sync's ignore file"]
    assert task["ansible.builtin.copy"]["owner"] == "root", "the agent's user cannot edit what it is judged by"
    patterns = [
        entry for entry in task["ansible.builtin.copy"]["content"].splitlines() if entry and not entry.startswith("#")
    ]
    ignore = tmp_path / "vault-ignore"
    assert patterns and all("/memories/" in entry for entry in patterns), "anchored to the memories, not the clone"
    ignore.write_text("\n".join(patterns).replace("{{ agent_stack_vault_zone }}", "zone") + "\n")

    repo = tmp_path / "clone"
    memories = repo / "zone" / "memories"
    memories.mkdir(parents=True)
    (memories / "MEMORY.md").write_text("a fact\n")
    for name in ("MEMORY.md.lock", ".mem_abc123"):
        (memories / name).write_text("")
        (memories / name).chmod(0o000)
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), "-c", f"core.excludesFile={ignore}", *args],
            capture_output=True,
            text=True,
            env=env,
        )
        staged = subprocess.run(
            ["git", "-C", str(repo), "diff", "--cached", "--name-only"], capture_output=True, text=True, env=env
        ).stdout.split()
    finally:
        for name in ("MEMORY.md.lock", ".mem_abc123"):
            (memories / name).chmod(0o600)
    if os.geteuid() == 0:
        pytest.skip("root reads a 0000 file, so the failure cannot be reproduced")
    assert done.returncode == 0, done.stderr
    assert staged == ["zone/memories/MEMORY.md"]
