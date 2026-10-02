"""Restore the newest Postgres dump from R2 into a scratch container (BACKUP-046 AC5).

A backup is covered once a restore of it has been seen to work, so this is the
proof behind `backup.sources.<node>.postgres`. It reads the newest snapshot of
the node's repository, takes `pg_dumpall.sql` out of it, refuses a dump without
its completion trailer, loads it into a throwaway container running the image
live runs, and checks that the restore is complete:

- every database and table live holds exists in the restore;
- no table that has rows live came back empty.

Counts are shown beside live, never compared for equality. The snapshot is up
to four hours older than live and the board keeps being written, so equality
would fail on a busy afternoon and prove nothing more.

The dump holds role password hashes and every row. It stays in a private temp
directory, psql's own output goes to a file there, and only names and counts are
printed. The container, its data volume and the directory are removed on every
exit path: the teardown is a `finally`, not a step (the principle `pvc_drill`
was built on). The volume matters most: the image declares one for its data
directory, and `docker rm` without `-v` leaves the restored database in it.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Optional

from toolkit.core.logging import logger
from toolkit.features.restore_drill import latest_snapshot, report, scratch

TRAILER = "-- PostgreSQL database cluster dump complete"

#: Lists every database, so a database live holds and the restore lacks is visible.
_DATABASES_SQL = "select datname from pg_database where not datistemplate order by 1;"

#: Exact counts, one query per database. `n_live_tup` is an estimate, and an
#: estimate of zero on a table that has rows would hide the failure that matters.
_COUNTS_SQL = """
select table_schema || '.' || table_name,
       (xpath('/row/c/text()',
              query_to_xml(format('select count(*) as c from %I.%I', table_schema, table_name),
                           false, true, '')))[1]::text
from information_schema.tables
where table_type = 'BASE TABLE' and table_schema not in ('pg_catalog', 'information_schema')
order by 1;
"""

Run = Callable[..., "tuple[int, str, str]"]

Counts = dict[str, dict[str, int]]


def _default_run(
    argv: list[str],
    *,
    env: Optional[dict[str, str]] = None,
    stdin: Optional[str] = None,
    stdout_path: Optional[str] = None,
    stderr_to_file: bool = True,
) -> tuple[int, str, str]:
    merged = {**os.environ, **(env or {})}
    if stdout_path:
        # By default stderr goes to the file too: psql reports a failed statement
        # on stderr, and its text can carry row data. restic's stderr carries no
        # rows and is returned instead, so it cannot corrupt the dump it writes.
        with open(stdout_path, "w", opener=lambda p, f: os.open(p, f, 0o600)) as sink:
            stderr = subprocess.STDOUT if stderr_to_file else subprocess.PIPE
            to_file = subprocess.run(argv, stdout=sink, stderr=stderr, env=merged, check=False)
        err = "" if stderr_to_file else to_file.stderr.decode("utf-8", "replace")
        return to_file.returncode, "", err
    proc = subprocess.run(argv, input=stdin, capture_output=True, text=True, env=merged, check=False)
    return proc.returncode, proc.stdout, proc.stderr


def parse_counts(text: str) -> dict[str, int]:
    """`schema.table|count` lines, as `psql -At -F '|'` prints them."""
    counts = {}
    for line in text.splitlines():
        if "|" in line:
            table, _, count = line.rpartition("|")
            counts[table] = int(count)
    return counts


def compare(live: Counts, restored: Counts) -> tuple[bool, list[str]]:
    """Complete, not equal: everything live has exists, and nothing with rows came back empty."""
    ok = True
    lines = []
    for db in sorted(live):
        if db not in restored:
            lines.append(f"FAIL {db}: database missing from the restore")
            ok = False
            continue
        for table in sorted(live[db]):
            want = live[db][table]
            got = restored[db].get(table)
            if got is None:
                lines.append(f"FAIL {db} {table}: table missing from the restore (live {want})")
                ok = False
            elif got == 0 and want > 0:
                lines.append(f"FAIL {db} {table}: restored empty, live {want}")
                ok = False
            else:
                lines.append(f"     {db} {table}: restored {got}, live {want}")
        for table in sorted(set(restored[db]) - set(live[db])):
            lines.append(f"     {db} {table}: restored {restored[db][table]}, gone from live since the snapshot")
    return ok, lines


def _has_trailer(path: Path) -> bool:
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - 4096))
        tail = handle.read().decode("utf-8", "replace").splitlines()
    return TRAILER in (line.strip() for line in tail[-5:])


def _counts(run: Run, exec_prefix: list[str]) -> Optional[Counts]:
    """Counts per database through `exec_prefix`, a command that runs psql on stdin."""
    rc, out, _ = run([*exec_prefix, "postgres"], stdin=_DATABASES_SQL)
    if rc != 0:
        return None
    result: Counts = {}
    for db in out.split():
        rc, out, _ = run([*exec_prefix, db], stdin=_COUNTS_SQL)
        if rc != 0:
            return None
        result[db] = parse_counts(out)
    return result


def run_drill(
    *,
    repo: str,
    restic_env: dict[str, str],
    dump_path: str,
    source: dict[str, Any],
    kubeconfig: Path,
    run: Run = _default_run,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Restore the newest dump in `repo` and check it against live. True only on a complete restore."""
    namespace = source["pvc"]["namespace"]
    deployment = source["pg_dumpall"]["deployment"]
    container = source["pg_dumpall"]["container"]

    snapshot = latest_snapshot(run, repo, restic_env)
    if snapshot is None:
        return False

    ok = False
    with scratch(run, "pgdrill", holds="a full dump of the cluster") as box:
        ok = _load_and_check(
            run=run,
            repo=repo,
            restic_env=restic_env,
            snapshot=snapshot["short_id"],
            dump_path=dump_path,
            workdir=box.workdir,
            name=box.name,
            namespace=namespace,
            deployment=deployment,
            container=container,
            kubeconfig=kubeconfig,
            sleep=sleep,
        )
    # A restore that passed but left the restored data behind is not a pass.
    return ok and box.clean


