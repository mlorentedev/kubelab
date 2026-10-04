"""OPS-024 (#1657): the CI node reclaims its own Docker residue, and never a declared volume.

act_runner 0.2.13 leaves a job's two named volumes behind whenever the job is
cancelled during setup or the runner is lost mid-job (its cleanup is chained behind
`startContainer()`), and no setting in that version changes it. So the residue is
bounded instead, by the `node_maintenance` timer running the same module the
emergency `make node-reclaim` uses. These tests hold the design in place:

  - the reclaim is wired into BOTH implementations (timer script, `make maintain`)
    on the CI node, and the role ships the module itself, not a copy of its logic;
  - no volume common.yaml's `backup` block declares can ever be planned, even one
    that looks exactly like residue, and the protection is what saves it, not luck;
  - a reclaim failure, or a disk still above the threshold after cleanup, makes the
    run exit non-zero, which is what fires `OnFailure=kubelab-notify@`.

Each was proven by mutation when written (lesson in docs/lessons/ops/): remove the
invocation, drop the protected check, widen the name pattern, or drop the final
`exit 1`, and a test below goes red.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml
from jinja2 import Environment, StrictUndefined

from tests.node_maintenance_role import COMMON, REPO, render_script, resolve_defaults, tasks
from toolkit.features import docker_reclaim
from toolkit.features.docker_reclaim import (
    _RECLAIMABLE_VOLUME,
    ReclaimRefused,
    Volume,
    plan_reclaim,
    protected_volumes,
)

CI_HOST = ["platform_nodes", "docker_hosts"]
GATEWAY = ["gateway_nodes", "docker_hosts"]
HUB = ["hub"]

MODULE = REPO / "toolkit" / "features" / "docker_reclaim.py"
NOW = datetime(2026, 10, 4, 4, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=30)

BACKUP: dict[str, Any] = yaml.safe_load(COMMON.read_text(encoding="utf-8"))["backup"]


def _declared_volume_names(block: Any) -> set[str]:
    """Every volume the SSOT names, collected independently of `protected_volumes`.

    Any `volume:` value anywhere under `backup.sources`, and every key under
    `backup.excluded.<node>` that is not a `pvc:` ruling. Written as a walk rather
    than by calling the function under test, so the two can disagree.
    """
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "volume" and isinstance(value, str):
                    found.add(value)
                walk(value)

    walk(block.get("sources"))
    for rulings in (block.get("excluded") or {}).values():
        found |= {name for name, ruling in rulings.items() if not (isinstance(ruling, dict) and "pvc" in ruling)}
    return found


DECLARED = _declared_volume_names(BACKUP)

# Job volumes as act_runner names them, measured on the Beelink 2026-10-04.
LEAKED = (
    "GITEA-ACTIONS-TASK-1313_WORKFLOW-publish-drive_JOB-publish",
    "GITEA-ACTIONS-TASK-1313_WORKFLOW-publish-drive_JOB-publish-env",
    "GITEA-ACTIONS-TASK-2023_WORKFLOW-CI_JOB-lint",
    "GITEA-ACTIONS-TASK-2023_WORKFLOW-CI_JOB-lint-env",
)


def test_the_ssot_declares_what_these_tests_rely_on() -> None:
    """Anti-vacuity: an empty or shrunken declaration would make every
    "never planned" assertion below pass trivially."""
    assert {
        "uptime_kuma_data",
        "coredns_pihole_data",
        "headscale_headscale_data",
        "act_runner_data",
        "act-toolcache",
        "github_runner_data",
        "github_runner_toolcache",
    } <= DECLARED
    assert protected_volumes(BACKUP) == frozenset(DECLARED)


# --- invariant 2: wired in, on the CI node ------------------------------------


def test_the_ci_node_reclaims_daily_and_the_others_do_not_reclaim() -> None:
    ci, gateway = resolve_defaults(CI_HOST), resolve_defaults(GATEWAY)
    assert ci["maintenance_docker_reclaim"] is True
    assert ci["maintenance_timer_schedule"] == "daily"
    assert gateway["maintenance_docker_reclaim"] is False
    assert gateway["maintenance_timer_schedule"] == "weekly"


def test_the_timer_script_runs_the_reclaim_between_the_two_prunes() -> None:
    script = render_script(CI_HOST)
    invocation = re.search(r"python3 (\S+) --apply \\\s+--declaration (\S+) \\\s+--min-age-hours (\d+)", script)
    assert invocation, "the timer script no longer runs the reclaim with --apply"
    defaults = resolve_defaults(CI_HOST)
    assert invocation.group(1) == defaults["maintenance_docker_reclaim_script"]
    assert invocation.group(2) == defaults["maintenance_backup_declaration_file"]
    assert int(invocation.group(3)) == defaults["maintenance_docker_reclaim_min_age_hours"]
    # A failure is recorded, not swallowed.
    assert 'FAILURES="$FAILURES docker-reclaim"' in script
    # Stopped containers go first so their volumes read as unheld; images after.
    assert (
        script.index("docker container prune -f") < invocation.start() < script.index("docker image prune -af")
    )


def _run_docker_section(tmp_path: Path, group_names: list[str], reclaim_rc: int) -> tuple[list[str], str]:
    """Execute the rendered script's Docker section against logging stubs.

    Text matching alone cannot tell a running invocation from a disabled one
    (`if ! true || false && python3 ...` still contains the command), so this
    runs the section and reads what was actually called, in order.
    """
    script = render_script(group_names)
    section = script[script.index("# Docker cleanup") : script.index("# K3s cleanup")]
    log = tmp_path / "calls.log"
    for tool, rc in (("docker", 0), ("python3", reclaim_rc)):
        stub = tmp_path / tool
        stub.write_text(f'#!/bin/sh\necho "{tool} $*" >> {log}\nexit {rc}\n')
        stub.chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", f'set -euo pipefail\nFAILURES=""\n{section}\necho "FAILURES=$FAILURES"'],
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return (log.read_text().splitlines() if log.exists() else []), result.stdout


def test_the_timer_actually_calls_the_reclaim_in_order(tmp_path: Path) -> None:
    calls, out = _run_docker_section(tmp_path, CI_HOST, reclaim_rc=0)
    reclaim = [i for i, c in enumerate(calls) if c.startswith("python3 /opt/kubelab-docker-reclaim.py --apply")]
    assert len(reclaim) == 1, calls
    assert calls.index("docker container prune -f") < reclaim[0] < calls.index("docker image prune -af")
    assert "FAILURES=\n" in out or out.rstrip().endswith("FAILURES=")


def test_a_failed_reclaim_is_recorded_and_the_cleanup_goes_on(tmp_path: Path) -> None:
    calls, out = _run_docker_section(tmp_path, CI_HOST, reclaim_rc=1)
    assert "docker-reclaim" in out
    assert "docker image prune -af" in calls, "a failed reclaim must not stop the rest of the cleanup"


def test_a_node_without_the_reclaim_never_calls_it(tmp_path: Path) -> None:
    calls, _ = _run_docker_section(tmp_path, GATEWAY, reclaim_rc=0)
    assert not [c for c in calls if c.startswith("python3")]
    assert "docker image prune -af" in calls


def test_a_node_without_the_reclaim_renders_none() -> None:
    assert "--declaration" not in render_script(GATEWAY)


def test_make_maintain_runs_the_same_reclaim_and_does_not_ignore_its_failure() -> None:
    by_name = {t["name"]: t for t in tasks()}
    reclaim = by_name["Reclaim orphaned buildx builders and CI job volumes"]
    assert "--apply" in reclaim["command"]
    assert "maintenance_docker_reclaim_script" in reclaim["command"]
    assert "maintenance_docker_reclaim" in reclaim["when"] and "maintenance_run_cleanup" in reclaim["when"]
    assert not reclaim.get("ignore_errors"), "a failed reclaim must fail `make maintain`"


def test_the_role_ships_the_module_itself() -> None:
    """One filter, two callers: the file on the node is this repo's module,
    so a fix to the filter reaches the timer with the next provision."""
    by_name = {t["name"]: t for t in tasks()}
    install = by_name["Install the Docker residue reclaimer"]
    assert install["copy"]["src"] == "{{ maintenance_docker_reclaim_source }}"
    source = Path(resolve_defaults(CI_HOST)["maintenance_docker_reclaim_source"]).resolve()
    assert source == MODULE


def test_the_module_imports_only_the_standard_library() -> None:
    """It runs on the node, where there is no toolkit and no venv."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    foreign = imported - set(sys.stdlib_module_names) - {"__future__"}
    assert not foreign, f"docker_reclaim.py is copied to nodes and must stay stdlib-only: {sorted(foreign)}"


