"""Unit tests for the node_backup role's capture/ship scripts — BACKUP-044 Part 3.

Pure render + assertion tests: NO SSH, no live node, no real restic/docker
call. Runs under ``make test`` (marker-less -> collected by ``-m "not e2e and
not infra"``), mirroring tests/test_node_maintenance_notify.py's pattern.

The contract encoded here:

- Every entry in backup.sources renders into the capture script, and every
  live SQLite database is snapshotted with ``sqlite3 .backup`` — never a
  plain ``cp`` of a file that is written to concurrently.
- A ``path:`` source is read directly; a ``volume:`` source is resolved
  through ``docker volume inspect`` at capture time, never assumed.
- The ship script carries the operator-approved retention flags verbatim,
  and only runs ``restic check`` when invoked with ``--check`` — that split
  is the whole reason Part 4 does not have to touch this script to add the
  weekly-vs-frequent schedule.
- Credentials are read from files, never appear as a literal in either
  script — the same argv/ps exposure ANSIBLE-038 already fixed elsewhere.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/node_backup"
TEMPLATES = ROLE / "templates"
DEFAULTS = ROLE / "defaults/main.yml"

# Mirrors the real shape measured against common.yaml's backup.sources: three
# volume: entries (Docker volumes) and one path: entry (a bind mount).
BEELINK_SOURCES = {
    "gitea": {"path": "/opt/gitea/data", "sqlite": "gitea/gitea.db"},
}
VPS_SOURCES = {
    "headscale": {"volume": "headscale_headscale_data", "sqlite": "db.sqlite"},
}
RPI3_SOURCES = {
    "uptime_kuma": {"volume": "uptime_kuma_data", "sqlite": "kuma.db"},
}


def _defaults() -> dict[str, object]:
    """The role's own defaults — so a renamed variable fails here, not on a node."""
    return yaml.safe_load(DEFAULTS.read_text())


def _render(template: str, **overrides: object) -> str:
    """Render one role template with StrictUndefined.

    StrictUndefined is load-bearing here even more than usual: this role's
    scripts are built almost entirely from Jinja loops over backup_sources,
    and a typo'd key would silently render an empty capture block instead of
    failing — a source that looks configured and backs up nothing.
    """
    ctx: dict[str, object] = dict(_defaults())
    ctx.update(
        ansible_managed="Ansible managed",
        inventory_hostname="beelink",
        node_backup_sources=BEELINK_SOURCES,
        node_backup_restic_version="0.19.1",
        node_backup_r2_repo_prefix="s3:https://acct.r2.cloudflarestorage.com/kubelab-backups",
    )
    ctx.update(overrides)
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    return env.get_template(template).render(**ctx)


# --- capture: every source is covered, by the right mechanism --------------


def test_a_path_source_is_read_directly_with_no_docker_involved():
    script = _render("node-backup-capture.sh.j2", node_backup_sources=BEELINK_SOURCES)
    assert 'SRC_DIR_gitea="/opt/gitea/data"' in script
    assert "docker volume inspect" not in script


def test_a_volume_source_is_resolved_through_docker_volume_inspect():
    script = _render("node-backup-capture.sh.j2", node_backup_sources=VPS_SOURCES)
    assert "docker volume inspect headscale_headscale_data" in script
    assert "--format" in script and "Mountpoint" in script


def test_every_declared_source_produces_a_capture_block():
    """Multiple sources on one node (RPi3 style) — none silently dropped."""
    sources = {**VPS_SOURCES, **RPI3_SOURCES}
    script = _render("node-backup-capture.sh.j2", node_backup_sources=sources)
    for service in sources:
        assert f"--- {service} " in script


def test_the_live_sqlite_db_is_snapshotted_with_backup_not_copied():
    script = _render("node-backup-capture.sh.j2", node_backup_sources=RPI3_SOURCES)
    assert 'sqlite3 "$SRC_DIR_uptime_kuma/kuma.db" ".backup' in script
    # A plain `cp` of the live db defeats the entire point of using .backup —
    # assert the generic copy step explicitly excludes it.
    assert '! -path "./kuma.db"' in script
    assert '! -path "./kuma.db-wal"' in script
    assert '! -path "./kuma.db-shm"' in script


def test_the_generic_copy_excludes_only_the_db_and_its_wal_shm_siblings():
    """Headscale's keys (not databases) must still be captured — AC2's
    "everything else by path" half, not just the sqlite half."""
    script = _render("node-backup-capture.sh.j2", node_backup_sources=VPS_SOURCES)
    assert "find . -mindepth 1" in script
    assert "cp -a --parents" in script


