"""The agent_stack role: Open WebUI on ace2 (ADR-068, spec AI-009-hermes-ace2).

Rendered with the values `provision-ace2.yml` passes, read from `common.yaml`,
so a change to the SSOT is what these tests see, not a fixture's copy of it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/agent_stack"
COMMON = REPO / "infra/config/values/common.yaml"

# ADR-068 D1: no single service on the dev node may take more than 1.5 GB.
MAX_MEMORY_BYTES = 1536 * 1024**2
SECRET_INPUTS = ("agent_stack_webui_oidc_client_secret", "agent_stack_nan_api_key", "_agent_stack_webui_secret_key")


def _common() -> dict:
    return yaml.safe_load(COMMON.read_text())


def _context() -> dict:
    common = _common()
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    return {
        **defaults,
        "ansible_managed": "managed",
        "tailscale_ip": common["networking"]["nodes"]["ace2"]["tailscale_ip"],
        "agent_stack_webui": common["apps"]["services"]["ai"]["open_webui"],
        "agent_stack_webui_oidc_client_id": "open-webui-oidc",
        "agent_stack_oidc_issuer": "https://auth.example.test",
        "agent_stack_webui_oidc_client_secret": "oidc-secret-sentinel",
        "agent_stack_nan_api_key": "nan-key-sentinel",
        "_agent_stack_webui_secret_key": "session-key-sentinel",
    }


def _render(name: str) -> str:
    env = Environment(loader=FileSystemLoader(str(ROLE / "templates")), undefined=StrictUndefined)
    return env.get_template(name).render(**_context())


def _tasks() -> list[dict]:
    """Every task in every file of the role, including those nested in a block."""
    flat: list[dict] = []
    for path in sorted((ROLE / "tasks").glob("*.yml")):
        for task in yaml.safe_load(path.read_text()) or []:
            flat.append(task)
            flat.extend(task.get("block") or [])
    return flat


def _template_task(src: str) -> dict:
    for task in _tasks():
        spec = task.get("ansible.builtin.template") or {}
        if spec.get("src") == src:
            return task
    raise AssertionError(f"no task renders {src}")


def _bytes(limit: str) -> int:
    units = {"k": 1024, "m": 1024**2, "g": 1024**3}
    limit = limit.strip().lower().removesuffix("b")
    return int(limit[:-1]) * units[limit[-1]] if limit[-1] in units else int(limit)


def test_every_service_is_memory_bounded_under_the_adr_limit() -> None:
    compose = yaml.safe_load(_render("compose-webui.yml.j2"))
    for name, service in compose["services"].items():
        assert "mem_limit" in service, f"{name} has no memory limit"
        assert _bytes(str(service["mem_limit"])) <= MAX_MEMORY_BYTES, f"{name} exceeds ADR-068 D1's 1.5 GB"


def test_the_port_is_published_on_the_tailscale_address_only() -> None:
    """A bare `<port>:8080` listens everywhere, and ufw cannot restrict it (#959)."""
    ip = _context()["tailscale_ip"]
    compose = yaml.safe_load(_render("compose-webui.yml.j2"))
    for name, service in compose["services"].items():
        for port in service.get("ports", []):
            assert str(port).startswith(f"{ip}:"), f"{name} publishes {port!r} beyond the Tailscale address"


def test_the_env_file_is_private_and_never_logged() -> None:
    task = _template_task("webui.env.j2")
    assert task["ansible.builtin.template"]["mode"] == "0600"
    assert task["ansible.builtin.template"]["owner"] == "root"
    assert task.get("no_log") is True, "a diff of this file would print the OIDC secret"


@pytest.mark.parametrize("secret", SECRET_INPUTS)
def test_no_secret_reaches_the_compose_file(secret: str) -> None:
    source = (ROLE / "templates/compose-webui.yml.j2").read_text()
    assert secret not in source
    assert _context()[secret] not in _render("compose-webui.yml.j2")


def test_oidc_is_the_only_way_in() -> None:
    """Without OIDC the first visitor becomes admin; the tailnet includes `work@` bridges."""
    env = dict(line.split("=", 1) for line in _render("webui.env.j2").splitlines() if line and not line.startswith("#"))
    assert env["ENABLE_LOGIN_FORM"] == "false"
    assert env["ENABLE_SIGNUP"] == "false"
    assert env["OAUTH_CLIENT_SECRET"] == "oidc-secret-sentinel"
    assert env["ENABLE_OLLAMA_API"] == "false"


def test_open_webui_is_not_deployed_without_an_oidc_secret() -> None:
    [block] = [t for t in _tasks() if t.get("name") == "Deploy Open WebUI"]
    assert block["when"] == "agent_stack_webui_oidc_client_secret | length > 0"


def test_the_redirect_uri_matches_the_declared_scheme_host_and_port() -> None:
    webui = _context()["agent_stack_webui"]
    env = dict(line.split("=", 1) for line in _render("webui.env.j2").splitlines() if line and not line.startswith("#"))
    base = f"{webui['scheme']}://{webui['host']}:{webui['default_port']}"
    assert env["WEBUI_URL"] == base
    assert env["OPENID_REDIRECT_URI"] == f"{base}/oauth/oidc/callback"


def test_the_role_runs_on_ace2_after_dev_node() -> None:
    plays = yaml.safe_load((REPO / "infra/ansible/playbooks/provision-ace2.yml").read_text())
    roles = [r["role"].rsplit("/", 1)[-1] for r in plays[1]["roles"]]
    assert "agent_stack" in roles
    assert roles.index("agent_stack") > roles.index("dev_node")


def test_an_unconfigured_run_takes_a_previous_open_webui_down() -> None:
    """Removing the secret from SOPS must stop Open WebUI, not leave it serving."""
    [stop] = [t for t in _tasks() if t.get("name") == "Stop Open WebUI when it is not configured"]
    assert stop["when"] == "agent_stack_webui_oidc_client_secret | length == 0"
    commands = [t["ansible.builtin.command"] for t in stop["block"] if "ansible.builtin.command" in t]
    assert any(c.rstrip().endswith(" down") for c in commands)
    [remove] = [t for t in stop["block"] if "ansible.builtin.file" in t]
    assert "webui.env" in remove["loop"], "the secret-bearing env file must not outlive the service"


_COMMAND_MODULES = ("ansible.builtin.command", "command", "ansible.builtin.shell", "shell")


def test_every_read_runs_in_a_dry_run() -> None:
    """A registered command that never reports a change is a read, so it must run under `--check`.

    Check mode skips `command`, a skipped task registers no `rc` or `stdout`, and
    the recreate decision reads both. The same rule holds in dev_node, where it
    was measured twice on ace2 (tests/test_dev_node_npm_converges.py).
    """
    reads = [
        task
        for task in _tasks()
        if any(key in task for key in _COMMAND_MODULES)
        and task.get("register")
        and task.get("changed_when") is False
    ]
    assert reads, "the role has no registered reads; this guard checks nothing"
    skipped = [task["name"] for task in reads if task.get("check_mode") is not False]
    assert not skipped, f"reads skipped by --check: {skipped}"
