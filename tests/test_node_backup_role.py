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


def _install_task() -> dict:
    """The apt task, read from tasks/main.yml itself — parsed as YAML rather
    than substring-matched, so a package named only inside a comment cannot
    satisfy it (lesson-357)."""
    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    return next(t for t in tasks if "apt" in t)


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


# --- the partial-backup guard ----------------------------------------------
#
# A populated staging dir proves capture STARTED, not that it FINISHED. The
# unit's `After=` orders the two and requires nothing, so without a sentinel a
# capture that dies on its third of four sources ships a short backup that
# reads as a whole one at restore time. Reported by review on #1179.


def test_capture_writes_the_success_sentinel_last():
    """Written after every source, so `set -e` guarantees its absence on failure."""
    script = _render(
        "node-backup-capture.sh.j2",
        node_backup_sources={**VPS_SOURCES, **RPI3_SOURCES},
    )
    sentinel = _defaults()["node_backup_capture_sentinel"]
    # The default is itself a Jinja expression over the staging dir; compare on
    # the rendered basename so this test does not re-implement the template.
    assert ".capture-complete" in str(sentinel)
    touch_at = script.index("touch ")
    # Must come after the LAST piece of capture work, not merely appear.
    assert touch_at > script.rindex("sqlite3 ")
    assert touch_at > script.rindex("cp -a --parents")


def test_ship_refuses_to_run_without_the_capture_sentinel():
    script = _render("node-backup-ship.sh.j2")
    assert "refusing to ship a partial backup" in script
    m = re.search(r'if \[ ! -f "\$SENTINEL" \]; then\n(.*?)\nfi', script, re.DOTALL)
    assert m and "exit 1" in m.group(1)


def test_sentinel_path_is_the_same_variable_on_both_sides():
    """Same drift guard as the credential files: the writer (capture) and the
    reader (ship) must reference one variable, not a duplicated literal."""
    ref = "{{ node_backup_capture_sentinel }}"
    assert ref in (TEMPLATES / "node-backup-capture.sh.j2").read_text()
    assert ref in (TEMPLATES / "node-backup-ship.sh.j2").read_text()


def test_ship_unit_does_not_hard_require_capture():
    """`Requires=` would re-run capture on every ship start — both are oneshots
    without RemainAfterExit — which decides Part 4's timer topology from here.
    The sentinel covers the failure instead; this asserts the deferral holds."""
    unit = _render("node-backup-ship.service.j2")
    assert "Requires=" not in unit
    assert "BindsTo=" not in unit


# --- the playbook's availability split --------------------------------------


def _plays() -> list[dict]:
    return yaml.safe_load((REPO / "infra/ansible/playbooks/backup.yml").read_text())


def test_always_on_nodes_do_not_ignore_unreachable():
    """VPS and RPi3 are always-on (ADR-028). An unreachable one is a real
    fault, and a run that reports success having installed nothing on them is
    this pipeline's own failure mode arriving via the deploy path."""
    always_on = [p for p in _plays() if "kubelab-vps" in p["hosts"]]
    assert len(always_on) == 1
    assert always_on[0].get("ignore_unreachable") is not True
    assert "rpi3" in always_on[0]["hosts"]


def test_on_demand_nodes_ignore_unreachable():
    """Beelink and RPi4 are powered off routinely; dark is the expected state."""
    on_demand = [p for p in _plays() if "beelink" in p["hosts"]]
    assert len(on_demand) == 1
    assert on_demand[0]["ignore_unreachable"] is True
    assert "rpi4" in on_demand[0]["hosts"]


def test_both_plays_share_one_role_invocation():
    """The split is about reachability ONLY. If the two plays ever carry
    different role vars, a node's backup silently depends on which availability
    class it landed in — the YAML anchors exist to make that impossible."""
    plays = _plays()
    assert len(plays) == 2
    assert plays[0]["roles"] == plays[1]["roles"]
    assert plays[0]["vars"] == plays[1]["vars"]
    assert plays[0]["pre_tasks"] == plays[1]["pre_tasks"]


def _inventory_hostnames() -> set[str]:
    """The names the generated inventory will actually carry.

    Mirrors `generator_ansible.py`: each node's inventory name is
    `networking.nodes.<key>.hostname`, defaulting to the key, and the VPS
    defaults to `kubelab-vps`. It is a MIRROR, so the test below also asserts
    the generator still derives names that way — a silent change there would
    otherwise leave this passing against a rule nobody follows any more.
    """
    common = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())
    net = common["networking"]
    names = {key: node.get("hostname", key) for key, node in net.get("nodes", {}).items()}
    if "vps" in net:
        names["vps"] = net["vps"].get("hostname", "kubelab-vps")
    return set(names.values())


