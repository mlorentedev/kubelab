"""A provision does not move the Beelink's CI engine as a side effect (#2722).

`base_system` runs `apt upgrade: dist` on every `make provision`. On 2026-10-27
one such run moved `docker-ce` from 29.8.1 to 29.9.2 on the Beelink as a side
effect. The maintenance timer already holds Docker for its own run; nothing held
it across a provision. The engine moves on purpose now, whether or not that
upgrade broke anything: the hang suspected of it was a slow pull (#2722).

So `base_system` holds a node's declared packages before its upgrade, and
releases them only for a run that asks to (`base_system_release_holds=true`),
holding them again after.
"""

from __future__ import annotations

from pathlib import Path

import jinja2
import pytest
import yaml

from tests.ansible_jinja import _to_bool
from tests.test_node_maintenance_patching import _run_hold_block

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "infra/ansible/roles/base_system"
BEE = REPO / "infra/ansible/playbooks/provision-bee.yml"
MAINTENANCE_DEFAULTS = REPO / "infra/ansible/roles/node_maintenance/defaults/main.yml"
CI_ENGINE = ["docker-ce", "docker-ce-cli", "containerd.io"]


def _load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _tasks() -> list[dict]:
    return _load(ROLE / "tasks/main.yml")


def _index(predicate) -> list[int]:
    return [i for i, task in enumerate(_tasks()) if predicate(task)]


def _upgrades(task: dict) -> bool:
    """The upgrade runs through the include that sizes it against the edge (#2809)."""
    return "_includes/apt-upgrade.yml" in str(task.get("ansible.builtin.import_tasks", ""))


def _sets_holds(task: dict) -> bool:
    return "dpkg_selections" in task and "base_system_held_packages" in str(task.get("loop", ""))


def _env() -> jinja2.Environment:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["bool"] = _to_bool
    return env


def _selection(task: dict, release: bool) -> str:
    return _env().from_string(task["dpkg_selections"]["selection"]).render(base_system_release_holds=release)


def _runs(task: dict, release: bool) -> bool:
    conditions = task.get("when", [])
    conditions = conditions if isinstance(conditions, list) else [conditions]
    return all(
        _to_bool(_env().from_string("{{ " + c + " }}").render(base_system_release_holds=release, legacy_python=False))
        for c in conditions
    )


def _applied(release: bool) -> list[str]:
    """The selections a run applies, in order: the task's `when` decides as much as its value."""
    return [_selection(t, release) for t in _tasks() if _sets_holds(t) and _runs(t, release)]


def test_no_node_holds_anything_unless_its_play_says_so() -> None:
    defaults = _load(ROLE / "defaults/main.yml")
    assert defaults["base_system_held_packages"] == []
    assert defaults["base_system_release_holds"] is False


def test_the_holds_are_set_before_the_upgrade_and_again_after() -> None:
    [upgrade] = _index(_upgrades)
    holds = _index(_sets_holds)
    assert any(i < upgrade for i in holds), "nothing holds the packages before the upgrade runs"
    assert any(i > upgrade for i in holds), "nothing holds them again after a released run"


def test_a_run_releases_them_only_when_asked() -> None:
    [upgrade] = _index(_upgrades)
    before = [_tasks()[i] for i in _index(_sets_holds) if i < upgrade]
    assert [_selection(t, release=False) for t in before] == ["hold"]
    assert [_selection(t, release=True) for t in before] == ["install"]


@pytest.mark.parametrize(("release", "applied"), [(False, ["hold"]), (True, ["install", "hold"])])
def test_every_run_ends_with_the_packages_held(release: bool, applied: list[str]) -> None:
    """A released run must not end unheld: the routine provision after it would upgrade them."""
    assert _applied(release) == applied


def test_only_an_installed_package_is_held() -> None:
    """dpkg_selections fails on a name dpkg has never seen: a first provision, before Docker is installed."""
    [facts] = _index(lambda t: "package_facts" in t)
    for i in _index(_sets_holds):
        assert facts < i
        assert "ansible_facts.packages" in _tasks()[i]["loop"], _tasks()[i]["name"]


def _bee_base_system_vars() -> dict:
    [play] = [p for p in _load(BEE) if "roles" in p]
    [role] = [r for r in play["roles"] if str(r.get("role", "")).endswith("/base_system")]
    return role.get("vars", {})


def test_the_beelink_holds_its_ci_engine() -> None:
    assert _bee_base_system_vars().get("base_system_held_packages") == CI_ENGINE


def test_the_maintenance_timer_finds_them_held_and_leaves_them_held(tmp_path: Path) -> None:
    """It releases only the holds it created (pinned in test_node_maintenance_patching), and it creates none here."""
    blacklist = _load(MAINTENANCE_DEFAULTS)["maintenance_patch_blacklist"]
    assert set(CI_ENGINE) <= set(blacklist), "the timer no longer holds the CI engine for its own run"
    unprotected, held_by_timer = _run_hold_block(
        tmp_path, fail_hold=[], states=dict.fromkeys(CI_ENGINE, "installed"), held_before=tuple(CI_ENGINE)
    )
    assert not unprotected
    assert not held_by_timer & set(CI_ENGINE), f"the timer would release the provision's holds: {held_by_timer}"
