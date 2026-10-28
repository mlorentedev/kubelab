"""The Headscale host's audit identity can read, and can do nothing else (SEC-037, #2734).

`deployer` is root-equivalent on the VPS (passwordless sudo and the docker
group), so an unattended audit cannot be handed a key that logs in as it
unrestricted. The key is authorized instead with `restrict` and a forced
command, and that command is the whole security boundary: sshd runs it for
every connection and hands it the client's request in `SSH_ORIGINAL_COMMAND`.

The script therefore has to refuse everything it does not match exactly, and
the refusals that matter are the ones a prefix or glob match would let
through: a chain, a pipe, a substitution, a write subcommand of an allowed
binary, a Docker escape. These tests run the shipped file under `sh`, as sshd
does, with a stand-in `logger` that records what it was asked to log.
"""

from __future__ import annotations

import ipaddress
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.ansible_jinja import ansible_env

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/headscale"
SCRIPT = ROLE / "files/headscale-audit.sh"
AUDIT_TASKS = ROLE / "tasks/audit_identity.yml"
VPS_PLAYBOOK = REPO / "infra/ansible/playbooks/deploy-vps.yml"
COMMON = REPO / "infra/config/values/common.yaml"

INSTALLED_AT = "/usr/local/bin/headscale-audit"
DENIED_RC = 126

SH = shutil.which("sh")
needs_sh = pytest.mark.skipif(SH is None, reason="no POSIX sh on this runner")

REFUSED = [
    "rm -rf /tmp/canary",
    "bash",
    "sh",
    "hostname; id",
    "true && id",
    "hostname | sh",
    "hostname $(id)",
    "hostname `id`",
    "hostname\nid",
    " hostname",
    "hostname ",
    "headscale nodes list -o json",
    "docker exec headscale headscale nodes delete -i 1 --force",
    "docker exec headscale headscale policy set -f /tmp/p.hujson",
    "docker exec headscale headscale nodes list -o json; id",
    "docker exec headscale headscale nodes list -o json --output yaml",
    "docker exec -it headscale sh",
    "docker run --rm -v /:/host alpine cat /host/etc/shadow",
    "docker ps",
    "sudo -n true",
]


