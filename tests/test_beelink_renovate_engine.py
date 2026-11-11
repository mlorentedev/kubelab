"""The Gitea Renovate run's engine comes from ci-workflows' `engine.json` (IDP-036 AC4).

The engine image and version live once, in `renovate/engine.json` next to the shared
preset. The Gitea run reads them at the SAME tag its global config extends, so one
pin (`ci.renovate.preset_tag`) moves the preset and the engine together. kubelab
carries no engine version of its own: a literal would be a second pin that nothing
bumps, and the Gitea run would fall behind GitHub's while every check stayed green.

The engine is resolved when the node is provisioned, not when Renovate runs, so a
version reaches the node only through a provisioned PR. Its image joins the bounded
pull the Beelink uses for every image (#2742) with the unit that runs it (AC2).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from jinja2 import StrictUndefined

from tests.ansible_jinja import ansible_env

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/beelink_services"
PLAYBOOK = REPO / "infra/ansible/playbooks/provision-bee.yml"
ENGINE_URL = "https://raw.githubusercontent.com/mlorentedev/ci-workflows/{{ %s }}/renovate/engine.json"

(PLAY,) = [p for p in yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8")) if "roles" in p]


def _role_vars() -> dict:
    (role,) = [r for r in PLAY["roles"] if isinstance(r, dict) and "beelink_services" in str(r.get("role"))]
    return role["vars"]


def _engine_fetches() -> list[dict]:
    return [
        task
        for task in PLAY["pre_tasks"]
        if "engine.json" in str((task.get("ansible.builtin.uri") or task.get("uri") or {}).get("url", ""))
    ]


def _tag_expression() -> str:
    """The expression the global config's `extends` tag is read from."""
    match = re.fullmatch(r"\{\{\s*(.+?)\s*\}\}", _role_vars()["renovate_preset_tag"])
    assert match, _role_vars()["renovate_preset_tag"]
    return match.group(1)


def _render_env(engine: dict) -> str:
    env = ansible_env(str(ROLE / "templates"), undefined=StrictUndefined)
    return env.get_template("renovate.env.j2").render(ansible_managed="Ansible managed", renovate_engine=engine)


def test_the_play_fetches_the_engine_exactly_once() -> None:
    """A role with no fetch fails AC4: its engine would have to come from somewhere else."""
    assert len(_engine_fetches()) == 1


def test_the_engine_is_read_at_the_tag_the_config_extends() -> None:
    """Same expression as `renovate_preset_tag`, so preset and engine cannot drift apart."""
    (fetch,) = _engine_fetches()
    url = (fetch.get("ansible.builtin.uri") or fetch["uri"])["url"]
    assert url == ENGINE_URL % _tag_expression()


def test_the_fetch_runs_on_the_controller_under_every_tag_and_in_check_mode() -> None:
    (fetch,) = _engine_fetches()
    assert fetch["delegate_to"] == "localhost"
    assert fetch["become"] is False
    assert fetch["check_mode"] is False
    assert fetch["changed_when"] is False
    assert "always" in fetch["tags"]


def test_the_engine_shape_is_asserted_before_anything_reads_it() -> None:
    """A changed `engine.json` must fail the play, not render `None:None`."""
    names = [t.get("name") for t in PLAY["pre_tasks"]]
    (fetch,) = _engine_fetches()
    following = PLAY["pre_tasks"][names.index(fetch["name"]) + 1]
    body = following.get("ansible.builtin.assert") or following.get("assert")
    assert body, f"the task after the fetch is {following.get('name')!r}, not an assert"
    text = " ".join(body["that"])
    assert "image" in text and "version" in text and "regex" in text


def test_the_role_receives_the_fetched_engine_not_a_value() -> None:
    assert _role_vars()["renovate_engine"] == "{{ _renovate_engine.json }}"


def test_the_env_file_carries_the_fetched_image() -> None:
    assert "RENOVATE_IMAGE=example/renovate:1.2.3" in _render_env({"image": "example/renovate", "version": "1.2.3"})


def test_the_env_file_follows_the_engine_not_a_literal() -> None:
    assert "RENOVATE_IMAGE=other/renovate:9.9.9" in _render_env({"image": "other/renovate", "version": "9.9.9"})


def test_kubelab_carries_no_engine_version_of_its_own() -> None:
    pattern = re.compile(r"renovatebot/renovate:\d|renovate_version|RENOVATE_VERSION")
    files = [*ROLE.rglob("*"), PLAYBOOK, REPO / "infra/config/values/common.yaml"]
    offenders = [
        str(path.relative_to(REPO))
        for path in files
        if path.is_file() and pattern.search(path.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert not offenders, f"a Renovate engine version outside ci-workflows: {offenders}"
