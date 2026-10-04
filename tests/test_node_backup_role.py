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

from toolkit.features.generator_ansible import AnsibleGenerator

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
        # Supplied by the playbook from `deploy_env`, like the domain above.
        node_backup_env="prod",
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
    # Asserted as "sqlite3 ... .backup over THIS database" rather than as one
    # literal string. The previous form pinned the exact argument order and
    # broke when `-cmd ".timeout"` was inserted between the binary and the path
    # — a test that fails on a change it has no opinion about, while still not
    # noticing if `.backup` were swapped for `.dump`. Both halves are checked
    # here, and neither depends on where the flags sit.
    assert "sqlite3 " in script
    assert '"$SRC_DIR_uptime_kuma/kuma.db"' in script
    assert '".backup ' in script
    assert ".dump" not in script, "`.dump` is a text export, not a consistent binary snapshot"

    # A plain `cp` of the live db defeats the entire point of using .backup —
    # assert the generic copy step explicitly excludes it.
    assert '! -path "./kuma.db"' in script
    assert '! -path "./kuma.db-wal"' in script
    assert '! -path "./kuma.db-shm"' in script


def test_the_snapshot_waits_out_a_contended_database_instead_of_failing():
    """A writer's commit must not be able to abort the whole capture.

    Measured 2026-09-04 on beelink: `.backup` with no timeout hit gitea.db while
    act_runner was committing every second, failed instantly with "database is
    locked", `set -e` aborted before the sentinel, and the ship step then
    (correctly) refused to send a partial backup. Both halves are asserted: the
    timeout must be set BEFORE `.backup` runs, which is what `-cmd` does and
    what a trailing PRAGMA would not, and the retry covers a SQLITE_BUSY
    returned from a backup step rather than from the open.
    """
    script = _render("node-backup-capture.sh.j2", node_backup_sources=RPI3_SOURCES)
    assert '-cmd ".timeout' in script, (
        "`.backup` runs with no busy timeout: a single contended instant aborts "
        "the capture, and nothing ships until the next run"
    )
    assert script.index('-cmd ".timeout') < script.index('".backup '), (
        "the timeout is set after `.backup` — it must precede it to apply"
    )
    assert "for attempt in 1 2 3" in script, "no retry around a contended .backup"


def test_a_failed_snapshot_names_which_database_it_was():
    """`Error: database is locked` names nothing, and the VPS has three.

    On a node with one source that is unhelpful; on the VPS it leaves the reader
    guessing between n8n, authelia and headscale. The service and the file must
    both appear in the failure line.
    """
    # The module's `VPS_SOURCES` carries only headscale, while common.yaml
    # declares three for that host (n8n, authelia, headscale). Rendering all
    # three here rather than reusing the fixture: this test is specifically
    # about telling several sources APART, so a single-source fixture would
    # pass while proving nothing about the case it names.
    three = {
        "n8n": {"pvc": {"namespace": "kubelab", "claim": "n8n-data"}, "sqlite": "database.sqlite"},
        "authelia": {"pvc": {"namespace": "kubelab", "claim": "authelia-data"}, "sqlite": "db.sqlite3"},
        "headscale": {"volume": "headscale_headscale_data", "sqlite": "db.sqlite"},
    }
    script = _render("node-backup-capture.sh.j2", node_backup_sources=three)
    for service, db in (("n8n", "database.sqlite"), ("authelia", "db.sqlite3"), ("headscale", "db.sqlite")):
        assert f"node-backup-capture: {service} ({db})" in script, (
            f"a failed snapshot of {service} would not say so; the operator sees "
            f"only sqlite3's own message, which names no database"
        )


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


def test_prune_script_carries_the_approved_retention_flags_verbatim():
    """The prune unit applies retention since BACKUP-057 Q6 (amended 2026-10-03)."""
    script = _render("node-backup-prune.sh.j2")
    d = _defaults()
    assert d["node_backup_retention_flags"] == (
        "--keep-within 31d --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --max-repack-size 0"
    )
    assert str(d["node_backup_retention_flags"]) in script