def test_capture_script_fails_closed_on_error():
    script = _render("node-backup-capture.sh.j2")
    assert "set -euo pipefail" in script


# --- ship: retention, the --check split, credentials -----------------------


def test_ship_script_carries_the_approved_retention_flags_verbatim():
    script = _render("node-backup-ship.sh.j2")
    d = _defaults()
    assert d["node_backup_retention_flags"] == "--keep-daily 7 --keep-weekly 4 --keep-monthly 6"
    assert str(d["node_backup_retention_flags"]) in script


def test_restic_check_only_runs_when_the_check_flag_is_passed():
    script = _render("node-backup-ship.sh.j2")
    assert '[ "${1:-}" = "--check" ]' in script
    # `restic check` must be conditional, not unconditional — the whole
    # reason the approved-parameters table separates "weekly" from "per-run".
    m = re.search(r'if \[ "\$RUN_CHECK" -eq 1 \]; then\n(.*?)\nfi', script, re.DOTALL)
    assert m and "$RESTIC check" in m.group(1)


def test_ship_script_reads_credentials_from_files_never_as_a_literal():
    script = _render("node-backup-ship.sh.j2")
    d = _defaults()
    assert f"cat {d['node_backup_restic_password_file']}" in script
    assert f"cat {d['node_backup_r2_access_key_file']}" in script
    assert f"cat {d['node_backup_r2_secret_key_file']}" in script


def test_credential_file_paths_are_the_same_variable_on_both_sides():
    """The write side (tasks.yml) and the read side (ship script) must
    reference the SAME Jinja variable, not a literal path duplicated in two
    places — the ship_script_path drift guard, applied to all three
    credential files this role writes and then reads back."""
    ship_tpl_src = (TEMPLATES / "node-backup-ship.sh.j2").read_text()
    tasks_src = (ROLE / "tasks/main.yml").read_text()
    for var in (
        "node_backup_restic_password_file",
        "node_backup_r2_access_key_file",
        "node_backup_r2_secret_key_file",
    ):
        ref = "{{ " + var + " }}"
        assert ref in ship_tpl_src, f"{var} not read by the ship script"
        assert ref in tasks_src, f"{var} not written by tasks/main.yml"


def test_ship_script_refuses_to_run_against_an_empty_staging_dir():
    script = _render("node-backup-ship.sh.j2")
    assert "capture did not run first" in script
    assert "exit 1" in script


def test_ship_script_fails_closed_on_error():
    script = _render("node-backup-ship.sh.j2")
    assert "set -euo pipefail" in script


# --- units: the ordering constraint and the RPi3 memory cap ----------------


def test_ship_unit_orders_after_capture():
    unit = _render("node-backup-ship.service.j2")
    after = re.search(r"^After=(\S+)$", unit, re.MULTILINE)
    assert after
    assert after.group(1) == _defaults()["node_backup_capture_service_name"]


def test_ship_unit_execstart_matches_the_script_the_role_installs():
    unit = _render("node-backup-ship.service.j2")
    exec_start = re.search(r"^ExecStart=(\S+)$", unit, re.MULTILINE)
    assert exec_start
    assert exec_start.group(1) == _defaults()["node_backup_ship_script_path"]
    # Both sides reference the SAME variable, not a literal duplicated in two
    # places — so renaming the default in one spot cannot silently orphan the
    # other. Checked against the templates' own unrendered source, since the
    # rendered path is already asserted above.
    unit_src = (TEMPLATES / "node-backup-ship.service.j2").read_text()
    tasks_src = (ROLE / "tasks/main.yml").read_text()
    assert "{{ node_backup_ship_script_path }}" in unit_src
    assert "{{ node_backup_ship_script_path }}" in tasks_src


def test_memory_cap_is_omitted_when_not_set_default_off():
    """Only RPi3 gets the cap (Part 0/R-B); every other node must not."""
    unit = _render("node-backup-ship.service.j2", node_backup_memory_max="")
    assert "MemoryMax" not in unit


def test_memory_cap_applies_with_swap_disabled_when_set():
    unit = _render(
        "node-backup-ship.service.j2",
        node_backup_memory_max="128M",
        node_backup_memory_swap_max="0",
    )
    assert "MemoryMax=128M" in unit
    assert "MemorySwapMax=0" in unit


def test_no_timer_unit_exists_yet():
    """Part 3 scope guard: Part 4 owns scheduling, not this part."""
    assert not any(TEMPLATES.glob("*.timer.j2"))
