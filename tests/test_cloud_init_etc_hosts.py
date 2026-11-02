"""cloud-init does not rewrite the edge's /etc/hosts at boot (#2777).

Two roles write `/etc/hosts`: `base_system` owns the `127.0.1.1` line and
`dns_resilience` a marked block. On the edge a third writer outranked both: the
Raspberry Pi image's user-data sets `manage_etc_hosts: true`, so cloud-init's
`update_etc_hosts` rewrote the file from its own template at every boot, and
after each reboot the edge had no `vpn.kubelab.live` pin until the next
provision put it back.

User-data outranks `/etc/cloud/cloud.cfg.d`, so a drop-in cannot turn it off.
`base_system` writes `/etc/cloud/cloud-init.disabled`, the marker the Ubuntu
installer already left on the nodes installed from the ISO, on the nodes whose
play asks for it, and only the edge's play does.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
ROLES = REPO / "infra/ansible/roles"
PLAYBOOKS = REPO / "infra/ansible/playbooks"
BASE_SYSTEM = ROLES / "base_system"
EDGE_PLAY = PLAYBOOKS / "provision-rpi4.yml"
MARKER = "/etc/cloud/cloud-init.disabled"
VAR = "base_system_disable_cloud_init"
HOSTS_LINE = "Ensure hostname resolves locally"


def _load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _tasks() -> list[dict]:
    return _load(BASE_SYSTEM / "tasks/main.yml")


def _marker_task_index() -> int:
    hits = [i for i, task in enumerate(_tasks()) if task.get("copy", {}).get("dest") == MARKER]
    assert len(hits) == 1, f"base_system must write {MARKER} in exactly one task, found {len(hits)}"
    return hits[0]


def _role_vars(play_path: Path, role: str) -> list[dict]:
    found = []
    for play in _load(play_path) or []:
        for entry in play.get("roles", []) if isinstance(play, dict) else []:
            if isinstance(entry, dict) and Path(str(entry.get("role", ""))).name == role:
                found.append(entry.get("vars", {}) or {})
    return found


def test_only_the_two_known_roles_write_etc_hosts():
    """A third writer in a role would race these two the way cloud-init did."""
    writers = sorted(
        path.relative_to(ROLES).parts[0]
        for path in ROLES.glob("*/tasks/*.yml")
        if "/etc/hosts" in path.read_text(encoding="utf-8")
    )
    assert writers == ["base_system", "dns_resilience"]


def test_the_marker_is_written_before_the_hosts_line_and_never_overwritten():
    marker = _marker_task_index()
    hosts = next(i for i, task in enumerate(_tasks()) if task.get("name") == HOSTS_LINE)
    task = _tasks()[marker]

    assert marker < hosts, "cloud-init must be stopped before base_system writes its own line"
    assert task["copy"]["force"] is False, "an existing marker, the installer's included, is left as it is"
    assert task["when"] == f"{VAR} | bool"


def test_the_role_leaves_cloud_init_alone_unless_a_play_asks():
    assert _load(BASE_SYSTEM / "defaults/main.yml")[VAR] is False


def test_only_the_edge_play_stops_cloud_init():
    setters = sorted(
        path.name
        for path in PLAYBOOKS.rglob("*.yml")
        if any(VAR in role_vars for role_vars in _role_vars(path, "base_system"))
    )
    assert setters == [EDGE_PLAY.name]
    assert all(role_vars.get(VAR) is True for role_vars in _role_vars(EDGE_PLAY, "base_system"))

    # A play can also set it with set_fact or a group var, which the walk above
    # does not read: provision.yml sets base_system vars that way, for all hosts.
    naming = sorted(
        path.name
        for path in [*PLAYBOOKS.rglob("*.yml"), *(REPO / "infra/ansible/inventories").rglob("*.yml")]
        if VAR in path.read_text(encoding="utf-8")
    )
    assert naming == [EDGE_PLAY.name]


def test_no_task_removes_the_marker():
    """Another play applying base_system without the var must not bring cloud-init back."""
    for path in ROLES.glob("*/tasks/*.yml"):
        for task in _load(path) or []:
            module = task.get("file") or task.get("ansible.builtin.file") or {}
            assert not (module.get("path") == MARKER and module.get("state") == "absent"), path