def test_restic_check_only_runs_when_the_check_flag_is_passed():
    script = _render("node-backup-ship.sh.j2")
    assert '[ "${1:-}" = "--check" ]' in script
    # `restic check` must be conditional, not unconditional — the whole
    # reason the approved-parameters table separates "weekly" from "per-run".
    m = re.search(r'if \[ "\$RUN_CHECK" -eq 1 \]; then\n(.*?)\nfi', script, re.DOTALL)
    assert m and "$RESTIC check" in m.group(1)


def test_ship_script_reads_credentials_from_files_never_as_a_literal():
    d = _defaults()
    for template in ("node-backup-ship.sh.j2", "node-backup-prune.sh.j2"):
        script = _render(template)
        assert f"cat {d['node_backup_restic_password_file']}" in script, template
        assert f"cat {d['node_backup_r2_access_key_file']}" in script, template
        assert f"cat {d['node_backup_r2_secret_key_file']}" in script, template


def test_credential_file_paths_are_the_same_variable_on_both_sides():
    """The write side (tasks.yml) and the read side (ship script) must
    reference the SAME Jinja variable, not a literal path duplicated in two
    places — the ship_script_path drift guard, applied to all three
    credential files this role writes and then reads back."""
    ship_tpl_src = (TEMPLATES / "node-backup-ship.sh.j2").read_text()
    prune_tpl_src = (TEMPLATES / "node-backup-prune.sh.j2").read_text()
    tasks_src = (ROLE / "tasks/main.yml").read_text()
    for var in (
        "node_backup_restic_password_file",
        "node_backup_r2_access_key_file",
        "node_backup_r2_secret_key_file",
    ):
        ref = "{{ " + var + " }}"
        assert ref in ship_tpl_src, f"{var} not read by the ship script"
        assert ref in prune_tpl_src, f"{var} not read by the prune script"
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
    plays = [p for p in _plays() if _resolve(p["hosts"]) & _backup_hosts_by_location("always-on")]
    assert len(plays) == 1
    assert plays[0].get("ignore_unreachable") is not True
    assert _resolve(plays[0]["hosts"]) == _backup_hosts_by_location("always-on")


def test_on_demand_nodes_ignore_unreachable():
    """Beelink and RPi4 are powered off routinely; dark is the expected state."""
    plays = [p for p in _plays() if _resolve(p["hosts"]) & _backup_hosts_by_location("on-demand")]
    assert len(plays) == 1
    assert plays[0]["ignore_unreachable"] is True
    assert _resolve(plays[0]["hosts"]) == _backup_hosts_by_location("on-demand")


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


def _common() -> dict:
    return yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())


def _generated_inventory() -> dict:
    """The inventory the playbooks run against, built by the generator itself.

    Not a mirror of its naming rule: lesson-356's first coverage test compared
    the patterns to a transformation of themselves and could only pass. Since
    BACKUP-062 the plays target derived groups, so the only faithful answer to
    "which hosts does this play reach" is the generator's own output.
    """
    common = _common()
    return AnsibleGenerator()._build_inventory(common["networking"], backup_sources=common["backup"]["sources"])


def _resolve(pattern: str) -> set[str]:
    """Ansible's host-pattern semantics for the forms used here: `a:b` / `a,b`
    union, `a:&b` intersection, `a:!b` exclusion, each term a group or host."""
    children = _generated_inventory()["all"]["children"]
    every = {h for group in children.values() for h in group["hosts"]}

    def term(name: str) -> set[str]:
        if name == "all":
            return every
        if name in children:
            return set(children[name]["hosts"])
        return {name} & every

    hosts: set[str] = set()
    for raw in (t for t in re.split(r"[:,]", pattern) if t):
        if raw.startswith("&"):
            hosts &= term(raw[1:])
        elif raw.startswith("!"):
            hosts -= term(raw[1:])
        else:
            hosts |= term(raw)
    return hosts


