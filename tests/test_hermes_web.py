"""Spec AI-024: the gateway's web tools, and only the gateway's.

`web_search` and `web_extract` run in the gateway process. The sandbox keeps no
network (ADR-068 D2), so nothing about the key may reach it.
"""

from __future__ import annotations

import re

import yaml

from tests.test_agent_stack_role import COMMON, _environment, _resolved
from toolkit.features.secrets_manager import SECRET_CATALOG

KEY = "apps.services.ai.hermes_kubelab.tavily_api_key"
CONFIG = yaml.safe_load(COMMON.read_text())["apps"]["services"]["ai"]["hermes_kubelab"]["agent_config"]


def _env_text(**overrides: object) -> str:
    env = _environment()
    return env.get_template("hermes.env.j2").render(**_resolved(env, **overrides))


def _rendered_config(**overrides: object) -> dict:
    env = _environment()
    return yaml.safe_load(env.get_template("hermes-config.yaml.j2").render(**_resolved(env, **overrides)))


def test_the_key_is_catalogued_for_prod_with_its_shape() -> None:
    spec = next(s for s in SECRET_CATALOG if s.key_path == KEY)
    assert spec.envs == ("prod",)
    assert re.fullmatch(spec.value_pattern, "tvly-dev-AbC_123-x")
    assert not re.fullmatch(spec.value_pattern, "sk-ant-nope")


def test_the_gateway_gets_the_key_only_when_there_is_one() -> None:
    assert "TAVILY_API_KEY=tvly-sentinel" in _env_text(agent_stack_tavily_api_key="tvly-sentinel")
    assert "TAVILY_API_KEY" not in _env_text(agent_stack_tavily_api_key="")


def test_the_sandbox_is_given_no_environment_and_no_network() -> None:
    terminal = _rendered_config(agent_stack_tavily_api_key="tvly-sentinel")["terminal"]
    assert terminal["docker_forward_env"] == []
    assert terminal["docker_network"] is False
    assert "tvly-sentinel" not in yaml.safe_dump(terminal)


def test_the_backend_is_pinned_and_a_turn_cannot_spend_the_month() -> None:
    config = _rendered_config(agent_stack_tavily_api_key="tvly-sentinel")
    assert config["web"]["backend"] == "tavily"
    assert config["web"]["keyless_rescue"] is False, "a failed call must not send the query to four anonymous vendors"
    assert 0 < config["tool_loop_guardrails"]["loop_caps"]["max_web_searches"] <= 20
    assert CONFIG["web"]["backend"] == "tavily"
