"""A token minted but never recorded must not stop the role from converging.

Each machine credential is two tasks: mint a named token in the container, then
record it in SOPS from the controller. Both are gated on the SOPS key being empty.
When the record fails after the mint succeeded, the token exists in Gitea, its value
is gone (`no_log`, and the register dies with the play), and the next run mints the
same name again, which Gitea refuses. The role then never converges without a manual
delete on the node. Measured 2026-11-01: the controller had no in-project `.venv`, so
`Record the issue-reader token in SOPS` failed after its mint had run.

The role converges by itself when (a) it revokes, before minting, a token of that
name that SOPS does not know, with the admin password already reasserted, since
Gitea's token endpoints take Basic Auth only, and (b) it refuses to mint at all
when the controller cannot record the result.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
TASKS = REPO / "infra/ansible/roles/beelink_services/tasks/main.yml"


def _tasks() -> list[dict]:
    return yaml.safe_load(TASKS.read_text(encoding="utf-8"))


def _index(name: str) -> int:
    for i, task in enumerate(_tasks()):
        if task.get("name") == name:
            return i
    raise AssertionError(f"no task named {name!r} in {TASKS.name}")


def _mints() -> dict[int, str]:
    """Position -> token name, for every task that runs generate-access-token."""
    found = {}
    for i, task in enumerate(_tasks()):
        argv = (task.get("command") or {}).get("argv") if isinstance(task.get("command"), dict) else None
        script = " ".join(argv or [])
        if "generate-access-token" in script:
            found[i] = re.search(r"--token-name\s+(\S+)", script).group(1)
    return found


def _revoke() -> tuple[int, dict]:
    for i, task in enumerate(_tasks()):
        uri = task.get("uri") or {}
        if uri.get("method") == "DELETE" and "/tokens/" in str(uri.get("url", "")):
            return i, task
    raise AssertionError("no task revokes a token through the API before minting")


def test_every_mint_has_a_name() -> None:
    assert len(_mints()) >= 5, "the mint tasks were not found; the scan no longer matches the role"


def test_the_revoke_covers_every_minted_token_name() -> None:
    _, task = _revoke()
    covered = {item["name"] for item in task["loop"]}
    missing = set(_mints().values()) - covered
    assert not missing, f"minted but never revoked when unrecorded: {sorted(missing)}"


def test_the_revoke_runs_before_every_mint() -> None:
    position, _ = _revoke()
    assert all(position < mint for mint in _mints()), "a mint runs before the stale token is revoked"


def test_the_admin_password_is_reasserted_before_the_revoke() -> None:
    position, _ = _revoke()
    assert _index("Reassert the admin password from SOPS when it has drifted") < position, (
        "the revoke authenticates with the admin password, so a drifted one must be repaired first"
    )


def _mint_gates() -> dict[str, tuple[str, str]]:
    """Token name -> (SOPS variable gating its mint, account it is minted on)."""
    tasks = _tasks()
    gates = {}
    for i, name in _mints().items():
        script = " ".join(tasks[i]["command"]["argv"])
        var = re.search(r"\bnot (gitea_\w+_token)\b", str(tasks[i]["when"])).group(1)
        user = re.search(r"--username \{\{ (\w+) \}\}", script).group(1)
        gates[name] = (var, user)
    return gates


def test_each_revoke_reads_the_same_sops_value_and_account_as_its_mint() -> None:
    """A swapped variable would revoke one token on the evidence of another's key."""
    _, task = _revoke()
    gates = _mint_gates()
    for item in task["loop"]:
        var = re.fullmatch(r"\{\{ (gitea_\w+_token) \| length > 0 \}\}", item["recorded"]).group(1)
        user = re.fullmatch(r"\{\{ (\w+) \}\}", item["user"]).group(1)
        assert (var, user) == gates[item["name"]], f"{item['name']}: revoke reads {(var, user)}, mint {gates[item['name']]}"


def test_the_revoke_skips_a_recorded_token() -> None:
    """Inverted, the gate deletes every live credential and nothing re-mints it."""
    _, task = _revoke()
    assert "not item.recorded | bool" in str(task.get("when")), (
        "a recorded token would be revoked from under its consumer"
    )


def test_the_controller_can_record_before_anything_is_minted() -> None:
    preflight = _index("Assert the controller can record a minted token")
    assert all(preflight < mint for mint in _mints()), "a token can be minted that the controller cannot record"


def _records() -> list[dict]:
    """Every controller-side task that writes a minted credential to SOPS."""
    return [t for t in _tasks() if "toolkit secrets set" in str(t.get("command"))]


def test_the_preflight_checks_the_tool_the_record_tasks_run() -> None:
    checked = _tasks()[_index("Assert the controller can record a minted token")]["stat"]["path"]
    assert len(_records()) >= len(_mints()), "the record tasks were not found; the scan no longer matches the role"
    for task in _records():
        assert task["command"].startswith(f"{checked} "),f"{task['name']}: runs a tool the preflight never checked"


def test_the_preflight_runs_whenever_a_record_would() -> None:
    """Tied to the record gates, so a converged host, which records nothing, still passes."""
    when = str(_tasks()[_index("Assert the controller can record a minted token")].get("when"))
    for task in _records():
        var = re.search(r"\bnot (\w+_token)\b", str(task["when"])).group(1)
        assert f"not {var}" in when, f"{task['name']} can run while the preflight is skipped"