def _backup_hosts_by_location(location: str) -> set[str]:
    """Backup-source hostnames of one ADR-028 class, read from common.yaml."""
    net = _common()["networking"]
    out = set()
    for key in _common()["backup"]["sources"]:
        node = net["vps"] if key == "vps" else net["nodes"][key]
        if node["location"] == location:
            out.add(node.get("hostname", key))
    return out


def test_every_play_reaches_at_least_one_host():
    """A pattern that matches nothing is a WARNING and exit 0 (lesson-356), so
    an empty resolution is the failure this pipeline must never report green."""
    for play in _plays():
        assert _resolve(play["hosts"]), f"play {play['name']!r} ({play['hosts']!r}) matches no host"


def test_the_plays_together_reach_exactly_the_nodes_with_declared_sources():
    """No backup node dropped, and no other node reached (the #1943 defect:
    `hosts: all` ran the ship unit on ace1, ace2, gcp1 and jetson)."""
    reached = set().union(*(_resolve(p["hosts"]) for p in _plays()))
    assert reached == _backup_hosts_by_location("always-on") | _backup_hosts_by_location("on-demand")
    assert reached, "backup.sources declares no node"


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
        "sqlite3 must remain the role's only apt package — counted across every apt task, not just the first one"
    )

    tasks = [t for f in ("main.yml", "restic.yml") for t in yaml.safe_load((ROLE / "tasks" / f).read_text())]
    shells = " ".join(str(t.get("shell", "")) for t in tasks)
    assert "bunzip2" not in shells, "no external decompressor — use stdlib bz2"
    assert "import bz2" in shells, "decompression must come from Python's stdlib"


def test_restic_is_decompressed_via_a_temp_path_never_onto_the_install_path():
    """A redirect straight onto the install path truncates it before bunzip2
    even runs, so any failure leaves a broken binary where the capture and
    ship scripts expect a working one."""
    # The install lives in the file node_backup shares with dev_node (BACKUP-071).
    tasks_src = (ROLE / "tasks/restic.yml").read_text()
    decompress = next(t for t in yaml.safe_load(tasks_src) if "bz2" in str(t.get("shell", "")))
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
    assert path not in writes.replace(f"{path}.tmp", ""), "decompression must never write straight to the install path"


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
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
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
    assert len(failed_ship) == 1, f"expected exactly one failed-shutdown-ship branch, found {len(failed_ship)}"

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
            f"{path} survives the boot read-back, so the next boot can read this boot's outcome as its own"
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

    capture_at = next(i for i, line in enumerate(stops) if str(_defaults()["node_backup_capture_script_path"]) in line)
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
        assert "schedule_state" in str(task["when"]), f"task {task.get('name')!r} is not gated on the requested state"


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
        "the integrity-check timer is not managed alongside the ship timer, so a disarm leaves half a schedule running"
    )


# --- BACKUP-058: `init` is reachable from exactly one exit code -------------


def test_init_is_gated_on_restic_exit_code_10_only():
    """`restic init` sits inside the `10)` arm of the snapshots exit-code case.

    Exit 10 is restic's "repository does not exist", measured on R2 with the
    fleet's restic 0.19.1 (specs/archive/BACKUP-058-no-silent-reinit, 2026-09-30).
    Any other placement of `init` is the defect this spec fixed: a deleted
    history re-initialised silently. The behaviour itself is exercised in
    tests/test_node_backup_ship_script.py; this pins the shape it relies on.
    """
    script = _render("node-backup-ship.sh.j2")
    code = [line for line in script.splitlines() if not line.lstrip().startswith("#")]
    init_lines = [i for i, line in enumerate(code) if re.search(r"\$RESTIC init\b", line)]
    assert len(init_lines) == 1, "exactly one `restic init` call"
    arm = next(i for i in range(init_lines[0], -1, -1) if re.match(r"\s*\d+\)", code[i]))
    assert code[arm].strip() == "10)", f"`init` must sit in the `10)` arm, found under {code[arm].strip()!r}"


