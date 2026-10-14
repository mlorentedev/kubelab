"""#1228: a playbook run that matches no host fails instead of reporting success.

By default Ansible treats a host pattern that matches nothing as a warning and
exits 0, so a run against the wrong inventory, or one whose host names have
drifted, touches nothing and reads as a green deploy (lesson-356). The committed
`infra/ansible/inventories/homelab.yml` drifted exactly that way. `infra/ansible/ansible.cfg`
turns the warning into an error for every command started from that directory,
which is where the toolkit runner starts them.
"""

from __future__ import annotations

import configparser
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from toolkit.cli import infra
from toolkit.config.settings import settings

ANSIBLE_DIR = Path(__file__).resolve().parents[1] / "infra/ansible"


def test_the_config_makes_a_pattern_mismatch_an_error() -> None:
    config = configparser.ConfigParser()
    config.read(ANSIBLE_DIR / "ansible.cfg", encoding="utf-8")
    assert config.get("inventory", "host_pattern_mismatch", fallback=None) == "error"


@pytest.mark.allow_host_clients(reason="runs a play whose only host is ansible_connection=local and matches none of it")
def test_a_play_that_matches_no_host_fails(tmp_path: Path) -> None:
    if shutil.which("ansible-playbook") is None:
        pytest.skip("ansible-playbook not on PATH: the zero-host run was NOT executed")
    inventory = tmp_path / "hosts.yml"
    inventory.write_text("all:\n  hosts:\n    somebody:\n      ansible_connection: local\n", encoding="utf-8")
    play = tmp_path / "play.yml"
    play.write_text("- hosts: nobody\n  gather_facts: false\n  tasks: []\n", encoding="utf-8")
    result = subprocess.run(
        ["ansible-playbook", str(play), "-i", str(inventory)],
        cwd=ANSIBLE_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "nobody" in result.stdout + result.stderr


def test_the_runner_starts_ansible_where_the_config_lives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The config only binds a command started from its directory, so pin both halves."""
    assert settings.ansible_dir.resolve() == ANSIBLE_DIR.resolve()

    (tmp_path / "playbooks").mkdir()
    (tmp_path / "playbooks" / "site.yml").write_text("---\n", encoding="utf-8")
    (tmp_path / "generated" / "prod").mkdir(parents=True)
    (tmp_path / "generated" / "prod" / "hosts.yml").write_text("---\n", encoding="utf-8")
    monkeypatch.setattr(infra, "settings", SimpleNamespace(ansible_dir=tmp_path))
    seen: dict[str, Any] = {}

    def fake_run(cmd: str, **kwargs: Any) -> SimpleNamespace:
        seen.update(kwargs, cmd=cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(infra.command, "run", fake_run)
    infra.ansible_run(playbook="site", env="prod", skip_generate=True)
    assert seen["cmd"].startswith("ansible-playbook ")
    assert seen["cwd"] == tmp_path