# --- invariant 2: what the role ships protects every declared volume ----------


def _shipped_declaration() -> dict[str, Any]:
    """The JSON the role writes to the node, rendered from the task itself."""
    by_name = {t["name"]: t for t in tasks()}
    content = by_name["Install the backup declaration the reclaimer protects"]["copy"]["content"]
    env = Environment(undefined=StrictUndefined)
    env.filters["to_nice_json"] = lambda value: json.dumps(value, indent=4)
    return json.loads(env.from_string(content).render(resolve_defaults(CI_HOST)))


def test_the_shipped_declaration_protects_every_declared_volume() -> None:
    assert protected_volumes(_shipped_declaration()) == frozenset(DECLARED)


@pytest.mark.parametrize("name", sorted(DECLARED))
def test_no_declared_volume_matches_the_residue_pattern(name: str) -> None:
    assert not _RECLAIMABLE_VOLUME.match(name), f"{name} would be a reclaim candidate by name alone"


def _disguised_as_residue() -> list[Volume]:
    """Every declared volume made to look exactly like residue -- old, unheld,
    and labelled anonymous -- next to real residue."""
    return [Volume(name, created=OLD, anonymous=True) for name in sorted(DECLARED)] + [
        Volume(name, created=OLD) for name in LEAKED
    ]


