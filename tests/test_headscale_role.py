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

import json
import re
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/headscale"
TEMPLATES = ROLE / "templates"
COMMON_YAML = REPO / "infra/config/values/common.yaml"


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


# ── policy.hujson content (VPN-ACL-002) ─────────────────────────────────────────


def _hosts_from_ssot() -> dict[str, str]:
    """Build the ACL host map exactly as the deploy-vps playbook does (from common.yaml)."""
    net = yaml.safe_load(COMMON_YAML.read_text())["networking"]
    hosts = {name: node["tailscale_ip"] for name, node in net["nodes"].items()}
    hosts["vps"] = net["vps"]["tailscale_ip"]
    hosts["aws1"] = net["aws"]["tailscale_ip"]
    hosts["lan-rpi4"] = net["lan_cidr"]
    return hosts


def _render_policy(hosts: dict[str, str] | None = None) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env.get_template("policy.hujson.j2").render(headscale_policy_hosts=hosts or _hosts_from_ssot())


def _load_hujson(text: str) -> dict:
    """Parse HuJSON (JSON + // comments + trailing commas) into a dict for assertions."""
    no_comments = re.sub(r"//[^\n]*", "", text)
    no_trailing = re.sub(r",(\s*[}\]])", r"\1", no_comments)
    return json.loads(no_trailing)


class TestPolicyHujsonContent:
    """policy.hujson is the permissive-first baseline + tag:hermes egress, rendered from SSOT."""

    def test_renders_valid_hujson(self) -> None:
        policy = _load_hujson(_render_policy())
        assert set(policy) >= {"hosts", "tagOwners", "acls"}

    def test_hosts_come_from_ssot_not_hardcoded(self) -> None:
        # the template DATA must contain NO IP literals — every address comes from the var.
        # (Comments may reference IPs for documentation; strip them before the check.)
        src_body = re.sub(r"//[^\n]*", "", (TEMPLATES / "policy.hujson.j2").read_text())
        assert not re.search(r"\d{1,3}(\.\d{1,3}){3}", src_body), "policy.hujson.j2 must not hardcode IPs/CIDRs"
        # and the rendered hosts must equal the common.yaml values
        ssot = _hosts_from_ssot()
        rendered_hosts = _load_hujson(_render_policy())["hosts"]
        assert rendered_hosts["vps"] == ssot["vps"]
        assert rendered_hosts["beelink"] == ssot["beelink"]
        assert rendered_hosts["lan-rpi4"] == ssot["lan-rpi4"]

    def test_tag_hermes_owned_by_admin(self) -> None:
        policy = _load_hujson(_render_policy())
        assert policy["tagOwners"]["tag:hermes"] == ["kubelab@"], "v0.28 needs the user@ form"

    def test_permissive_first_rule_preserves_existing_identities(self) -> None:
        acls = _load_hujson(_render_policy())["acls"]
        permissive = [a for a in acls if a["dst"] == ["*:*"]]
        assert permissive, "rule 1 must preserve all current flows (dst *:*)"
        src = permissive[0]["src"]
        assert {"kubelab@", "manu@", "work@"} <= set(src), "existing users must keep allow-all (user@ form)"

    def test_hermes_egress_is_node_like_controlled(self) -> None:
        acls = _load_hujson(_render_policy())["acls"]
        hermes = [a for a in acls if a["src"] == ["tag:hermes"]]
        assert hermes, "tag:hermes must have an egress rule"
        assert set(hermes[0]["dst"]) == {"vps:443", "beelink:9000"}

    def test_crown_jewels_excluded_from_hermes(self) -> None:
        acls = _load_hujson(_render_policy())["acls"]
        hermes_dst = [d for a in acls if a["src"] == ["tag:hermes"] for d in a["dst"]]
        forbidden = (":8080", ":6443", ":22")  # Headscale CP, K3s API, peer SSH
        for d in hermes_dst:
            assert not d.endswith(forbidden), f"tag:hermes must not reach a control-plane port: {d}"