def test_the_capture_keeps_the_staging_dir_private_after_it_recreates_it():
    """The role creates the staging dir 0700; the capture `rm -rf`s and recreates it.

    Under root's default umask 022 the recreated dir was 0755 and the staged
    database copies 0644, readable by any local user until the next deploy put
    the mode back. Found by `make backup ENV=prod` reporting `changed` on
    "Ensure staging directory exists" after a scheduled capture (BACKUP-058
    deploy, 2026-09-30). The umask lives in the script, not the unit, because
    the shutdown unit runs the script from ExecStop too.
    """
    script = _render("node-backup-capture.sh.j2", node_backup_location="on-demand")
    lines = [line.strip() for line in script.splitlines()]
    assert "umask 077" in lines, "the capture recreates the staging dir with the default umask"
    assert lines.index("umask 077") < lines.index('rm -rf "$STAGING"')


def test_the_restic_version_probe_runs_in_check_mode() -> None:
    """A `command` is skipped under --check, so the probe's stdout is empty and the
    download that keys on it reports `changed` on every node: `make backup CHECK=1`
    then claims every node needs restic. The probe only reads, so it runs anyway.
    """
    tasks = yaml.safe_load((ROLE / "tasks/restic.yml").read_text())
    probe = next(t for t in tasks if t.get("register") == "node_backup_restic_installed")
    assert probe.get("check_mode") is False


# --- BACKUP-057 Q6 (amended 2026-10-03): the prune is a unit of its own ------