@pytest.fixture
def run(tmp_path: Path):
    """Run the script as sshd would, returning (result, lines logged)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "logger.out"
    fake = bindir / "logger"
    fake.write_bytes(b'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$FAKE_LOGGER_OUT"\n')
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def _run(command: str | None, ssh_client: str | None = "192.0.2.10 50000 22"):
        env = {k: v for k, v in os.environ.items() if k not in ("SSH_ORIGINAL_COMMAND", "SSH_CLIENT")}
        env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
        env["FAKE_LOGGER_OUT"] = str(log)
        if command is not None:
            env["SSH_ORIGINAL_COMMAND"] = command
        if ssh_client is not None:
            env["SSH_CLIENT"] = ssh_client
        result = subprocess.run([SH, str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30)
        lines = log.read_text().splitlines() if log.exists() else []
        return result, lines

    return _run


class TestForcedCommand:
    def test_the_file_is_lf_only(self) -> None:
        assert b"\r" not in SCRIPT.read_bytes(), "a CR breaks the shebang and every case pattern under sh"

    @needs_sh
    @pytest.mark.parametrize("command", [None, "", "true"])
    @pytest.mark.parametrize("ssh_client", ["192.0.2.10 50000 22", None])
    def test_liveness_exits_0(self, run, command: str | None, ssh_client: str | None) -> None:
        result, lines = run(command, ssh_client)
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""
        assert len(lines) == 1 and "allowed" in lines[0]

    @needs_sh
    def test_an_allowlisted_read_runs(self, run) -> None:
        result, lines = run("hostname")
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip()
        assert len(lines) == 1 and "allowed" in lines[0] and "hostname" in lines[0]

    @needs_sh
    @pytest.mark.parametrize("command", REFUSED)
    def test_anything_else_is_refused_and_logged(self, run, command: str) -> None:
        result, lines = run(command)
        assert result.returncode == DENIED_RC
        assert "command not allowed" in result.stderr
        assert result.stdout == ""
        assert len(lines) == 1 and "refused" in lines[0]

    @needs_sh
    def test_a_refused_command_never_runs(self, run, tmp_path: Path) -> None:
        canary = tmp_path / "canary"
        canary.mkdir()
        result, _ = run(f"rm -rf {canary}")
        assert result.returncode == DENIED_RC
        assert canary.exists()

    @needs_sh
    def test_a_refusal_without_ssh_client_is_still_logged(self, run) -> None:
        result, lines = run("bash", ssh_client=None)
        assert result.returncode == DENIED_RC
        assert "unbound variable" not in result.stderr
        assert len(lines) == 1 and "refused" in lines[0] and "unknown" in lines[0]

    def test_the_allowlist_holds_only_reads(self) -> None:
        patterns = set(re.findall(r"^\s*'([^']*)'\)", SCRIPT.read_text(), re.M))
        headscale = {p for p in patterns if p.startswith("docker exec headscale headscale ")}
        assert headscale == {
            "docker exec headscale headscale nodes list -o json",
            "docker exec headscale headscale users list -o json",
            "docker exec headscale headscale policy get",
            "docker exec headscale headscale version",
        }
        assert not any(c in p for p in patterns for c in "*?["), "a glob turns an exact match into a prefix match"


def _audit_tasks() -> list[dict[str, Any]]:
    return yaml.safe_load(AUDIT_TASKS.read_text())


def _task_using(module: str) -> dict[str, Any]:
    names = (module, f"ansible.builtin.{module}", f"ansible.posix.{module}")
    found = [t for t in _audit_tasks() if any(n in t for n in names)]
    assert len(found) == 1, f"expected one {module} task, found {len(found)}"
    task = found[0]
    return task | {"_args": next(task[n] for n in names if n in task)}


def _audit_identities() -> list[dict[str, Any]]:
    return yaml.safe_load(COMMON.read_text())["apps"]["services"]["core"]["headscale"]["audit_identities"]


class TestRole:
    def test_the_role_includes_the_audit_tasks(self) -> None:
        main = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
        assert any("audit_identity.yml" in str(t) for t in main)

    def test_the_script_is_installed_root_owned_and_not_writable_by_the_account(self) -> None:
        copy = _task_using("copy")
        args = copy["_args"]
        assert args["src"] == "headscale-audit.sh"
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        dest = ansible_env(str(ROLE)).from_string(args["dest"]).render(**defaults)
        assert dest == INSTALLED_AT
        assert (args["owner"], args["group"], str(args["mode"])) == ("root", "root", "0755")
        assert copy.get("become") is True

    def test_keys_are_added_never_made_exclusive(self) -> None:
        args = _task_using("authorized_key")["_args"]
        assert "exclusive" not in args, "exclusive authorized_keys is SEC-033's switch (#2246), not this role's"

    @pytest.mark.parametrize(
        ("item", "expected"),
        [
            ({"name": "probe", "key": "k"}, "present"),
            ({"name": "probe", "key": "k", "revoked": False}, "present"),
            ({"name": "probe", "key": "k", "revoked": True}, "absent"),
        ],
    )
    def test_revoking_is_declared_not_done_by_hand(self, item: dict[str, Any], expected: str) -> None:
        template = _task_using("authorized_key")["_args"]["state"]
        assert ansible_env(str(ROLE)).from_string(template).render(item=item) == expected

    @pytest.mark.parametrize(
        ("sources", "expected"),
        [
            ({}, f'restrict,command="{INSTALLED_AT}"'),
            ({"other": "198.51.100.7"}, f'restrict,command="{INSTALLED_AT}"'),
            ({"probe": "198.51.100.7"}, f'restrict,command="{INSTALLED_AT}",from="198.51.100.7"'),
        ],
    )
    def test_key_options_restrict_force_and_pin_the_source_when_declared(
        self, sources: dict[str, str], expected: str
    ) -> None:
        template = _task_using("authorized_key")["_args"]["key_options"]
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        rendered = (
            ansible_env(str(ROLE))
            .from_string(template)
            .render(
                item={"name": "probe", "key": "ssh-ed25519 AAAA"},
                headscale_audit_command=defaults["headscale_audit_command"],
                headscale_audit_sources=sources,
            )
        )
        assert rendered.strip() == expected

    def test_defaults_declare_no_identity(self) -> None:
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        assert defaults["headscale_audit_identities"] == []
        assert defaults["headscale_audit_sources"] == {}
        assert defaults["headscale_audit_command"] == INSTALLED_AT

    def test_the_vps_play_takes_keys_from_config_and_sources_from_sops(self) -> None:
        play = yaml.safe_load(VPS_PLAYBOOK.read_text())[0]
        role = next(r for r in play["roles"] if str(r.get("role", "")).endswith("/headscale"))
        assert "config.apps.services.core.headscale.audit_identities" in role["vars"]["headscale_audit_identities"]
        sources = role["vars"]["headscale_audit_sources"]
        assert "secrets" in sources and "config." not in sources


class TestDeclaration:
    def test_every_identity_is_a_bare_public_key(self) -> None:
        identities = _audit_identities()
        assert identities, "no audit identity is declared"
        for identity in identities:
            assert set(identity) <= {"name", "key", "revoked"} and {"name", "key"} <= set(identity)
            assert re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/]+={0,2}", identity["key"]), (
                "the comment comes from `name`, so a key's own comment cannot leak a host name"
            )

    def test_names_are_unique(self) -> None:
        names = [i["name"] for i in _audit_identities()]
        assert len(names) == len(set(names))

    def test_no_source_address_in_the_public_tree(self) -> None:
        for token in re.findall(r"[0-9A-Fa-f:.]{7,}", yaml.safe_dump(_audit_identities())):
            with pytest.raises(ValueError):
                ipaddress.ip_network(token.strip(":."), strict=False)
