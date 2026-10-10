"""The MCP bridge that serves Open WebUI the vault, read-only (ADR-068 D5 and D6,
spec AI-009 AC9).

mcpo turns the stdio filesystem MCP server into the OpenAPI tool server Open
WebUI speaks. It runs on the system daemon beside Open WebUI, on Open WebUI's
network and nowhere else, and reads the root-owned mirror (#2155), never the
agent's clone. The image is built on ace2 from the role's files, FROM mcpo
pinned by digest, with the filesystem server installed from a committed
lockfile, so nothing is fetched unpinned at start.
"""

from __future__ import annotations

import json
import re

import yaml

from tests.test_agent_stack_role import COMMON, REPO, ROLE, _environment, _resolved, _tasks

BRIDGE = ROLE / "files/mcp-bridge"
WRITERS = {"write_file", "edit_file", "create_directory", "move_file"}
KEY = "mcp-bridge-key-sentinel"
CONFIGURED = {"agent_stack_vault_token": "vault-token-sentinel", "_agent_stack_mcp_bridge_key": KEY}


def _render(name: str, **overrides: object) -> str:
    env = _environment()
    return env.get_template(name).render(**_resolved(env, **overrides))


def _compose(**overrides: object) -> dict:
    return yaml.safe_load(_render("compose-webui.yml.j2", **overrides))


def _env(**overrides: object) -> dict[str, str]:
    lines = _render("webui.env.j2", **overrides).splitlines()
    return dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))


def _ssot() -> dict:
    return yaml.safe_load(COMMON.read_text())["apps"]["services"]["ai"]["open_webui"]["mcp_bridge"]


def _connections(**overrides: object) -> list[dict]:
    value = _env(**overrides)["TOOL_SERVER_CONNECTIONS"]
    # Single-quoted, so Compose's env_file parser takes the JSON literally.
    assert value.startswith("'") and value.endswith("'"), value
    return json.loads(value[1:-1])


# --------------------------------------------------------------------------- the service


def test_the_bridge_runs_only_with_open_webui_and_the_vault() -> None:
    assert "mcp-bridge" not in _compose()["services"], "no vault token, no bridge"
    assert "TOOL_SERVER_CONNECTIONS" not in _env()
    assert "mcp-bridge" in _compose(**CONFIGURED)["services"]
    gate = yaml.safe_load((ROLE / "defaults/main.yml").read_text())["agent_stack_mcp_bridge_configured"]
    assert "agent_stack_webui_configured" in gate and "agent_stack_vault_configured" in gate


def test_the_bridge_publishes_no_port_and_reads_the_mirror_read_only() -> None:
    d = _resolved(_environment())
    service = _compose(**CONFIGURED)["services"]["mcp-bridge"]
    assert "ports" not in service, "reached from Open WebUI's network only"
    assert "network_mode" not in service and "networks" not in service, "on Open WebUI's network, the default"
    assert service["volumes"] == [f"{d['agent_stack_vault_mirror']}/tree:/vault:ro"]


def test_the_bridge_container_cannot_write_or_escalate() -> None:
    service = _compose(**CONFIGURED)["services"]["mcp-bridge"]
    assert service["read_only"] is True
    assert service["user"] == "65534:65534"
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]


def test_the_bridge_is_built_on_the_node_and_never_pulled() -> None:
    d = _resolved(_environment())
    service = _compose(**CONFIGURED)["services"]["mcp-bridge"]
    assert service["build"] == {"context": d["agent_stack_mcp_bridge_dir"]}
    assert service["image"] == d["agent_stack_mcp_bridge_image"]
    # `compose pull` would ask a registry for a tag only this node has.
    assert service["pull_policy"] == "never"


def test_the_limits_come_from_the_ssot() -> None:
    service = _compose(**CONFIGURED)["services"]["mcp-bridge"]
    assert service["mem_limit"] == _ssot()["memory_limit"]
    assert str(service["cpus"]) == str(_ssot()["cpu_limit"])
    assert service["environment"] == {"MCP_BRIDGE_PORT": str(_ssot()["container_port"])}


def test_the_key_reaches_the_bridge_by_env_file_only() -> None:
    d = _resolved(_environment())
    service = _compose(**CONFIGURED)["services"]["mcp-bridge"]
    assert service["env_file"] == [f"{d['agent_stack_dir']}/mcp-bridge.env"]
    assert KEY not in _render("compose-webui.yml.j2", **CONFIGURED)
    assert _render("mcp-bridge.env.j2", **CONFIGURED).strip().endswith(f"MCP_BRIDGE_API_KEY={KEY}")


# --------------------------------------------------------------------------- the image