def _code_lines(script: str) -> list[str]:
    return [line for line in script.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def test_the_ship_no_longer_prunes_and_unlocks_before_backup():
    """A refused DELETE retries for ~15 minutes, past the ship's timeout, so the
    ship must never reach one. It unlocks first because a killed prune leaves an
    exclusive lock that restic 0.19.1 never treats as stale on its own."""
    code = _code_lines(_render("node-backup-ship.sh.j2"))
    assert not any(re.search(r"\$RESTIC forget\b", line) for line in code), "the ship still runs forget"
    unlock = next(i for i, line in enumerate(code) if re.search(r"\$RESTIC unlock\b", line))
    backup = next(i for i, line in enumerate(code) if re.search(r"\$RESTIC backup\b", line))
    assert unlock < backup


def test_the_prune_unit_fails_loudly_within_its_own_bound():
    defaults = _defaults()
    unit = _render("node-backup-prune.service.j2")
    lines = _directive_lines(unit)
    assert "Type=oneshot" in lines
    assert "OnFailure=kubelab-notify@%n.service" in lines
    assert f"ExecStart={defaults['node_backup_prune_script_path']}" in lines
    assert f"TimeoutStartSec={defaults['node_backup_prune_timeout']}" in lines


def test_the_prune_bound_covers_the_refusals_the_spec_names():
    """Q6's arithmetic: about 15 minutes per batch of refused packs, batches as
    wide as the S3 connection count, and the bound sized for ~80 packs."""
    defaults = _defaults()
    batches = int(defaults["node_backup_prune_timeout"]) // 900
    assert batches * int(defaults["node_backup_prune_connections"]) >= 80


def test_the_prune_carries_the_ship_s_memory_cap():
    """rpi3 is the monitoring of record; prune is the heavier restic operation."""
    for template in ("node-backup-ship.service.j2", "node-backup-prune.service.j2"):
        lines = _directive_lines(_render(template, node_backup_memory_max="128M"))
        assert "MemoryMax=128M" in lines, template
        assert "MemorySwapMax=0" in lines, template


def test_a_ship_queued_during_a_prune_waits_for_it():
    defaults = _defaults()
    for check in (False, True):
        lines = _directive_lines(_render("node-backup-ship.service.j2", node_backup_check=check))
        assert f"After={defaults['node_backup_prune_service_name']}" in lines


def test_the_prune_waits_out_a_running_ship():
    """`--retry-lock` must outlast the longest ship, or a prune that starts
    mid-ship fails on the lock and notifies about nothing."""
    script = _render("node-backup-prune.sh.j2")
    retry = re.search(r"--retry-lock (\d+)m\b", script)
    assert retry
    ship = _render("node-backup-ship.service.j2")
    ceiling = int(re.search(r"^TimeoutStartSec=(\d+)$", ship, re.M).group(1))
    assert int(retry.group(1)) * 60 >= ceiling


def test_the_prune_timer_is_daily_and_persistent():
    lines = _directive_lines(_render("node-backup-prune.timer.j2"))
    assert f"OnCalendar={_defaults()['node_backup_prune_schedule']}" in lines
    assert "Persistent=true" in lines


def test_the_role_installs_and_arms_the_prune():
    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    templated = {t["template"]["src"]: t["template"]["dest"] for t in tasks if "template" in t}
    assert templated["node-backup-prune.sh.j2"] == "{{ node_backup_prune_script_path }}"
    assert templated["node-backup-prune.service.j2"] == "/etc/systemd/system/{{ node_backup_prune_service_name }}"
    assert templated["node-backup-prune.timer.j2"] == "/etc/systemd/system/{{ node_backup_prune_timer_name }}"
    armed = [
        t["systemd"]
        for t in tasks
        if "systemd" in t and t["systemd"].get("name") == "{{ node_backup_prune_timer_name }}"
    ]
    assert armed and armed[0].get("enabled") is True and armed[0].get("state") == "started"


def test_every_rendered_unit_passes_systemd_analyze_verify(tmp_path):
    """The scripts are stood in by /bin/true: verify checks that ExecStart is
    executable, and the real scripts only exist on a node."""
    import shutil
    import subprocess

    if shutil.which("systemd-analyze") is None:
        import pytest

        pytest.skip("systemd-analyze is not installed")
    paths = {
        "node_backup_ship_script_path": "/bin/true",
        "node_backup_prune_script_path": "/bin/true",
    }
    units = {
        "node-backup-ship.service": _render("node-backup-ship.service.j2", **paths),
        "node-backup-prune.service": _render("node-backup-prune.service.j2", **paths),
        "node-backup-prune.timer": _render("node-backup-prune.timer.j2"),
        "kubelab-notify@.service": "[Service]\nType=oneshot\nExecStart=/bin/true\n",
        "node-backup-capture.service": "[Service]\nType=oneshot\nExecStart=/bin/true\n",
    }
    for name, text in units.items():
        (tmp_path / name).write_text(text)
    # Every unit the role renders; the capture unit is only a stub for `Wants=`.
    targets = [str(tmp_path / n) for n in units if n != "node-backup-capture.service"]
    proc = subprocess.run(
        ["systemd-analyze", "verify", "--man=no", *targets],
        capture_output=True,
        text=True,
        env={"SYSTEMD_UNIT_PATH": f"{tmp_path}:", "PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 0, proc.stderr


def test_the_schedule_arms_the_prune_and_reports_its_failures() -> None:
    play = _schedule_playbook()
    assert "node-backup-prune.timer" in play["vars"]["backup_timers"]
    commands = [
        t["ansible.builtin.command"].get("cmd", "") if isinstance(t.get("ansible.builtin.command"), dict) else ""
        for t in play["tasks"]
    ]
    assert any("node-backup-prune.service" in c and "journalctl" in c for c in commands), (
        "AC3 reads each node's prune failures over seven days; nothing in the schedule playbook reports them"
    )
    # A node without the unit also answers "no failures": the report must say
    # it measured nothing there, not print the same 0 as a clean week.
    assert any("node-backup-prune.service" in c and "LoadState" in c for c in commands), (
        "the report cannot tell a clean week from a node where the prune unit was never installed"
    )
    report = next(t for t in play["tasks"] if t.get("name") == "Report the prune unit's failures")
    assert "not installed" in report["ansible.builtin.debug"]["msg"]
