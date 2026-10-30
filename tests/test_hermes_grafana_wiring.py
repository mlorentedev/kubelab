"""Spec AI-024 stage 2 (PR 2b): the cluster-state reader reaches the gateway, and only the gateway.

The script's own behaviour is `test_hermes_grafana.py`. What is held here is the wiring: the token
enters one env file and one MCP server's `env`, the server is read-only inside the container, the
model can call exactly the four declared tools, and a node without the token declares nothing.
"""

from __future__ import annotations

import re

import yaml

from tests.test_agent_stack_role import COMMON, ROLE, _environment, _resolved
from toolkit.features.secrets_manager import SECRET_CATALOG

KEY = "apps.services.ai.hermes_kubelab.grafana_token"
TOKEN = "glsa_" + "wiring" + "_" + "0123456789"  # assembled, so a scanner sees no credential
HERMES = yaml.safe_load(COMMON.read_text(encoding="utf-8"))["apps"]["services"]["ai"]["hermes_kubelab"]
SCRIPT_TOOLS = {"firing_alerts", "errors_by_app", "log_volume_by_app", "recent_errors"}


def _render(template: str, **overrides: object) -> str:
    env = _environment()
    return env.get_template(template).render(**_resolved(env, **overrides))


def _config(**overrides: object) -> dict:
    return yaml.safe_load(_render("hermes-config.yaml.j2", **overrides))


def test_the_token_is_the_catalogued_viewer_token_for_prod() -> None:
    spec = next(s for s in SECRET_CATALOG if s.key_path == KEY)
    assert spec.envs == ("prod",)
    assert re.fullmatch(spec.value_pattern, TOKEN)


def test_a_node_without_the_token_declares_no_server_and_no_variable() -> None:
    assert "mcp_servers" not in _config(agent_stack_grafana_token="")
    assert "GRAFANA_TOKEN" not in _render("hermes.env.j2", agent_stack_grafana_token="")


def test_the_token_enters_the_env_file_and_one_server() -> None:
    assert f"GRAFANA_TOKEN={TOKEN}" in _render("hermes.env.j2", agent_stack_grafana_token=TOKEN)
    server = _config(agent_stack_grafana_token=TOKEN)["mcp_servers"]["grafana"]
    assert server["env"]["GRAFANA_TOKEN"] == "${GRAFANA_TOKEN}", "a reference, never the value"
    assert TOKEN not in _render("hermes-config.yaml.j2", agent_stack_grafana_token=TOKEN)


def test_the_token_is_named_only_where_it_must_be() -> None:
    allowed = {
        "templates/hermes.env.j2",
        "templates/hermes-config.yaml.j2",
        "defaults/main.yml",
        "files/hermes-mcp/grafana-reader.py",
    }
    mentions = {
        str(path.relative_to(ROLE))
        for path in ROLE.rglob("*")
        if path.is_file()
        and re.search("agent_stack_grafana_token|GRAFANA_TOKEN", path.read_text(errors="ignore", encoding="utf-8"))
    }
    assert mentions == allowed
    terminal = _config(agent_stack_grafana_token=TOKEN)["terminal"]
    assert terminal["docker_forward_env"] == [] and terminal["docker_network"] is False


def test_the_model_can_call_exactly_the_tools_the_script_serves() -> None:
    server = _config(agent_stack_grafana_token=TOKEN)["mcp_servers"]["grafana"]
    assert set(server["tools"]["include"]) == SCRIPT_TOOLS
    source = (ROLE / "files/hermes-mcp/grafana-reader.py").read_text(encoding="utf-8")
    assert all(f'"{name}"' in source or f"{name}:" in source for name in SCRIPT_TOOLS)


def test_the_apps_and_url_come_from_the_ssot() -> None:
    server = _config(agent_stack_grafana_token=TOKEN)["mcp_servers"]["grafana"]
    reader = HERMES["grafana_reader"]
    assert server["env"]["GRAFANA_URL"] == reader["url"]
    assert server["env"]["HERMES_GRAFANA_APPS"] == ",".join(reader["apps"])
    assert reader["apps"] and reader["url"].startswith("https://")


def test_the_server_directory_is_read_only_inside_the_gateway() -> None:
    compose = _render("compose-hermes.yml.j2")
    assert re.search(r"hermes-mcp:\S+/mcp:ro\b", compose)
    server = _config(agent_stack_grafana_token=TOKEN)["mcp_servers"]["grafana"]
    assert server["args"][0].endswith("/mcp/grafana-reader.py")


def test_the_role_installs_what_it_ships_for_the_gateway() -> None:
    install = next(t for t in _tasks_named("Install the MCP servers"))
    assert "hermes-mcp/" in install["ansible.builtin.copy"]["src"]
    assert install["ansible.builtin.copy"]["mode"] == "0644"


def _tasks_named(name: str) -> list[dict]:
    from tests.test_agent_stack_role import _tasks

    return [t for t in _tasks() if t.get("name") == name]
