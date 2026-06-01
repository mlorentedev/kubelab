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

# Render helpers are imported from the single-source renderer (also used by the
# CI gate `make check-headscale-policy`) so tests and CI never drift.
from toolkit.scripts.headscale_probe import run_probe
from toolkit.scripts.render_headscale_policy import build_hosts as _hosts_from_ssot
from toolkit.scripts.render_headscale_policy import render_policy as _render_policy

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

    def _template_task(self) -> dict:
        """The task that renders policy.hujson.j2 (distinct from the backup/rescue tasks)."""
        tasks = [t for t in self._tasks() if t.get("template", {}).get("src") == "policy.hujson.j2"]
        assert tasks, "a template task must render policy.hujson.j2"
        return tasks[0]

    def test_policy_deploy_task_exists_and_is_conditional(self) -> None:
        t = self._template_task()
        assert "when" in t, "policy-file deploy must be conditional (dormant when headscale_policy_path is empty)"
        assert "headscale_policy_path" in str(t["when"]), "the guard must key off headscale_policy_path"

    def test_policy_change_notifies_reload_not_restart(self) -> None:
        notify = self._template_task().get("notify", "")
        notify_s = " ".join(notify) if isinstance(notify, list) else str(notify)
        assert "reload" in notify_s.lower(), "policy-file change must notify the reload (SIGHUP) handler"
        assert "restart" not in notify_s.lower(), "policy-file change must NOT trigger a restart"


# ── policy.hujson content (VPN-ACL-002) ─────────────────────────────────────────


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

    def test_tag_hermes_owned_by_registering_user(self) -> None:
        # the `agents` user registers tagged nodes, so it MUST own the tag (Headscale
        # rejects a node/key carrying a tag its user does not own); kubelab@ kept for
        # manual admin tagging. v0.28 needs the user@ form.
        owners = _load_hujson(_render_policy())["tagOwners"]["tag:hermes"]
        assert "agents@" in owners, "agents@ must own tag:hermes so the agent can register with it"
        assert all(o.endswith("@") for o in owners), "user references need the user@ form on v0.28"

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


# ── external probe + auto-revert gate (VPN-ACL-002) ─────────────────────────────


def _net() -> dict:
    return yaml.safe_load(COMMON_YAML.read_text())["networking"]


def _fake_runner(down_ips: frozenset[str] = frozenset(), blocked: frozenset[str] = frozenset()):
    """Mock command runner: `down_ips` fail the ssh reachability probe; `blocked` ('ip:port') fail the TCP probe."""

    def run(cmd: list[str]) -> int:
        joined = " ".join(cmd)
        if cmd[-1] == "true":  # ssh reachability check
            return 1 if any(ip in joined for ip in down_ips) else 0
        m = re.search(r"/dev/tcp/([\d.]+)/(\d+)", joined)
        if m and f"{m.group(1)}:{m.group(2)}" in blocked:
            return 1
        return 0

    return run


class TestHeadscaleProbe:
    """run_probe: required flows must hold; optional flows skip when their source is down."""

    def test_all_flows_pass(self) -> None:
        assert run_probe(_net(), runner=_fake_runner()) == 0

    def test_required_dst_unreachable_fails(self) -> None:
        vps = _net()["vps"]["tailscale_ip"]
        assert run_probe(_net(), runner=_fake_runner(blocked=frozenset({f"{vps}:22"}))) == 1

    def test_optional_source_down_is_skipped_not_failed(self) -> None:
        # ace1 is the source only of an OPTIONAL flow (intra-K3s) → skip, overall pass
        ace1 = _net()["nodes"]["ace1"]["tailscale_ip"]
        assert run_probe(_net(), runner=_fake_runner(down_ips=frozenset({ace1}))) == 0

    def test_required_source_down_fails(self) -> None:
        # aws1 is the source of a REQUIRED flow (hub->spoke :6443 prod) → cannot be skipped
        aws1 = _net()["aws"]["tailscale_ip"]
        assert run_probe(_net(), runner=_fake_runner(down_ips=frozenset({aws1}))) == 1

    def test_optional_broken_flow_is_logged_not_fatal(self) -> None:
        # an optional flow that fails (e.g. intra-K3s ace1:6443) is logged but must NOT
        # trigger an auto-revert — only required flows drive the gate (homelab/route nuances)
        ace1 = _net()["nodes"]["ace1"]["tailscale_ip"]
        assert run_probe(_net(), runner=_fake_runner(blocked=frozenset({f"{ace1}:6443"}))) == 0

    def test_required_broken_flow_fails(self) -> None:
        # a required flow failing (hub->spoke prod, vps:6443) IS fatal
        vps = _net()["vps"]["tailscale_ip"]
        assert run_probe(_net(), runner=_fake_runner(blocked=frozenset({f"{vps}:6443"}))) == 1


class TestAutoRevert:
    """The role backs up the policy, probes after reload, and reverts on failure."""

    def _tasks(self) -> list[dict]:
        return yaml.safe_load((ROLE / "tasks/main.yml").read_text())

    def test_policy_backed_up_before_write(self) -> None:
        backups = [t for t in self._tasks() if "back up" in str(t.get("name", "")).lower()]
        assert backups, "must back up the current policy before overwriting it"
        assert ".prev" in str(backups[0].get("copy", {}).get("dest", "")), "backup must write a .prev copy"

    def test_revert_block_restores_reloads_and_fails(self) -> None:
        blocks = [t for t in self._tasks() if "block" in t and "rescue" in t]
        assert blocks, "the probe must run in a block guarded by a rescue (auto-revert)"
        rescue_yaml = yaml.safe_dump(blocks[0]["rescue"])
        assert ".prev" in rescue_yaml, "rescue must restore the previous policy"
        assert "kill --signal=HUP" in rescue_yaml, "rescue must SIGHUP-reload the reverted policy"
        assert any("fail" in task for task in blocks[0]["rescue"]), "rescue must fail the play after reverting"

    def test_first_activation_reverts_to_allow_all(self) -> None:
        # Codex P1: with no .prev (first activation), a failed probe must revert to an explicit
        # allow-all, not strand the mesh on the just-loaded ACL.
        rescue = [t for t in self._tasks() if "block" in t and "rescue" in t][0]["rescue"]
        rescue_yaml = yaml.safe_dump(rescue)
        assert '"*:*"' in rescue_yaml or "'*:*'" in rescue_yaml, "no-.prev path must write an allow-all policy"
        assert "not hs_prev.stat.exists" in rescue_yaml, "allow-all fallback must guard on the no-previous-policy case"

    def test_probe_runs_via_cli_not_direct_script(self) -> None:
        blocks = [t for t in self._tasks() if "block" in t]
        block_yaml = yaml.safe_dump(blocks[0]["block"])
        assert "toolkit infra headscale probe" in block_yaml, "probe must run via the toolkit CLI"
        assert "toolkit/scripts/" not in block_yaml, "must not invoke the script file directly"
