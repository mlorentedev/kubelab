"""`make backup-repo-reinit`: the one sanctioned way to start a history over (BACKUP-058).

Since BACKUP-058 a node refuses to re-initialise a repository it has shipped to
before. A guard with no documented override gets bypassed by hand: someone
deletes the marker over SSH, and the reason is lost with the shell session. So
the override is a target, and these tests pin what makes it deliberate and
recorded rather than just possible:

- it takes exactly one node: `NODE=all` is refused by the target, and a host
  pattern that still matches several hosts is refused by the playbook;
- `DEST` must name a declared destination, so no path is ever built from input;
- it reads the recorded id and writes it to the node's journal BEFORE removing
  the marker;
- an unreachable node FAILS, unlike `backup-node.yml`: the operator must know
  the override did not happen;
- the marker path comes from the role's own defaults, never a second copy.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
PLAYBOOK = REPO / "infra/ansible/playbooks/backup-repo-reinit.yml"
DEFAULTS = REPO / "infra/ansible/roles/node_backup/defaults/main.yml"
MAKEFILE = REPO / "Makefile"


def _play() -> dict:
    plays = yaml.safe_load(PLAYBOOK.read_text())
    assert len(plays) == 1, "one play"
    return plays[0]


def _tasks() -> list[dict]:
    return _play()["tasks"]


def _recipe() -> str:
    text = MAKEFILE.read_text()
    m = re.search(r"^backup-repo-reinit:.*?(?=^\S|\Z)", text, re.S | re.M)
    assert m, "Makefile has no backup-repo-reinit target"
    return m.group(0)


def _index(predicate) -> int:
    return next(i for i, t in enumerate(_tasks()) if predicate(t))


def _assert_on(needle: str):
    """Match an assert by its `that:` conditions, never by its serialised task.

    A `fail_msg` can name another assert's variable, so a search over the whole
    task could locate the wrong one and let an ordering swap pass.
    """
    return lambda t: any(needle in cond for cond in (t.get("ansible.builtin.assert") or {}).get("that", []))


def test_the_marker_path_comes_from_the_role_defaults() -> None:
    play = _play()
    assert "../roles/node_backup/defaults/main.yml" in play.get("vars_files", [])
    destinations = play["vars"]["reinit_destinations"]
    defaults = yaml.safe_load(DEFAULTS.read_text())
    for dest, path in destinations.items():
        var = f"node_backup_{dest}_repository_id_file"
        assert var in defaults, f"{dest}: the role declares no {var}"
        assert path == "{{ " + var + " }}", f"{dest}: the playbook must reference {var}, not restate a path"


def test_an_unreachable_node_fails_instead_of_being_skipped() -> None:
    # Explicit `false`, not an absent key: absence would pass for a play whose
    # behaviour is decided somewhere this test cannot see.
    assert _play().get("ignore_unreachable") is False


def test_the_destination_is_validated_against_a_declared_list() -> None:
    i = _index(_assert_on("reinit_destinations"))
    assert "r2" in _play()["vars"]["reinit_destinations"]
    remove = _index(lambda t: t.get("ansible.builtin.file", {}).get("state") == "absent")
    assert i < remove


def test_exactly_one_host_may_match() -> None:
    i = _index(_assert_on("ansible_play_hosts_all"))
    remove = _index(lambda t: t.get("ansible.builtin.file", {}).get("state") == "absent")
    assert i < remove


def test_the_recorded_id_is_journaled_before_the_marker_is_removed() -> None:
    read = _index(lambda t: "ansible.builtin.slurp" in t)
    journal = _index(lambda t: "logger" in str(t.get("ansible.builtin.command", "")))
    remove = _index(lambda t: t.get("ansible.builtin.file", {}).get("state") == "absent")
    assert read < journal < remove


def test_the_target_refuses_a_missing_node_all_nodes_a_missing_dest_and_a_non_fleet_env() -> None:
    recipe = _recipe()
    assert '-n "$(NODE)"' in recipe
    assert '-n "$(DEST)"' in recipe
    assert '"$(NODE)" != "all"' in recipe
    # ENV defaults to `dev` in the Makefile: a presence check would never fire.
    assert '"$(ENV)" = staging -o "$(ENV)" = prod' in recipe
    assert "-p backup-repo-reinit" in recipe
    assert "-l $(NODE)" in recipe
    assert "--extra-vars dest=$(DEST)" in recipe
    assert "$(_CHECK)" in recipe
