"""The Gitea Renovate run's repository list is derived, never hand-listed (IDP-036 AC1).

`apps.services.core.gitea.organizations` already declares every repository the
forge holds; the reconciler creates them from it (TOOL-035). A second list in the
Renovate config would drift the first time a repository is declared and the
config is not edited, and the symptom would be silence: a repository Renovate
never opens a PR on looks exactly like one with nothing to update.

The expected set comes from `gitea_repos.load_declaration`, the same reader the
reconciler uses, so this test cannot agree with the template by re-implementing
the SSOT walk the same wrong way.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from jinja2 import StrictUndefined

from tests.ansible_jinja import ansible_env
from toolkit.features.gitea_repos import load_declaration

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/beelink_services"
PLAYBOOK = REPO / "infra/ansible/playbooks/provision-bee.yml"
TEMPLATE = "renovate-config.yaml.j2"

COMMON = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text(encoding="utf-8"))
ORGANIZATIONS = COMMON["apps"]["services"]["core"]["gitea"]["organizations"]


def _render(organizations: dict) -> str:
    env = ansible_env(str(ROLE / "templates"), undefined=StrictUndefined)
    return env.get_template(TEMPLATE).render(
        ansible_managed="Ansible managed",
        renovate_gitea_organizations=organizations,
    )


def _repositories(organizations: dict) -> list[str]:
    return yaml.safe_load(_render(organizations))["repositories"]


def _declared(common: dict) -> set[str]:
    return {f"{org}/{spec.name}" for org, specs in load_declaration(common).items() for spec in specs}


def test_rendered_repositories_equal_the_declaration() -> None:
    # Non-empty first: with nothing declared, both sides are the empty set and the
    # equality holds in exactly the state this test exists to catch.
    declared = _declared(COMMON)
    assert declared, "apps.services.core.gitea.organizations declares no repositories"
    assert set(_repositories(ORGANIZATIONS)) == declared


def test_no_repository_is_listed_twice() -> None:
    rendered = _repositories(ORGANIZATIONS)
    assert len(rendered) == len(set(rendered))


def test_render_is_byte_identical_across_runs() -> None:
    """A reordered list is a changed file, and a changed file is `changed=1` on every provision."""
    assert _render(ORGANIZATIONS) == _render(dict(reversed(list(ORGANIZATIONS.items()))))


def test_an_organization_with_no_repositories_contributes_nothing() -> None:
    organizations = {"empty": {"repositories": []}, "nulled": {"repositories": None}, "bare": None}
    assert _repositories(organizations) == []


def test_a_newly_declared_repository_is_covered_without_editing_the_role() -> None:
    organizations = {**ORGANIZATIONS, "neworg": {"repositories": [{"name": "fresh", "origin": "native"}]}}
    assert "neworg/fresh" in _repositories(organizations)


def test_the_playbook_passes_the_ssot_not_a_list() -> None:
    """The role var must be the declaration itself; a literal list there is the drift this test exists for."""
    plays = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    values = [
        role["vars"]["renovate_gitea_organizations"]
        for play in plays
        for role in play.get("roles", [])
        if isinstance(role, dict) and "beelink_services" in str(role.get("role")) and "vars" in role
    ]
    assert values == ["{{ gitea_config.apps.services.core.gitea.organizations }}"]