def test_a_declared_volume_is_never_planned_even_disguised_as_residue() -> None:
    plan = plan_reclaim([], _disguised_as_residue(), NOW, 24, protected=protected_volumes(_shipped_declaration()))
    assert not DECLARED & set(plan.volumes)
    assert set(LEAKED) <= set(plan.volumes), "anti-vacuity: the real residue must still go"


def test_the_protection_is_what_saves_them() -> None:
    """Same input without the declaration's names: every one is planned. So the
    test above is green because of `protected`, not because of the pattern."""
    plan = plan_reclaim([], _disguised_as_residue(), NOW, 24, protected=frozenset({"unrelated"}))
    assert DECLARED <= set(plan.volumes)


def test_an_empty_protection_is_refused() -> None:
    with pytest.raises(ReclaimRefused):
        protected_volumes({"sources": {}, "excluded": {}})
    with pytest.raises(ReclaimRefused):
        plan_reclaim([], [], NOW, 24, protected=frozenset())


# --- the shipped file, run as the timer runs it -------------------------------

FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, sys
state = json.load(open(os.environ["FAKE_DOCKER_STATE"]))
log = open(os.environ["FAKE_DOCKER_LOG"], "a")
args = sys.argv[1:]
vols = {v["name"]: v for v in state["volumes"]}
ctrs = {c["id"]: c for c in state["containers"]}
if args[:2] == ["volume", "ls"]:
    print("\n".join(vols))
elif args[:2] == ["volume", "inspect"]:
    for name in args[4:]:
        v = vols[name]
        print(f"{name}|{v['created']}|{json.dumps(v['labels'])}")
elif args[:2] == ["ps", "-aq"]:
    print("\n".join(ctrs))
elif args[0] == "inspect":
    for cid in args[3:]:
        c = ctrs[cid]
        print(f"/{c['name']}|{c['created']}|{str(c['running']).lower()}|{''.join(m + ',' for m in c['mounts'])}")
elif args[:2] == ["rm", "-f"] or args[:2] == ["volume", "rm"]:
    log.write(" ".join(args) + "\n")
else:
    sys.exit(f"fake docker: unexpected {args}")
