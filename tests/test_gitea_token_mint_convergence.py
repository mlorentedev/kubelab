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

import jinja2
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
    env = jinja2.Environment()
    env.filters["bool"] = lambda v: str(v).strip().lower() in {"true", "yes", "1", "on"}
    when = task.get("when")
    gate = env.compile_expression(" and ".join(f"({c})" for c in (when if isinstance(when, list) else [when])))
    # `recorded` reaches the gate as the string the loop item's template rendered.
    for user, recorded, revoke in [
        ("kubelab-reviewer", "False", True),
        ("kubelab-reviewer", "True", False),
        ("", "False", False),
        ("", "True", False),
    ]:
        held = ["kubelab-reviewer"]  # what the probe found: the gate below is about the SOPS key
        item = {"name": "kubelab-reviewer", "user": user, "recorded": recorded}
        assert bool(gate(item=item, _gitea_unrecorded_held=held)) is revoke, (
            f"user={user!r} recorded={recorded}: the gate answers {not revoke}, "
            + ("revoking a live credential" if recorded == "True" or not user else "leaving the orphan in place")
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


# --------------------------------------------------------------------------- #3428
# "Absent from SOPS" was read from the controller's working copy. A provision from
# another checkout, which had minted and recorded a token there and not merged it,
# was then revoked by the next provision from this one: two green runs, one dead
# credential. Revoking is irreversible, so an unrecorded token that Gitea holds now
# stops the play unless the operator says the value is lost.

PROBE = "Look for an unrecorded token Gitea already holds"
HELD = "Name the unrecorded tokens Gitea already holds"
REFUSE = "Refuse to revoke a token another checkout may have recorded"
OVERRIDE = "gitea_revoke_unrecorded_tokens"


def _env() -> jinja2.Environment:
    env = jinja2.Environment()
    env.filters["bool"] = lambda v: str(v).strip().lower() in {"true", "yes", "1", "on"}
    return env


def _gate(task: dict):
    when = task.get("when")
    return _env().compile_expression(" and ".join(f"({c})" for c in (when if isinstance(when, list) else [when])))


def test_the_probe_reads_the_same_accounts_as_the_revoke_before_it() -> None:
    probe = _tasks()[_index(PROBE)]
    position, revoke = _revoke()
    assert _index(PROBE) < _index(HELD) < _index(REFUSE) < position
    assert probe["uri"]["method"] == "GET"
    assert probe["uri"]["url"].endswith("/api/v1/users/{{ item.user }}/tokens?limit=50")
    assert probe["loop"] == revoke["loop"] and probe["when"] == revoke["when"][0]
    assert probe["check_mode"] is False  # a read: the dry run reports the refusal too
    assert probe["no_log"] is True  # the listing carries each token's last eight characters


def _held(results: list[dict]) -> list[str]:
    expression = _tasks()[_index(HELD)]["set_fact"]["_gitea_unrecorded_held"]
    rendered = _env().from_string(expression).render(_gitea_unrecorded_probe={"results": results})
    return yaml.safe_load(rendered)


def test_only_a_name_gitea_lists_counts_as_held() -> None:
    results = [
        {"item": {"name": "kubelab-repo-reader"}, "json": [{"name": "kubelab-repo-reader"}, {"name": "x"}]},
        {"item": {"name": "kubelab-agent"}, "json": [{"name": "other"}]},
        {"item": {"name": "kubelab-renovate"}, "skipped": True},
    ]
    assert _held(results) == ["kubelab-repo-reader"]
    assert _held([]) == []


def test_a_held_unrecorded_token_stops_the_play_unless_the_operator_says_it_is_lost() -> None:
    gate = _gate(_tasks()[_index(REFUSE)])
    assert gate(_gitea_unrecorded_held=["kubelab-repo-reader"], **{OVERRIDE: False})
    assert not gate(_gitea_unrecorded_held=["kubelab-repo-reader"], **{OVERRIDE: True})
    assert not gate(_gitea_unrecorded_held=[], **{OVERRIDE: False})
    msg = _tasks()[_index(REFUSE)]["fail"]["msg"]
    for part in ("ERROR", "WHY", "FIX", OVERRIDE):
        assert part in msg


def test_the_override_is_off_by_default() -> None:
    defaults = yaml.safe_load((TASKS.parent.parent / "defaults/main.yml").read_text(encoding="utf-8"))
    assert defaults[OVERRIDE] is False


def test_the_revoke_touches_only_what_the_probe_found_held() -> None:
    _, task = _revoke()
    gate = _gate(task)
    item = {"name": "kubelab-repo-reader", "user": "kubelab-reviewer", "recorded": "False"}
    assert gate(item=item, _gitea_unrecorded_held=["kubelab-repo-reader"])
    assert not gate(item=item, _gitea_unrecorded_held=[])
