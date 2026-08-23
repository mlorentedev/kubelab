"""Unit tests for the node_backup role's capture/ship scripts — BACKUP-044 Part 3.

Pure render + assertion tests: NO SSH, no live node, no real restic/docker
call. Runs under ``make test`` (marker-less -> collected by ``-m "not e2e and
not infra"``), mirroring tests/test_node_notify_role.py's pattern.

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


def _apt_packages() -> set[str]:
    """Every package the role installs, across ALL apt tasks.

    Read from tasks/main.yml as YAML rather than substring-matched, so a
    package named only inside a comment cannot satisfy it — and gathered from
    every apt task rather than the first, so a second apt task added later
    cannot slip a dependency in behind a guard that only ever looked at one
    (both halves of lesson-357).
    """
    packages: set[str] = set()
    for task in yaml.safe_load((ROLE / "tasks/main.yml").read_text()):
        if "apt" not in task:
            continue
        name = task["apt"]["name"]
        packages.update([name] if isinstance(name, str) else name)
    return packages


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
        # Supplied by the playbook, not by the role's defaults — deliberately, so
        # StrictUndefined catches a playbook that forgot it. An empty default
        # would render `https:///api/push/<token>`: structurally valid, reaching
        # nobody, and surfacing 6h later as a coverage monitor blaming the backup
        # (#1221). Restated here for the same reason as the two values above it.
        node_backup_heartbeat_domain="status.kubelab.live",
        # ADR-028 class, supplied by the playbook from `networking.*.location`
        # like the three above it. The capture script branches on it to read
        # back the shutdown receipt, which only exists on on-demand nodes —
        # they are the ones that power off. Defaulting it in the ROLE would
        # hide a playbook that forgot to pass it, which is what StrictUndefined
        # is here to catch.
        node_backup_location="on-demand",
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


def _directive_lines(unit: str) -> list[str]:
    """Non-comment, non-blank lines of a rendered unit file.

    Checking a raw substring against the whole file is a false-positive trap
    the moment prose ABOUT a directive (a comment explaining why `Requires=`
    was rejected, say) contains that directive's own name. Restricting the
    check to actual directive lines is what makes the assertion mean what it
    says.
    """
    return [line for line in unit.splitlines() if line.strip() and not line.strip().startswith("#")]


def test_ship_unit_does_not_hard_require_capture():
    """`Requires=` would re-run capture on every ship start — both are oneshots
    without RemainAfterExit — which would have decided Part 4's timer topology
    from here. The sentinel covers the failure instead; `Wants=` is what Part 4
    settled on, and this asserts the harder alternatives were not used too."""
    lines = _directive_lines(_render("node-backup-ship.service.j2"))
    assert not any(line.startswith(("Requires=", "BindsTo=")) for line in lines)
    assert any(line.startswith("Wants=") for line in lines)


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


# --- the trigger model (Part 4) ----------------------------------------------
#
# `node_backup_location` is never role-defaulted (playbook-computed from the
# ADR-028 SSOT, tests/test_node_location_axis.py) -- every render below must
# pass it explicitly, which is StrictUndefined doing its job: a class this
# consequential must never resolve by accident.


def test_always_on_timer_is_wall_clock_and_survives_a_missed_window():
    timer = _render("node-backup-ship.timer.j2", node_backup_location="always-on")
    lines = _directive_lines(timer)
    assert any(line.startswith("OnCalendar=") for line in lines)
    assert "Persistent=true" in lines
    assert not any(line.startswith(("OnUnitActiveSec=", "OnBootSec=")) for line in lines)


def test_on_demand_timer_is_an_interval_and_does_not_survive_a_missed_window():
    """Persistent=true here would treat every boot as a missed window and
    re-run a catch-up the boot capture already covered, seconds earlier and
    against a quiescent database (see node-backup-capture.service.j2)."""
    timer = _render("node-backup-ship.timer.j2", node_backup_location="on-demand")
    lines = _directive_lines(timer)
    assert any(line.startswith("OnUnitActiveSec=") for line in lines)
    assert any(line.startswith("OnBootSec=") for line in lines)
    assert not any(line.startswith("OnCalendar=") for line in lines)
    assert "Persistent=true" not in lines


def test_capture_unit_is_ordered_before_dockerd_only_on_demand():
    """R-C (verification.md): boot-ordering only matters for a node that is
    routinely power-cycled. Forcing it on an always-on node buys nothing and
    adds a boot-path dependency it never needed."""
    on_demand = _render("node-backup-capture.service.j2", node_backup_location="on-demand")
    always_on = _render("node-backup-capture.service.j2", node_backup_location="always-on")
    assert any(line.startswith("Before=docker.service") for line in _directive_lines(on_demand))
    assert "[Install]" in on_demand
    assert not any(line.startswith("Before=") for line in _directive_lines(always_on))
    assert "[Install]" not in always_on


def test_shutdown_unit_targets_the_unit_that_actually_stops_the_writer():
    """Ordering against a fleet-wide `docker.service` constant would race
    Beelink's kubelab-compose.service, which stops itself before dockerd does
    on its own After=docker.service -- see node-backup-shutdown.service.j2."""
    beelink = _render(
        "node-backup-shutdown.service.j2",
        inventory_hostname="beelink",
        node_backup_shutdown_after="kubelab-compose.service",
    )
    rpi4 = _render(
        "node-backup-shutdown.service.j2",
        inventory_hostname="rpi4",
        node_backup_shutdown_after="docker.service",
    )
    assert any(line.startswith("After=kubelab-compose.service") for line in _directive_lines(beelink))
    assert any(line.startswith("After=docker.service") for line in _directive_lines(rpi4))


def test_shutdown_unit_ships_best_effort_but_captures_unconditionally():
    """No `-` on capture: if it fails, ship's own sentinel check already
    refuses a partial backup, so there is nothing left worth attempting. `-`
    on ship: an unreachable R2 at the moment of poweroff must never block
    shutdown."""
    unit = _render(
        "node-backup-shutdown.service.j2",
        node_backup_shutdown_after="docker.service",
    )
    lines = _directive_lines(unit)
    exec_stops = [line for line in lines if line.startswith("ExecStop=")]
    capture_path = _defaults()["node_backup_capture_script_path"]
    assert f"ExecStop={capture_path}" in exec_stops
    assert any(line.startswith("ExecStop=-") and "ship" in line for line in exec_stops)


def test_weekly_check_service_passes_the_flag_the_frequent_one_omits():
    checked = _render("node-backup-ship.service.j2", node_backup_check=True)
    frequent = _render("node-backup-ship.service.j2", node_backup_check=False)
    exec_start = next(line for line in _directive_lines(checked) if line.startswith("ExecStart="))
    assert exec_start.endswith(" --check")
    exec_start = next(line for line in _directive_lines(frequent) if line.startswith("ExecStart="))
    assert not exec_start.endswith(" --check")


def test_weekly_check_timer_is_persistent_on_both_node_classes():
    """Unlike the main timer, Persistent=true here is not location-dependent:
    a missed weekly check has no boot-time equivalent already covering it,
    on either node class."""
    timer = _render("node-backup-ship-check.timer.j2")
    lines = _directive_lines(timer)
    assert "OnCalendar=weekly" in lines
    assert "Persistent=true" in lines


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
    assert _apt_packages() == {"sqlite3"}, (
        "sqlite3 must remain the role's only apt package — counted across every "
        "apt task, not just the first one"
    )

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


def test_a_failing_ship_can_say_why():
    """Every failure looked like a timeout, and none said why.

    Measured 2026-08-22 by injecting two real failures on beelink — a
    blackholed R2 endpoint and an invalid credential. BOTH surfaced as systemd
    `Result=timeout` after ~180s with **no restic error line in the journal at
    all**. The operator got "node-backup-ship.service failed" and a log tail
    that ended mid-run.

    Two independent causes, and the fix needs both:

    - restic's `--stuck-request-timeout` defaults to 5m, which outlives the
      unit's useful life: systemd killed it before restic reached its own error
      path, so `TimeoutStartSec=600` never applied either.
    - The `snapshots` probe discarded stderr. That probe is the FIRST thing to
      touch R2, so it is exactly where a bad credential is discovered — and its
      stderr was the only explanation the run would ever produce.
    """
    script = _render("node-backup-ship.sh.j2")
    assert "--stuck-request-timeout" in script, (
        "restic's 5m default outlives the unit; systemd kills it before it can "
        "report, so every failure arrives as an unexplained timeout"
    )
    probe = next(line for line in script.splitlines() if "snapshots -q" in line)
    assert "2>&1" not in probe, (
        f"the repository probe discards stderr: {probe.strip()!r}. It is the first "
        f"call to reach R2, so its stderr is where a bad credential or an "
        f"unreachable endpoint explains itself — and the only place it ever will."
    )


def test_the_request_timeout_leaves_room_under_the_unit_ceiling():
    """A request timeout above TimeoutStartSec puts the old defect straight back.

    The whole point is that restic reaches its error path *while the unit is
    still alive to log it*. Compared numerically rather than by eye, because
    these live in two different files and drift silently.
    """
    import re

    defaults = _defaults()
    stuck = str(defaults["node_backup_stuck_request_timeout"])
    seconds = int(re.match(r"^(\d+)s$", stuck).group(1))
    unit = _render("node-backup-ship.service.j2")
    ceiling = int(re.search(r"^TimeoutStartSec=(\d+)$", unit, re.M).group(1))
    assert seconds < ceiling, (
        f"stuck-request-timeout is {seconds}s against TimeoutStartSec={ceiling}s. "
        f"systemd would kill the run before restic could explain itself, which is "
        f"the defect this setting exists to remove."
    )


def test_the_capture_ceiling_clears_the_overrun_that_was_measured():
    """120s was not enough at the one moment capture matters — cold boot.

    rpi4, 2026-08-23: capture started 08:46:11, was still running at 08:48:11,
    and systemd killed it (`Failed with result 'timeout'`, SIGTERM). The retry
    two minutes later copied the same 29 MB in ONE second. So the ceiling was
    below what a booting Pi needs while being nowhere near what the work costs.

    Guarded numerically, and deliberately against the OBSERVED overrun rather
    than a round number: the next person tuning this has to clear the event
    that caused it, not merely change the digits. The value is read from the
    role default so the unit cannot drift from the knob that documents it.
    """
    import re

    MEASURED_OVERRUN_SECONDS = 120

    raw = str(_defaults()["node_backup_capture_timeout"])
    match = re.match(r"^(\d+)s$", raw)
    assert match, f"node_backup_capture_timeout is not a plain seconds value: {raw!r}"
    configured = int(match.group(1))

    assert configured > MEASURED_OVERRUN_SECONDS, (
        f"capture TimeoutStartSec is {configured}s, at or under the {MEASURED_OVERRUN_SECONDS}s "
        f"that was already measured overrunning on a cold boot. A run killed at boot is the "
        f"one that covers the previous session on nodes that lose power without shutting down."
    )

    unit = _render("node-backup-capture.service.j2", node_backup_location="on-demand")
    assert f"TimeoutStartSec={raw}" in unit, (
        "the capture unit does not take its ceiling from node_backup_capture_timeout; "
        "a literal here drifts from the default that explains it"
    )


# --- BACKUP-044 AC5: telling two absences apart ----------------------------


def _capture_receipt_block() -> str:
    """The boot read-back, comments stripped.

    Every branch below is explained by a comment that quotes the other
    branches, so a raw match on the rendered file would find `>&2` in the prose
    about stderr and pass on a script that never writes to it.
    """
    script = _render("node-backup-capture.sh.j2", node_backup_location="on-demand")
    code = "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )
    start = code.index("previous shutdown snapshot")
    return code[code.rindex("if ", 0, start) : code.index("STAGING=", start)]


def _branch_bodies(block: str) -> list[str]:
    """The block's shell branches, split on the keyword at the START of a line.

    Not `block.split("elif")`: that matches the word wherever it appears —
    inside an `echo`, a path, a message — and manufactures branches out of
    prose. Requiring it to open a line is what makes the split mean what it
    says, the same reasoning `_directive_lines` applies to unit files.
    """
    bodies: list[list[str]] = [[]]
    for line in block.splitlines():
        first = line.strip().split(" ", 1)[0].rstrip(";")
        if first in {"if", "elif", "else", "fi"}:
            bodies.append([])
        else:
            bodies[-1].append(line)
    return ["\n".join(b) for b in bodies if any(line.strip() for line in b)]


def test_an_unclean_power_off_is_not_reported_as_a_failed_backup():
    """The operator kills the homelab with a smart plug, so ExecStop never runs.

    Absence of a receipt therefore has two meanings that used to print the
    same: the shutdown sequence ran and failed to ship (a real defect), or no
    shutdown sequence ran at all (Tuesday). The second is the normal path on
    this fleet, and reporting it as `the last power-off did not ship` on every
    boot is what emptied the line of meaning.

    The attempt marker is what separates them, so the branch that has no
    marker must NOT reach stderr -- `OnFailure=` and the operator's eye both
    read stderr as the failure channel.
    """
    block = _capture_receipt_block()

    assert "node-backup-shutdown.attempted" in block, (
        "the read-back does not consult the attempt marker, so it cannot tell a "
        "failed shutdown ship from a power cut that never ran one"
    )

    bodies = _branch_bodies(block)

    # Selected by what each branch SAYS, not by where it sits. A positional
    # read (`branches[1]`) encodes the branch count as well as the property,
    # so adding a fourth case later fails this test for a reason that has
    # nothing to do with what it guards — raised on #1318 and correct in
    # substance, though not in mechanism: the split ran on comment-stripped
    # text, so a comment containing `elif` was never the risk.
    unclean = [b for b in bodies if "unclean" in b]
    failed_ship = [b for b in bodies if "did NOT ship" in b]

    assert len(unclean) == 1, f"expected exactly one power-cut branch, found {len(unclean)}"
    assert len(failed_ship) == 1, (
        f"expected exactly one failed-shutdown-ship branch, found {len(failed_ship)}"
    )

    assert ">&2" not in unclean[0], (
        "the no-shutdown-sequence branch writes to stderr. On a smart-plug fleet that "
        "fires on every single boot, which is the alarm fatigue this change removes."
    )
    assert ">&2" in failed_ship[0], (
        "the marker-without-receipt branch does NOT write to stderr, so the one case "
        "that is a real failure has become as quiet as the normal one"
    )


def test_the_read_back_runs_once_per_boot_not_once_per_run():
    """Ship pulls capture in via Wants= on every tick, so this is not a boot-only script.

    Measured on rpi4 2026-08-23: the read-back printed at 08:46 (boot) and
    again at 08:50, when ship pulled capture in. The answer cannot change
    between those two, so the second one is noise by construction.
    """
    block = _capture_receipt_block()
    flag = str(_defaults()["node_backup_boot_check_flag"])

    assert flag.startswith("/run/"), (
        f"the boot flag is at {flag!r}, off tmpfs — it would survive the reboot it is "
        f"meant to be reset by, and the read-back would never run again"
    )
    assert flag in block, "the read-back is not scoped by the boot flag"


def test_the_boot_read_back_clears_what_it_read():
    """A receipt that outlives its boot is read as proof of the WRONG power-off.

    The previous revision left clearing to the shutdown unit's first ExecStop
    line. That unit does not run on a power cut — the whole reason this control
    exists — so a receipt from the last clean reboot would still be sitting
    there at the next boot and would be reported as a successful shutdown ship
    that never happened.
    """
    block = _capture_receipt_block()
    receipt = str(_defaults()["node_backup_shutdown_receipt"])
    marker = str(_defaults()["node_backup_shutdown_attempt_marker"])

    removal = [line for line in block.splitlines() if line.strip().startswith("rm ")]
    assert removal, "the boot read-back never clears the files it just read"
    cleared = " ".join(removal)
    for path in (receipt, marker):
        assert path in cleared, (
            f"{path} survives the boot read-back, so the next boot can read this "
            f"boot's outcome as its own"
        )


def test_the_shutdown_unit_marks_its_attempt_before_it_can_fail():
    """The marker means 'this sequence started', so it must precede what may fail.

    Written after capture or ship, it would only ever exist when they
    succeeded — which is what the receipt already says, leaving the failure
    case indistinguishable from the power cut all over again.
    """
    unit = _render(
        "node-backup-shutdown.service.j2",
        node_backup_location="on-demand",
        inventory_hostname="rpi4",
        node_backup_shutdown_after="docker.service",
    )
    stops = [line for line in _directive_lines(unit) if line.startswith("ExecStop=")]

    marker = str(_defaults()["node_backup_shutdown_attempt_marker"])
    touch_at = next((i for i, line in enumerate(stops) if marker in line), None)
    assert touch_at is not None, "the shutdown unit never records that it attempted a ship"

    capture_at = next(
        i for i, line in enumerate(stops) if str(_defaults()["node_backup_capture_script_path"]) in line
    )
    assert touch_at < capture_at, (
        f"the attempt marker is written at ExecStop position {touch_at}, after capture at "
        f"{capture_at}. A marker that only appears on success cannot distinguish failure."
    )


# --- backup-schedule: the teardown verb AC9 needed and did not have ---------


def _schedule_playbook() -> dict:
    import yaml

    path = REPO / "infra/ansible/playbooks/backup-schedule.yml"
    assert path.exists(), "backup-schedule.yml is missing"
    return yaml.safe_load(path.read_text(encoding="utf-8"))[0]


def test_reporting_the_schedule_cannot_change_it() -> None:
    """`make backup-schedule NODE=x` with no STATE must be read-only.

    An operator runs this to find out whether a node's backups are armed —
    often precisely because something looks wrong. A default that mutates
    would arm the timer as a side effect of asking, and destroy the state
    being investigated. That is the shape of the AC9 harvest itself: evidence
    first, teardown second, and a tool that does both at once has no first.
    """
    play = _schedule_playbook()
    mutating = [
        task
        for task in play["tasks"]
        if "ansible.builtin.systemd" in task or task.get("name", "").startswith("Put the timers")
    ]
    assert mutating, "the playbook has no task that changes the timers at all"

    for task in mutating:
        assert "when" in task, (
            f"task {task.get('name')!r} changes timer state unconditionally, so a "
            f"report-only invocation would mutate the thing it was asked to look at"
        )
        assert "schedule_state" in str(task["when"]), (
            f"task {task.get('name')!r} is not gated on the requested state"
        )


def test_an_unrecognised_state_is_refused_rather_than_ignored() -> None:
    """Silently ignoring STATE=stoped reports success and changes nothing.

    The operator reads "completed successfully" as "the timer is stopped", and
    the divergence surfaces hours later as a backup that did happen or one
    that did not. Exactly the failure `make backup ENV=prod CHECK=1` had: make
    has no notion of an unknown variable, so the only signal was the absence
    of one.
    """
    play = _schedule_playbook()
    guard = next(
        (t for t in play["tasks"] if "ansible.builtin.assert" in t and "state" in t.get("name", "").lower()),
        None,
    )
    assert guard is not None, "no task rejects an unrecognised STATE"

    conditions = str(guard["ansible.builtin.assert"]["that"])
    for allowed in ("started", "stopped"):
        assert allowed in conditions, f"{allowed!r} is not in the accepted set"


def test_both_timers_move_together() -> None:
    """Disarming only the ship timer leaves the node in a state nothing declares.

    The weekly integrity check would keep running against a repository nobody
    is shipping to, and a later `is-active` on one timer would report a
    schedule that is half there.
    """
    play = _schedule_playbook()
    timers = play["vars"]["backup_timers"]
    assert "node-backup-ship.timer" in timers
    assert "node-backup-ship-check.timer" in timers, (
        "the integrity-check timer is not managed alongside the ship timer, so a "
        "disarm leaves half a schedule running"
    )
