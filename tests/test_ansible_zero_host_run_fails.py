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

import pytest

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
