"""Unit tests for the headscale Ansible role — VPN-ACL-001 (ADR-041).

Pure render + static-YAML assertions: NO VPN/SSH required, runs under
``make test`` (marker-less → collected by ``-m "not e2e and not infra"``).

Encodes the spec VPNACL-001 contract:
- ``policy.path`` is parameterized from ``headscale_policy_path`` (not the
  hardcoded ``""`` in ``config.yaml.j2``); the default ``""`` is a no-op
  refactor that keeps the mesh allow-all.
- Policy reload is a **SIGHUP** (``docker kill --signal=HUP headscale``) on the
  Docker Compose deployment — NOT a container restart, and SEPARATE from the
  ``config.yaml`` restart path (finding #1: headscale only hot-reloads the
  policy file via SIGHUP; the server config still needs a restart).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROLE = Path(__file__).resolve().parent.parent / "infra/ansible/roles/headscale"
TEMPLATES = ROLE / "templates"


def _base_context(**overrides: object) -> dict[str, object]:
    """Minimal var context to render config.yaml.j2 standalone (mirrors defaults/main.yml)."""
    ctx: dict[str, object] = dict(
        headscale_domain="vpn.kubelab.live",
        headscale_listen_port=8080,
        tailscale_cidr="100.64.0.0/10",
        headscale_derp_enabled=True,
        headscale_derp_region_id=999,
        headscale_derp_region_code="kubelab",
        headscale_derp_region_name="KubeLab Homelab",
        headscale_derp_verify_clients=True,
        headscale_dns_split={},
        headscale_dns_extra_records=[],
        headscale_db_type="sqlite",
        headscale_policy_path="",
    )
    ctx.update(overrides)
    return ctx


def _render_config(**overrides: object) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    return env.get_template("config.yaml.j2").render(**_base_context(**overrides))


class TestPolicyPathParameterized:
    """policy.path must come from the role var, not a hardcoded literal."""

    def test_policy_path_renders_from_var(self) -> None:
        cfg = yaml.safe_load(_render_config(headscale_policy_path="/etc/headscale/policy.hujson"))
        assert cfg["policy"]["mode"] == "file"
        assert cfg["policy"]["path"] == "/etc/headscale/policy.hujson"

    def test_default_empty_preserves_allow_all(self) -> None:
        # default var "" must render path: "" — no-op refactor, mesh stays allow-all
        cfg = yaml.safe_load(_render_config())
        assert cfg["policy"]["path"] == ""

    def test_template_source_not_hardcoded(self) -> None:
        src = (TEMPLATES / "config.yaml.j2").read_text()
        assert 'path: ""' not in src, "policy.path must be templated, not the hardcoded empty literal"
        assert "headscale_policy_path" in src, "config.yaml.j2 must reference the headscale_policy_path var"


class TestReloadHandler:
    """Policy reload is SIGHUP via docker, never a restart (finding #1)."""

    def _handlers(self) -> list[dict]:
        return yaml.safe_load((ROLE / "handlers/main.yml").read_text())

    def test_reload_handler_uses_sighup(self) -> None:
        reload_handlers = [h for h in self._handlers() if "reload" in str(h.get("name", "")).lower()]
        assert reload_handlers, "a 'reload headscale' handler must exist"
        cmds = " ".join(str(h.get("command", "")) for h in reload_handlers)
        assert "kill --signal=HUP headscale" in cmds, (
            "policy reload must SIGHUP the container (docker kill --signal=HUP headscale), not restart"
        )

    def test_reload_handler_is_not_a_restart(self) -> None:
        reload_handlers = [h for h in self._handlers() if "reload" in str(h.get("name", "")).lower()]
        cmds = " ".join(str(h.get("command", "")) for h in reload_handlers)
        assert "restart" not in cmds.lower(), "reload must not be a docker compose restart (drops sessions)"


class TestPolicyFileDeploy:
    """The policy file is deployed conditionally and notifies the SIGHUP reload."""

    def _tasks(self) -> list[dict]:
        return yaml.safe_load((ROLE / "tasks/main.yml").read_text())

    def test_policy_deploy_task_exists_and_is_conditional(self) -> None:
        policy_tasks = [t for t in self._tasks() if "policy" in str(t.get("name", "")).lower()]
        assert policy_tasks, "a task must deploy the HuJSON policy file"
        t = policy_tasks[0]
        assert "when" in t, "policy-file deploy must be conditional (dormant when headscale_policy_path is empty)"
        assert "headscale_policy_path" in str(t["when"]), "the guard must key off headscale_policy_path"

    def test_policy_change_notifies_reload_not_restart(self) -> None:
        policy_tasks = [t for t in self._tasks() if "policy" in str(t.get("name", "")).lower()]
        notify = policy_tasks[0].get("notify", "")
        notify_s = " ".join(notify) if isinstance(notify, list) else str(notify)
        assert "reload" in notify_s.lower(), "policy-file change must notify the reload (SIGHUP) handler"
        assert "restart" not in notify_s.lower(), "policy-file change must NOT trigger a restart"
