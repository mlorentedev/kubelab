"""hermes-kubelab's fallback model (spec AI-012 AC2).

When NaN fails (429 after retries, 5xx, 401/403, 404), Hermes swaps
an unpinned session to the next `fallback_providers` entry mid-turn. The entry
is Anthropic's Haiku on its own key, in a workspace the operator capped at 20
USD a month. Without the key the chain is empty, never an entry Hermes cannot
authenticate.
"""

from __future__ import annotations

import pytest
import yaml

from tests.test_agent_stack_role import COMMON, ROLE, _environment, _resolved
from toolkit.features.secrets_manager import SECRET_CATALOG

HERMES = yaml.safe_load(COMMON.read_text())["apps"]["services"]["ai"]["hermes_kubelab"]
KEY = {"agent_stack_anthropic_api_key": "sk-ant-sentinel"}


def _render(name: str, **overrides: object) -> str:
    env = _environment()
    return env.get_template(name).render(**_resolved(env, **overrides))


def _env(**overrides: object) -> dict[str, str]:
    lines = _render("hermes.env.j2", **overrides).splitlines()
    return dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))


def _config(**overrides: object) -> dict:
    return yaml.safe_load(_render("hermes-config.yaml.j2", **overrides))


def test_the_fallback_is_the_ssots_model_on_anthropic() -> None:
    assert _config(**KEY)["fallback_providers"] == [{"provider": "anthropic", "model": HERMES["models"]["fallback"]}]


def test_without_the_key_there_is_no_fallback_hermes_cannot_authenticate() -> None:
    assert not _config().get("fallback_providers")
    assert "ANTHROPIC_API_KEY" not in _env()


def test_the_key_reaches_the_env_file_only() -> None:
    assert _env(**KEY)["ANTHROPIC_API_KEY"] == KEY["agent_stack_anthropic_api_key"]
    for name in ("hermes-config.yaml.j2", "compose-hermes.yml.j2"):
        assert KEY["agent_stack_anthropic_api_key"] not in _render(name, **KEY), name


def test_delegated_work_never_borrows_the_metered_chain() -> None:
    """ADR-068 D7. A child pinned by model gets no fallback unless one is declared
    for it (`scoped_fallback_chain`, unchanged in v0.22.1), so the pin is what keeps it off."""
    delegation = _config(**KEY)["delegation"]
    assert delegation["model"] == HERMES["models"]["unmetered"]
    assert "fallback_providers" not in delegation


@pytest.mark.parametrize("ported", [{"fallback_providers": [{"provider": "openrouter", "model": "x"}]}])
def test_the_ported_keys_cannot_set_the_chain(ported: dict) -> None:
    hermes = _resolved(_environment())["agent_stack_hermes"]
    config = _config(**KEY, agent_stack_hermes={**hermes, "agent_config": {**hermes["agent_config"], **ported}})
    assert config["fallback_providers"] == [{"provider": "anthropic", "model": HERMES["models"]["fallback"]}]


def test_the_playbook_reads_the_key_from_prods_vault() -> None:
    playbook = (ROLE.parents[1] / "playbooks/provision-ace2.yml").read_text()
    assert (
        "agent_stack_anthropic_api_key: \"{{ gitea_secrets.apps.services.ai.hermes_kubelab.anthropic_api_key"
        " | default('') }}\"" in playbook
    )


def test_the_key_is_in_the_catalog_for_prod() -> None:
    [spec] = [s for s in SECRET_CATALOG if s.key_path == "apps.services.ai.hermes_kubelab.anthropic_api_key"]
    assert spec.envs == ("prod",)
    assert "hermes_kubelab" in spec.services
