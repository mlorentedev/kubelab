"""The DNS gateway stack has one location and one identity, whoever deploys it (ANSIBLE-064, #2053).

Two playbooks run the coredns role: deploy-dns.yml without `become`, provision-rpi4.yml
with it. The role used to inherit its privilege from the caller and keep the stack in
`~/coredns`, so each caller rendered a different directory and moved the containers to
it. These tests pin the three things that make the role's result independent of its
caller. The generic `~` rule is in test_ansible_remote_paths_absolute.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/coredns"
# The live Pi-hole state is in the volume `coredns_pihole_data` (rpi4, 2026-10-04).
LIVE_PROJECT = "coredns"


def test_the_role_runs_under_its_own_become() -> None:
    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    unprivileged = [t.get("name") for t in tasks if not (t.get("block") and t.get("become") is True)]
    assert not unprivileged, (
        "every task must sit in a block that declares `become: true`, so the result does not "
        f"depend on whether the caller set it: {unprivileged}"
    )


def test_the_stack_directory_is_absolute() -> None:
    directory = yaml.safe_load((ROLE / "defaults/main.yml").read_text())["coredns_remote_dir"]
    assert str(directory).startswith("/"), f"coredns_remote_dir must be absolute, got {directory!r}"


def test_the_compose_project_is_pinned_to_the_live_volume() -> None:
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    template = (ROLE / "templates/docker-compose.yml.j2").read_text()
    assert re.search(r"^name: \{\{ coredns_project \}\}$", template, re.M), (
        "the compose file must pin its project name; derived from the directory, it changes "
        "whenever the directory does, and the Pi-hole volume with it"
    )
    assert defaults["coredns_project"] == LIVE_PROJECT, (
        f"renaming the project orphans the Pi-hole volume `{LIVE_PROJECT}_pihole_data`; migrate the volume first"
    )