def test_the_mirror_of_the_generator_is_still_accurate():
    source = (REPO / "toolkit/features/generator_ansible.py").read_text()
    assert 'node.get("hostname", _node_key)' in source
    assert 'vps.get("hostname", "kubelab-vps")' in source


def test_every_play_targets_hosts_that_exist_in_the_inventory():
    """The defect this replaces a test for, rather than the test it replaces.

    The previous version stripped `kubelab-` from the play patterns and
    compared the result to `backup.sources`. That compares the file to its own
    derivation and can only pass: `kubelab-beelink` stripped to `beelink`,
    which is declared, so it went green while `beelink` was the name the
    inventory actually used and the pattern matched NOTHING. Three of four
    nodes were silently skipped and the run reported success.

    So this asserts against the inventory's namespace instead — the artifact
    Ansible resolves against — not against a transformation of the patterns.
    """
    inventory = _inventory_hostnames()
    for play in _plays():
        for pattern in play["hosts"].split(","):
            assert pattern in inventory, (
                f"play {play['name']!r} targets {pattern!r}, which is not an "
                f"inventory hostname. Known: {sorted(inventory)}"
            )


def test_every_node_with_declared_sources_is_covered_by_a_play():
    """The split must not drop a node that has state to back up.

    Now goes the other way round from the patterns: `backup.sources` keys are
    short node names, and the play patterns are inventory hostnames, so this
    maps sources -> hostname through the generator's own rule rather than
    guessing a string transformation.
    """
    common = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())
    net = common["networking"]
    declared = set(common.get("backup", {}).get("sources", {}))
    targeted = {p for play in _plays() for p in play["hosts"].split(",")}
    for short in declared:
        node = net.get("nodes", {}).get(short) or (net.get("vps") if short == "vps" else None)
        assert node is not None, f"backup.sources declares {short!r}, absent from networking.*"
        hostname = node.get("hostname", "kubelab-vps" if short == "vps" else short)
        assert hostname in targeted, (
            f"{short!r} declares backup sources but no play targets {hostname!r}"
        )


# --- the install step's own prerequisites -----------------------------------
#
# Both of these were found by the FIRST real deploy of this role, not by the
# suite. The RPi4 cannot install bzip2 at all (its apt refuses the package
# against the installed libbz2), so a role that shells out to bunzip2 is a
# role that cannot be installed there — and it died rc=127 having already
# created a 0-byte /usr/local/bin/restic, because the shell evaluates the
# redirect target before it resolves the command.


def test_the_role_needs_no_external_decompressor():
    """Backup machinery has to install on a node that is already degraded, and
    a broken apt is a degraded node. Decompression uses Python's stdlib, so the
    role's only apt dependency stays sqlite3."""
    packages = _install_task()["apt"]["name"]
    assert packages == "sqlite3", "sqlite3 must remain the role's only apt package"

    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    shells = " ".join(str(t.get("shell", "")) for t in tasks)
    assert "bunzip2" not in shells, "no external decompressor — use stdlib bz2"
    assert "import bz2" in shells, "decompression must come from Python's stdlib"


def test_restic_is_decompressed_via_a_temp_path_never_onto_the_install_path():
    """A redirect straight onto the install path truncates it before bunzip2
    even runs, so any failure leaves a broken binary where the capture and
    ship scripts expect a working one."""
    tasks_src = (ROLE / "tasks/main.yml").read_text()
    decompress = next(
        t for t in yaml.safe_load(tasks_src) if "bz2" in str(t.get("shell", ""))
    )
    # Anchored to the SSOT variable, not to an expanded path: the folded
    # scalar carries the Jinja reference verbatim, and asserting on it also
    # proves the task never hardcodes the install location.
    path = "{{ node_backup_restic_install_path }}"
    shell = " ".join(decompress["shell"].split())
    assert f"{path}.tmp" in shell, "decompress must write to a temp path"
    assert f"&& mv {path}.tmp {path}" in shell, "then move into place"
    # The install path must appear ONLY as the move's destination — never as a
    # write target, whether by redirect or as the writer's own argument.
    writes = shell.split("&& mv")[0]
    assert path not in writes.replace(f"{path}.tmp", ""), (
        "decompression must never write straight to the install path"
    )