def _load_and_check(
    *,
    run: Run,
    repo: str,
    restic_env: dict[str, str],
    snapshot: str,
    dump_path: str,
    workdir: Path,
    name: str,
    namespace: str,
    deployment: str,
    container: str,
    kubeconfig: Path,
    sleep: Callable[[float], None],
) -> bool:
    """Everything between reading the snapshot and the teardown. True only on a complete restore."""
    dump = workdir / "pg_dumpall.sql"
    rc, _, err = run(
        ["restic", "-r", repo, "dump", snapshot, dump_path],
        env=restic_env,
        stdout_path=str(dump),
        stderr_to_file=False,
    )
    if rc != 0 or not dump.exists():
        logger.error(f"drill: restic could not read {dump_path} from snapshot {snapshot}: {err.strip()[:160]}")
        return False
    if not _has_trailer(dump):
        logger.error("drill: the dump has no completion trailer: this backup would not restore whole")
        return False
    logger.success(f"drill: {dump_path} carries its completion trailer ({dump.stat().st_size} bytes)")

    kubectl = ["kubectl", "--kubeconfig", str(kubeconfig), "-n", namespace]
    jsonpath = f'{{.spec.template.spec.containers[?(@.name=="{container}")].image}}'
    rc, image, err = run([*kubectl, "get", "deploy", deployment, "-o", f"jsonpath={jsonpath}"])
    if rc != 0 or not image.strip():
        logger.error(f"drill: cannot read the image live runs: {err.strip()[:160]}")
        return False
    image = image.strip()

    if not _start_scratch(run, name, image, sleep) or not _load_dump(run, name, dump, workdir):
        return False

    live = _counts(
        run,
        [
            "kubectl",
            "--kubeconfig",
            str(kubeconfig),
            "exec",
            "-i",
            "-n",
            namespace,
            f"deploy/{deployment}",
            "-c",
            container,
            "--",
            "sh",
            "-c",
            'psql -U "$POSTGRES_USER" -At -F "|" -f - -d "$1"',
            "sh",
        ],
    )
    restored = _counts(run, ["docker", "exec", "-i", name, "psql", "-U", "postgres", "-At", "-F", "|", "-f", "-", "-d"])
    if live is None or restored is None:
        logger.error("drill: CANNOT CHECK — counting failed on " + ("live" if live is None else "the restore"))
        return False
    if not any(live.values()):
        # Every check below is "for each table live has", so an empty answer
        # would pass with nothing compared (lesson-416).
        logger.error("drill: CANNOT CHECK — live reported no tables at all")
        return False

    ok, lines = compare(live, restored)
    report(lines)
    if ok:
        logger.success(f"drill: snapshot {snapshot} restores completely ({sum(map(len, live.values()))} tables)")
    return ok