def test_the_base_image_is_pinned_by_digest() -> None:
    [base] = re.findall(r"^FROM (\S+)$", (BRIDGE / "Dockerfile").read_text(), re.M)
    assert re.fullmatch(r"ghcr\.io/open-webui/mcpo:[\w.-]+@sha256:[0-9a-f]{64}", base), base


def test_the_image_runs_as_nobody_and_installs_from_the_lockfile() -> None:
    dockerfile = (BRIDGE / "Dockerfile").read_text()
    assert re.search(r"^USER 65534:65534$", dockerfile, re.M)
    assert "npm ci" in dockerfile and "npm install" not in dockerfile


def test_the_lockfile_holds_the_pinned_server() -> None:
    [(name, spec)] = json.loads((BRIDGE / "package.json").read_text())["dependencies"].items()
    assert re.fullmatch(r"\d+\.\d+\.\d+", spec), f"{name} is pinned exactly, not {spec!r}"
    lock = json.loads((BRIDGE / "package-lock.json").read_text())
    assert lock["packages"][f"node_modules/{name}"]["version"] == spec


def test_the_launcher_keeps_the_key_out_of_argv_and_guards_every_endpoint() -> None:
    """mcpo takes its key only as `--api-key`. Passed on the command line, it would
    sit in /proc/<pid>/cmdline, which every user on ace2 can read, the agent's
    included. The launcher hands it to mcpo inside the process."""
    launcher = (BRIDGE / "launch.py").read_text()
    assert 'os.environ.pop("MCP_BRIDGE_API_KEY")' in launcher
    assert "--strict-auth" in launcher, "the spec and the docs need the key too"
    assert re.search(r'^ENTRYPOINT \["python", "/opt/mcp-bridge/launch.py"\]$', (BRIDGE / "Dockerfile").read_text(), re.M)


def test_only_the_read_tools_are_served() -> None:
    """mcpo creates no endpoint for a disabled tool (measured: 404), and the mount
    is read-only besides."""
    [(name, server)] = json.loads((BRIDGE / "config.json").read_text())["mcpServers"].items()
    assert name == "vault"
    assert server["args"] == ["/vault"], "the server's only allowed directory is the mount"
    assert set(server["disabledTools"]) == WRITERS


def test_dependabot_watches_the_base_image_and_the_server() -> None:
    updates = yaml.safe_load((REPO / ".github/dependabot.yml").read_text())["updates"]
    directory = "/" + str(BRIDGE.relative_to(REPO))
    watched = {u["package-ecosystem"] for u in updates if u["directory"] == directory}
    assert watched == {"docker", "npm"}


# --------------------------------------------------------------------------- Open WebUI's side


def test_open_webui_reaches_the_vault_tool_by_service_name_with_the_key() -> None:
    [connection] = _connections(**CONFIGURED)
    port = _ssot()["container_port"]
    assert connection["url"] == f"http://mcp-bridge:{port}/vault"
    assert connection["type"] == "openapi" and connection["auth_type"] == "bearer"
    assert connection["key"] == KEY
    assert connection["config"]["enable"] is True


def test_the_tool_is_granted_to_no_one_so_only_admins_see_it() -> None:
    """v0.11.4 `has_connection_access`: no `access_grants` is admin-only, the
    posture already decided for the Hermes model (AC4)."""
    [connection] = _connections(**CONFIGURED)
    assert "access_grants" not in connection["config"]


# --------------------------------------------------------------------------- the tasks


def _names() -> list[str]:
    return [t.get("name", "") for t in _tasks()]


def test_the_image_is_built_before_the_project_starts() -> None:
    names = _names()
    assert names.index("Build the MCP bridge image") < names.index("Start Open WebUI")
    [start] = [t for t in _tasks() if t.get("name") == "Start Open WebUI"]
    assert "--remove-orphans" in start["ansible.builtin.command"], "a bridge taken out of the file must stop"


def test_the_bridge_is_probed_after_the_mirror_is_filled() -> None:
    main = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    imports = [t["ansible.builtin.import_tasks"] for t in main if "ansible.builtin.import_tasks" in t]
    assert imports.index("mcp_bridge.yml") == imports.index("vault_mirror.yml") + 1


def test_the_probes_measure_from_open_webuis_side() -> None:
    probes = yaml.safe_load((ROLE / "tasks/mcp_bridge.yml").read_text())
    [block] = probes
    assert block["when"] == "agent_stack_mcp_bridge_configured | bool"
    names = " | ".join(t["name"] for t in block["block"])
    for step in (
        "Verify the bridge refuses a request without the key",
        "Verify the bridge serves no write tool",
        "Verify the bridge's user reads the mirror",
        "Verify Open WebUI lists the vault tool",
    ):
        assert step in names, names
