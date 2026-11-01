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


def test_the_revoke_only_touches_unrecorded_tokens() -> None:
    _, task = _revoke()
    for item in task["loop"]:
        assert "recorded" in item, f"{item['name']}: the revoke must know which SOPS value gates it"
    assert "item.recorded" in str(task.get("when")), "a recorded token would be revoked from under its consumer"


def test_the_controller_can_record_before_anything_is_minted() -> None:
    preflight = _index("Assert the controller can record a minted token")
    assert all(preflight < mint for mint in _mints()), "a token can be minted that the controller cannot record"