def _start_scratch(run: Run, name: str, image: str, sleep: Callable[[float], None]) -> bool:
    """Start the scratch server with no network and wait until it accepts connections."""
    # Trust auth is safe only because nothing can connect: no network at all
    # (loopback still serves the checks below), so the restored rows and role
    # hashes are reachable only through `docker exec`, for the drill's lifetime.
    rc, _, err = run(
        ["docker", "run", "-d", "--name", name, "--network", "none", "-e", "POSTGRES_HOST_AUTH_METHOD=trust", image]
    )
    if rc != 0:
        logger.error(f"drill: the scratch container did not start: {err.strip()[:160]}")
        return False
    # Over TCP on purpose: the image's init server listens on the socket only,
    # so a socket check can pass before the real server is up.
    for _ in range(60):
        if run(["docker", "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "postgres", "-q"])[0] == 0:
            break
        sleep(1)
    else:
        logger.error("drill: the scratch server never became ready")
        return False
    return True


def _load_dump(run: Run, name: str, dump: Path, workdir: Path) -> bool:
    """Load the dump into the scratch server. False when any statement but a role re-creation failed."""
    run(["docker", "cp", str(dump), f"{name}:/tmp/pg_dumpall.sql"])
    log = workdir / "psql.log"
    run(
        [
            "docker",
            "exec",
            name,
            "psql",
            "-U",
            "postgres",
            "-d",
            "postgres",
            "-v",
            "ON_ERROR_STOP=0",
            "-q",
            "-f",
            "/tmp/pg_dumpall.sql",
        ],
        stdout_path=str(log),
    )
    errors = [line for line in log.read_text(errors="replace").splitlines() if "ERROR:" in line]
    failed = [line for line in errors if not ("role " in line and "already exists" in line)]
    if failed:
        # Counted, never printed: a failed statement's text can carry row data.
        logger.error(f"drill: {len(failed)} statement(s) did not load (text withheld: it can carry row data)")
        return False
    return True


def staging_dir(project_root: Path) -> str:
    """Where `node_backup` stages captures; the snapshot stores absolute paths under it."""
    import yaml

    defaults = project_root / "infra/ansible/roles/node_backup/defaults/main.yml"
    return str(yaml.safe_load(defaults.read_text())["node_backup_staging_dir"])


def drill_postgres(env: str = "prod", project_root: Optional[Path] = None) -> bool:
    """Resolve every input from the SSOT and run the drill for each `pg_dumpall` source."""
    from toolkit.features.backup_destination import DestinationError, repo_url, repository_name, restic_context
    from toolkit.features.configuration import ConfigurationManager
    from toolkit.features.k8s_kubeconfig import output_path

    cm = ConfigurationManager(env, project_root)
    root = Path(project_root or cm.project_root)
    logger.section(f"postgres restore drill — newest dump in R2 into a scratch container ({env})")
    try:
        dest, restic_env = restic_context(cm)
    except DestinationError as exc:
        logger.error(str(exc))
        return False

    sources = (cm.get_merged_config().get("backup", {}) or {}).get("sources", {}) or {}
    targets = [
        (node, service, spec)
        for node, entries in sorted(sources.items())
        for service, spec in sorted((entries or {}).items())
        if isinstance(spec, dict) and "pg_dumpall" in spec
    ]
    if not targets:
        logger.error("drill: no source in backup.sources is captured by pg_dumpall")
        return False

    ok = True
    for node, service, spec in targets:
        logger.info(f"drill: {node}/{service}")
        ok = (
            run_drill(
                repo=repo_url(dest, repository_name(cm, node)),
                restic_env=restic_env,
                dump_path=f"{staging_dir(root)}/{service}/pg_dumpall.sql",
                source=spec,
                kubeconfig=output_path(env),
            )
            and ok
        )
    return ok
