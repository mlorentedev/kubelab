"""The Gitea Renovate run extends the shared preset at ONE pinned tag (IDP-036 AC3).

The tag is declared once, at `ci.renovate.preset_tag` in common.yaml, and a regex
manager in renovate.json bumps it like any other dependency. The role carries no
tag of its own: a literal there is a second pin nothing bumps, and the Gitea run
would sit on an old preset while every check stays green.

A regex manager fails by silence (see test_renovate_image_coverage.py): a pattern
that matches nothing reports no dependency and no error. So the manager is run
against common.yaml here, and must find exactly the declared tag.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from jinja2 import StrictUndefined

from tests.ansible_jinja import ansible_env

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/beelink_services"
PLAYBOOK = REPO / "infra/ansible/playbooks/provision-bee.yml"
COMMON_PATH = REPO / "infra/config/values/common.yaml"
TEMPLATE = "renovate-config.yaml.j2"

COMMON = yaml.safe_load(COMMON_PATH.read_text(encoding="utf-8"))
TAG = COMMON["ci"]["renovate"]["preset_tag"]
PRESET_REPO = "mlorentedev/ci-workflows"


def _rendered(tag: str = TAG) -> dict:
    env = ansible_env(str(ROLE / "templates"), undefined=StrictUndefined)
    text = env.get_template(TEMPLATE).render(
        ansible_managed="Ansible managed",
        renovate_gitea_organizations=COMMON["apps"]["services"]["core"]["gitea"]["organizations"],
        renovate_preset_tag=tag,
    )
    return yaml.safe_load(text)


def _manager() -> dict:
    managers = [
        m
        for m in json.loads((REPO / "renovate.json").read_text(encoding="utf-8"))["customManagers"]
        if m.get("depNameTemplate") == PRESET_REPO
    ]
    assert len(managers) == 1, f"expected one custom manager for {PRESET_REPO}, found {len(managers)}"
    return managers[0]


def _python_pattern(raw: str) -> re.Pattern[str]:
    """RE2's `(?<name>)` is Python's `(?P<name>)`; converted for the test only."""
    return re.compile(re.sub(r"\(\?<([a-zA-Z]\w*)>", r"(?P<\1>", raw))


def test_the_declared_tag_is_a_release_tag() -> None:
    assert re.fullmatch(r"v\d+\.\d+\.\d+", TAG), f"ci.renovate.preset_tag is {TAG!r}, not a vX.Y.Z tag"


def test_the_config_extends_the_preset_at_the_declared_tag() -> None:
    assert _rendered()["extends"] == [f"github>{PRESET_REPO}//renovate/default#{TAG}"]


def test_the_tag_reaches_the_config_from_the_variable_not_a_literal() -> None:
    assert _rendered("v9.9.9")["extends"] == [f"github>{PRESET_REPO}//renovate/default#v9.9.9"]


def test_repositories_are_processed_without_a_config_file_or_onboarding() -> None:
    """Renovate documents this pair as 'processed regardless of config file presence'."""
    config = _rendered()
    assert config["onboarding"] is False
    assert config["requireConfig"] == "optional"


def test_the_role_holds_no_preset_tag_of_its_own() -> None:
    offenders = [
        str(path.relative_to(REPO))
        for path in sorted(ROLE.rglob("*"))
        if path.is_file() and re.search(r"ci-workflows\S*#v\d", path.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert not offenders, f"a literal ci-workflows tag in the role: {offenders}"


def test_the_playbook_passes_the_declared_tag() -> None:
    plays = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    values = [
        role["vars"]["renovate_preset_tag"]
        for play in plays
        for role in play.get("roles", [])
        if isinstance(role, dict) and "beelink_services" in str(role.get("role")) and "vars" in role
    ]
    assert values == ["{{ gitea_config.ci.renovate.preset_tag }}"]


def test_the_manager_tracks_the_preset_repository_by_its_tags() -> None:
    manager = _manager()
    assert manager["datasourceTemplate"] == "github-tags"
    assert manager["managerFilePatterns"] == ["/^infra/config/values/common\\.yaml$/"]


def test_the_manager_finds_exactly_the_declared_tag() -> None:
    """The vacuity check: a pattern that matched nothing would leave the pin frozen, silently."""
    text = COMMON_PATH.read_text(encoding="utf-8")
    found = [
        match.group("currentValue")
        for raw in _manager()["matchStrings"]
        for match in _python_pattern(raw).finditer(text)
    ]
    assert found == [TAG]