'''


def test_the_shipped_module_reclaims_residue_and_spares_every_declared_volume(tmp_path: Path) -> None:
    iso = lambda moment: moment.strftime("%Y-%m-%dT%H:%M:%S+00:00")  # noqa: E731
    now = datetime.now(timezone.utc)
    old, young = iso(now - timedelta(days=30)), iso(now - timedelta(hours=1))
    anonymous = {"com.docker.volume.anonymous": ""}
    builder = "buildx_buildkit_builder-dae64fc0-165f-47c6-a953-46c7f026aa2d0"
    running_job = "GITEA-ACTIONS-TASK-2275_WORKFLOW-CI_JOB-audit"
    state = {
        "volumes": [{"name": n, "created": old, "labels": anonymous} for n in sorted(DECLARED)]
        + [{"name": n, "created": old, "labels": None} for n in LEAKED]
        + [
            {"name": f"{builder}_state", "created": old, "labels": None},
            {"name": running_job, "created": old, "labels": None},
            {"name": "399a4bea9ab2b2e72c19c786bdb14899f1afb3fecfeee2a92451db63f0787720", "created": old, "labels": anonymous},
            {"name": "a" * 64, "created": young, "labels": anonymous},
        ],
        "containers": [
            {"id": "c1", "name": builder, "created": old, "running": True, "mounts": [f"{builder}_state"]},
            {"id": "c2", "name": running_job, "created": young, "running": True, "mounts": [running_job, "act-toolcache"]},
        ],
    }
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(FAKE_DOCKER)
    (bin_dir / "docker").chmod(0o755)
    (tmp_path / "state.json").write_text(json.dumps(state))
    declaration = tmp_path / "declaration.json"
    declaration.write_text(json.dumps(_shipped_declaration()))
    log = tmp_path / "docker.log"

    result = subprocess.run(
        [sys.executable, str(MODULE), "--apply", "--declaration", str(declaration), "--min-age-hours", "24"],
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_DOCKER_STATE": str(tmp_path / "state.json"),
            "FAKE_DOCKER_LOG": str(log),
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    calls = log.read_text().splitlines()
    removed = {c.split()[-1] for c in calls}

    assert not DECLARED & removed
    assert running_job not in removed and "a" * 64 not in removed
    assert removed == {
        builder,
        f"{builder}_state",
        *LEAKED,
        "399a4bea9ab2b2e72c19c786bdb14899f1afb3fecfeee2a92451db63f0787720",
    }
    assert calls[0] == f"rm -f {builder}", "the builder goes before the volume it holds"


def test_the_shipped_module_fails_loudly_without_a_declaration(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(MODULE), "--declaration", str(tmp_path / "missing.json")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert "FAILED" in result.stderr


# --- invariant 4: a failure reaches someone ------------------------------------


def _script_tail(script: str) -> str:
    return 'FAILURES="${FAILURES:-}"\n' + script[script.index('DISK_PCENT="$(df') :]


@pytest.mark.parametrize(
    ("pcent", "failures", "expected"),
    [(50, "", 0), (85, "", 1), (80, "", 1), (50, " docker-reclaim", 1)],
)
def test_the_run_exits_non_zero_on_disk_pressure_or_a_failed_step(
    tmp_path: Path, pcent: int, failures: str, expected: int
) -> None:
    """Executes the rendered tail of the timer script against a fake `df`. A
    non-zero exit is what fires `OnFailure=kubelab-notify@`."""
    fake_df = tmp_path / "df"
    fake_df.write_text(f"#!/bin/sh\necho 'Use%'\necho ' {pcent}%'\n")
    fake_df.chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", _script_tail(render_script(CI_HOST))],
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}", "FAILURES": failures},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == expected, result.stdout + result.stderr


def test_the_alert_threshold_is_the_live_tests_threshold() -> None:
    from tests.infra.test_nodes import _DISK_THRESHOLD, _HUB_DISK_THRESHOLD

    assert int(resolve_defaults(CI_HOST)["maintenance_disk_alert_percent"]) == _DISK_THRESHOLD
    assert int(resolve_defaults(HUB)["maintenance_disk_alert_percent"]) == _HUB_DISK_THRESHOLD


def test_make_maintain_fails_on_disk_pressure_too() -> None:
    by_name = {t["name"]: t for t in tasks()}
    check = by_name["Fail when the disk is still above the alert threshold after cleanup"]
    assert "fail" in check
    assert any("maintenance_disk_alert_percent" in str(cond) for cond in check["when"])


def test_the_timer_unit_notifies_on_failure() -> None:
    unit = (REPO / "infra/ansible/roles/node_maintenance/templates/kubelab-maintenance.service.j2").read_text()
    assert "OnFailure=kubelab-notify@%n.service" in unit


def test_the_module_still_reads_the_live_probe_format() -> None:
    """The format `probe` asks Docker for, parsed back: anonymous by label."""
    line = '399a|2026-09-03T06:15:52+02:00|{"com.docker.volume.anonymous":""}'
    (volume,) = docker_reclaim.parse_volumes(line)
    assert volume.anonymous and volume.created == datetime(2026, 9, 3, 4, 15, 52, tzinfo=timezone.utc)
    (named,) = docker_reclaim.parse_volumes("act_runner_data|2026-09-03T07:08:12+02:00|null")
    assert not named.anonymous
