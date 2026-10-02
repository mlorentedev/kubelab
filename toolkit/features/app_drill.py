"""Restore the newest Authelia and n8n captures from R2 and prove the SOPS keys open them (BACKUP-068).

Both services keep encrypted data: Authelia's storage under
`storage_encryption_key`, n8n's credentials under `encryption_key`. An intact
database the key cannot open is not a restore, and `PRAGMA integrity_check`
cannot tell the two apart. So for each service this restores the VPS's newest
snapshot into a private temp directory and passes only if:

- `PRAGMA integrity_check` answers `ok`;
- every durable row live had when the snapshot was taken is in the restore, by
  id (`TABLES`). Rows whose contents are an identity (Authelia's opaque `sub`
  per OIDC client) must also come back unchanged;
- the image live runs opens the restore with the SOPS key, with no network:
  Authelia's encryption check prints SUCCESS and its server answers healthy;
  n8n starts (a key that is not the data's aborts the start) and decrypts every
  credential.

"Complete", never "equal": a row created after the snapshot is expected to be
missing, and one deleted since is expected to be there. Both are reported.
Transient tables (sessions, tokens, logs) are not compared at all.

Live is read from the database files on the node with `sqlite3 -readonly`, the
way the capture reads them. Never through the app's CLI in its pod: every `n8n`
command starts a second n8n process under the pod's memory limit (OPS-033), and
prints its answer through a logger the pod sets to `warn` (lesson-500).

The restore holds encrypted secrets and the key that opens them. Both stay in a
`0700` directory, the key reaches the container only as a `0600` file named by a
`*_FILE` variable, only table names, row ids and counts are printed, and the
container and the directory are removed on every exit path.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shlex
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from toolkit.core.logging import logger
from toolkit.features.headscale_drill import snapshot_time, sqlite_intact, ssh
from toolkit.features.restore_drill import latest_snapshot, report, restore_source, scratch

Run = Callable[..., "tuple[int, str, str]"]

#: Seconds a restored server gets to answer its health check.
READY_TIMEOUT = 120

#: Where the key files are mounted, read-only, in every scratch container.
SECRETS = "/run/drill"

#: `table -> {row id -> (created, in epoch seconds or None, digest of its identity columns or "")}`.
Rows = dict[str, dict[str, tuple[Optional[int], str]]]

_VERSION = "__schema_version__"

#: Pseudo-table holding `sqlite_sequence`: `{table: (highest id ever allocated, "")}`.
SEQUENCE = "__sequence__"


@dataclass(frozen=True)
class Table:
    """A table whose rows must survive a restore.

    `created` names the creation-time column. A table without one must use an
    `AUTOINCREMENT` id: the restore's `sqlite_sequence` then says which ids it had
    allocated, so a live id above that is newer and a missing one at or below it
    was lost. The restore's highest surviving id cannot say that, because a lost
    trailing row lowers it.
    `identity` names columns that must come back unchanged.
    """

    name: str
    created: Optional[str] = None
    identity: tuple[str, ...] = ()


@dataclass(frozen=True)
class App:
    """One service: where its data mounts, which key opens it, and what must survive."""

    service: str
    key_path: str
    key_env: str
    mount: str
    tables: tuple[Table, ...]
    version_sql: Optional[str] = None


APPS = {
    "authelia": App(
        service="authelia",
        key_path="apps.services.security.authelia.storage_encryption_key",
        key_env="AUTHELIA_STORAGE_ENCRYPTION_KEY_FILE",
        mount="/data",
        tables=(
            # The `sub` each OIDC client knows a user by: a changed one is a new identity.
            Table("user_opaque_identifier", identity=("service", "sector_id", "username", "identifier")),
            Table("user_preferences"),
            Table("totp_configurations", created="created_at"),
            Table("webauthn_credentials", created="created_at"),
        ),
        version_sql="select max(version_after) from migrations",
    ),
    "n8n": App(
        service="n8n",
        key_path="apps.services.automation.n8n.encryption_key",
        key_env="N8N_ENCRYPTION_KEY_FILE",
        mount="/home/node/.n8n",
        tables=(Table("workflow_entity", created="createdAt"), Table("credentials_entity", created="createdAt")),
    ),
}


def _default_run(argv: list[str], *, env: Optional[dict[str, str]] = None) -> tuple[int, str, str]:
    import subprocess

    proc = subprocess.run(argv, capture_output=True, text=True, env={**os.environ, **(env or {})}, check=False)
    return proc.returncode, proc.stdout, proc.stderr


def rows_sql(app: App) -> str:
    """One query for every durable table, so live and the restore are read by the same text."""
    parts = []
    for table in app.tables:
        created = f"CAST(strftime('%s', {table.created}) AS INTEGER)" if table.created else "NULL"
        identity = " || ',' || ".join(f"quote({column})" for column in table.identity) or "NULL"
        parts.append(
            f"select '{table.name}' as tbl, CAST(id AS TEXT) as k, {created} as t, {identity} as ident"
            f" from {table.name}"
        )
    by_sequence = [t.name for t in app.tables if not t.created]
    if by_sequence:
        names = ", ".join(f"'{name}'" for name in by_sequence)
        parts.append(
            f"select '{SEQUENCE}' as tbl, name as k, seq as t, NULL as ident"
            f" from sqlite_sequence where name in ({names})"
        )
    if app.version_sql:
        parts.append(f"select '{_VERSION}' as tbl, CAST(({app.version_sql}) AS TEXT) as k, NULL as t, NULL as ident")
    return " union all ".join(parts) + ";"


def parse_rows(records: list[dict[str, Any]]) -> tuple[Rows, Optional[str]]:
    """Rows by table, and the schema version. Identity values are hashed here and never kept."""
    rows: Rows = {}
    version = None
    for record in records:
        if record["tbl"] == _VERSION:
            version = record["k"]
            continue
        ident = record.get("ident")
        digest = hashlib.sha256(ident.encode()).hexdigest() if ident else ""
        rows.setdefault(record["tbl"], {})[str(record["k"])] = (record.get("t"), digest)
    return rows, version


def _restored_records(database: Path, sql: str) -> list[dict[str, Any]]:
    con = sqlite3.connect(f"file:{database}?mode=ro&immutable=1", uri=True)
    try:
        con.row_factory = sqlite3.Row
        return [dict(row) for row in con.execute(sql)]
    finally:
        con.close()


def compare(*, live: Rows, restored: Rows, tables: tuple[Table, ...], taken: float) -> tuple[bool, list[str]]:
    """Every row live had at `taken` is in the restore, identities unchanged. Contents are never printed."""
    lines: list[str] = []
    ok = True
    for table in tables:
        have, got = live.get(table.name, {}), restored.get(table.name, {})
        allocated = restored.get(SEQUENCE, {}).get(table.name, (None, ""))[0]
        for key, (created, digest) in sorted(have.items()):
            what = f"{table.name} row {key}"
            if key in got:
                if digest and got[key][1] != digest:
                    ok = False
                    lines.append(f"FAIL {what}: restored with different contents")
            elif created is not None and created > taken:
                lines.append(f"INFO {what}: newer than the snapshot")
            elif created is None and key.isdigit() and allocated is not None and int(key) > allocated:
                lines.append(f"INFO {what}: newer than the snapshot")
            else:
                ok = False
                lines.append(f"FAIL {what}: live had it at snapshot time; missing from the restore")
        for key in sorted(set(got) - set(have)):
            lines.append(f"INFO {table.name} row {key}: deleted since the snapshot")
        lines.append(f"{table.name}: {len(have)} live, {len(got)} restored")
    return ok, lines


def _write_secret(path: Path, value: str) -> None:
    """A `0600` file from the first byte: never a moment where another user could read it."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(value)


@dataclass
class _Scratch:
    run: Run
    app: App
    name: str
    image: str
    data: Path
    secrets: Path
    database: str
    sleep: Callable[[float], None]
    clock: Callable[[], float]

    def start(self, *extra: str) -> bool:
        # No network: a copy of an identity provider or an automation server must
        # never be reachable, and the restored n8n activates its workflows on start.
        rc, _, err = self.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                self.name,
                "--network",
                "none",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "-v",
                f"{self.data}:{self.app.mount}",
                "-v",
                f"{self.secrets}:{SECRETS}:ro",
                "-e",
                f"{self.app.key_env}={SECRETS}/key",
                *extra,
            ]
        )
        if rc != 0:
            logger.error(f"drill: {self.app.service}: the scratch container did not start: {err.strip()[:160]}")
        return rc == 0

    def wait_healthy(self, url: str, healthy: str, gone: Callable[[], bool]) -> bool:
        deadline = self.clock() + READY_TIMEOUT
        while True:
            rc, out, _ = self.run(["docker", "exec", self.name, "wget", "-qO-", url])
            if rc == 0 and healthy in out:
                return True
            if gone() or self.clock() > deadline:
                return False
            self.sleep(1)


def _prove_authelia(box: _Scratch) -> bool:
    """The SOPS key opens the restored storage, and the server starts on it."""
    for name in ("session", "jwt"):
        _write_secret(box.secrets / name, secrets.token_hex(32))
    from argon2 import PasswordHasher

    # The file backend refuses an empty user list, so one throwaway user whose
    # password nobody ever sees. Its hash is made here, never committed.
    users = {"users": {"drill": {"displayname": "drill", "email": "drill@drill.invalid"}}}
    users["users"]["drill"]["password"] = PasswordHasher().hash(secrets.token_hex(16))
    (box.secrets / "users.yml").write_text(yaml.safe_dump(users))
    config = {
        "server": {"address": "tcp://127.0.0.1:9091/"},
        "authentication_backend": {"file": {"path": f"{SECRETS}/users.yml", "watch": False}},
        "access_control": {"default_policy": "two_factor"},
        "session": {"cookies": [{"domain": "drill.invalid", "authelia_url": "https://auth.drill.invalid"}]},
        "storage": {"local": {"path": f"{box.app.mount}/{box.database}"}},
        "notifier": {"filesystem": {"filename": f"{box.app.mount}/drill-notification.txt"}},
        "ntp": {"disable_startup_check": True},
    }
    (box.secrets / "config.yml").write_text(yaml.safe_dump(config))

    # Idle first, so the key is checked by the CLI before the server can refuse it.
    if not box.start("--entrypoint", "sleep", box.image, "infinity"):
        return False
    _, out, _ = box.run(
        [
            "docker",
            "exec",
            box.name,
            "authelia",
            "storage",
            "encryption",
            "check",
            "--verbose",
            "--sqlite.path",
            f"{box.app.mount}/{box.database}",
            "--config",
            "/dev/null",
        ]
    )
    # Exits 0 on FAILURE too: only this text is a pass.
    if "Storage Encryption Key Validation: SUCCESS" not in out:
        logger.error("FAIL authelia: the SOPS storage key does not open the restored database")
        return False
    logger.success("drill: authelia: the SOPS storage key opens the restored database")

    rc, _, err = box.run(
        [
            "docker",
            "exec",
            "-d",
            "-e",
            f"AUTHELIA_SESSION_SECRET_FILE={SECRETS}/session",
            "-e",
            f"AUTHELIA_IDENTITY_VALIDATION_RESET_PASSWORD_JWT_SECRET_FILE={SECRETS}/jwt",
            box.name,
            "authelia",
            "--config",
            f"{SECRETS}/config.yml",
        ]
    )
    if rc != 0:
        logger.error(f"FAIL authelia: the server did not start: {err.strip()[:160]}")
        return False

    # The server is a second process in a container that stays up on `sleep`, so
    # the container's state says nothing about it. The image has busybox pidof.
    def gone() -> bool:
        return box.run(["docker", "exec", box.name, "pidof", "authelia"])[0] != 0

    if not box.wait_healthy("http://127.0.0.1:9091/api/health", '"OK"', gone=gone):
        logger.error(f"FAIL authelia: the server exited or did not answer healthy within {READY_TIMEOUT}s")
        return False
    logger.success("drill: authelia: the server starts on the restore and answers healthy")
    return True


def _prove_n8n(box: _Scratch) -> bool:
    """n8n starts on the restore with the SOPS key, and every credential decrypts."""
    if not box.start(
        "-e",
        "N8N_USER_FOLDER=/home/node",
        "-e",
        "DB_TYPE=sqlite",
        "-e",
        f"DB_SQLITE_DATABASE={box.app.mount}/{box.database}",
        "-e",
        "N8N_LOG_LEVEL=info",
        "-e",
        "N8N_DIAGNOSTICS_ENABLED=false",
        "-e",
        "N8N_VERSION_NOTIFICATIONS_ENABLED=false",
        "-e",
        "N8N_TEMPLATES_ENABLED=false",
        "-e",
        "N8N_PERSONALIZATION_ENABLED=false",
        box.image,
    ):
        return False

    def gone() -> bool:
        rc, out, _ = box.run(["docker", "inspect", "-f", "{{.State.Running}}", box.name])
        return rc != 0 or out.strip() != "true"

    if not box.wait_healthy("http://127.0.0.1:5678/healthz", '"ok"', gone=gone):
        _, out, err = box.run(["docker", "logs", box.name])
        if "Mismatching encryption keys" in out + err:
            logger.error("FAIL n8n: the SOPS key is not the key this data was encrypted with")
        else:
            logger.error(f"FAIL n8n: the server did not answer healthy within {READY_TIMEOUT}s")
        return False
    logger.success("drill: n8n: the server starts on the restore with the SOPS key")

    rc, _, _ = box.run(
        ["docker", "exec", box.name, "n8n", "export:credentials", "--all", "--decrypted", "--output=/dev/null"]
    )
    if rc != 0:
        logger.error("FAIL n8n: the restored credentials do not decrypt with the SOPS key")
        return False
    logger.success("drill: n8n: every restored credential decrypts")
    return True


PROVE: dict[str, Callable[[_Scratch], bool]] = {"authelia": _prove_authelia, "n8n": _prove_n8n}


def run_drill(
    *,
    app: App,
    database: str,
    repo: str,
    restic_env: dict[str, str],
    staging_dir: str,
    key: str,
    kubeconfig: str,
    namespace: str,
    claim: str,
    ssh_target: str,
    run: Run = _default_run,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Restore `app`'s newest capture in `repo` and check it against live. True only on a whole restore."""
    service = app.service
    read = _read_live(app, database, ["kubectl", "--kubeconfig", kubeconfig], namespace, claim, ssh_target, run)
    if read is None:
        return False
    image, live, live_version = read
    label = f"drill: {service}"
    snapshot = latest_snapshot(run, repo, restic_env, label=label)
    if snapshot is None:
        return False

    ok = False
    with scratch(run, f"{service}drill", holds=f"{service}'s data and key") as box:
        started = clock()
        source = f"{staging_dir}/{service}"
        data = restore_source(
            run,
            repo=repo,
            restic_env=restic_env,
            snapshot=snapshot["short_id"],
            source=source,
            workdir=box.workdir,
            required=database,
            label=label,
        )
        if data is not None and _restore_matches(app, data, database, live, live_version, snapshot["time"]):
            keys = box.workdir / "secrets"
            keys.mkdir(mode=0o700)
            _write_secret(keys / "key", key)
            ok = PROVE[service](_Scratch(run, app, box.name, image, data, keys, database, sleep, clock))
            if ok:
                logger.info(f"{label}: RTO {clock() - started:.0f}s from download to a server that answers")
                logger.success(f"drill: snapshot {snapshot['short_id']} restores {service} completely")
    # A restore that passed but left the data and key behind is not a pass.
    return ok and box.clean


def _read_live(
    app: App, database: str, kubectl: list[str], namespace: str, claim: str, ssh_target: str, run: Run
) -> Optional[tuple[str, Rows, Optional[str]]]:
    """The image live runs, its durable rows and its schema version, or None after naming what is unreadable.

    Live first: every check after it is "for each row live has" (lesson-416).
    """
    service = app.service
    jsonpath = f'{{.spec.template.spec.containers[?(@.name=="{service}")].image}}'
    rc, image, err = run([*kubectl, "-n", namespace, "get", "deploy", service, "-o", f"jsonpath={jsonpath}"])
    if rc != 0 or not image.strip():
        logger.error(f"drill: {service}: CANNOT CHECK — the image live runs could not be read: {err.strip()[:160]}")
        return None
    pv = (
        f'{{range .items[?(@.spec.claimRef.namespace=="{namespace}")]}}'
        '{.spec.claimRef.name}{"\\t"}{.spec.local.path}{"\\n"}{end}'
    )
    rc, out, err = run([*kubectl, "get", "pv", "-o", f"jsonpath={pv}"])
    paths = [line.split("\t", 1)[1] for line in out.splitlines() if line.split("\t", 1)[0] == claim and "\t" in line]
    if rc != 0 or len(paths) != 1 or not paths[0]:
        logger.error(f"drill: {service}: CANNOT CHECK — no local-path volume bound to {namespace}/{claim}")
        return None
    sql = rows_sql(app)
    rc, out, err = ssh(
        run, ssh_target, f"sudo -n sqlite3 -readonly -json {shlex.quote(f'{paths[0]}/{database}')} {shlex.quote(sql)}"
    )
    try:
        if rc != 0:
            raise ValueError(err.strip()[:160])
        live, live_version = parse_rows(json.loads(out) if out.strip() else [])
    except (ValueError, KeyError) as exc:
        logger.error(f"drill: {service}: CANNOT CHECK — live's database could not be read: {str(exc)[:160]}")
        return None
    if not any(live.get(table.name) for table in app.tables):  # the sequence is not a row
        logger.error(f"drill: {service}: CANNOT CHECK — live has no durable rows at all")
        return None
    return image.strip(), live, live_version


def _restore_matches(app: App, data: Path, database: str, live: Rows, live_version: Optional[str], taken: str) -> bool:
    """The restored database is intact and holds every row live had when the snapshot was taken."""
    service = app.service
    if not sqlite_intact(data / database):
        logger.error(f"FAIL {service}: {database}: PRAGMA integrity_check did not answer ok")
        return False
    restored, version = parse_rows(_restored_records(data / database, rows_sql(app)))
    complete, lines = compare(live=live, restored=restored, tables=app.tables, taken=snapshot_time(taken))
    report(lines, prefix=f"drill: {service}: ")
    if app.version_sql:
        logger.info(f"drill: {service}: schema version live {live_version}, restored {version}")
    return complete


def drill_apps(env: str = "prod", project_root: Optional[Path] = None) -> bool:
    """Resolve every input from the SSOT and run the drill for Authelia and n8n."""
    from toolkit.features.backup_destination import DestinationError, repo_url, repository_name, restic_context
    from toolkit.features.configuration import ConfigurationManager
    from toolkit.features.k8s_kubeconfig import output_path
    from toolkit.features.postgres_drill import staging_dir

    cm = ConfigurationManager(env, project_root)
    root = Path(project_root or cm.project_root)
    logger.section(f"authelia + n8n restore drill — newest capture in R2 into scratch containers ({env})")
    try:
        dest, restic_env = restic_context(cm)
    except DestinationError as exc:
        logger.error(str(exc))
        return False

    merged = cm.get_merged_config()
    sources = (merged.get("backup", {}) or {}).get("sources", {}) or {}
    net = merged["networking"]
    ok = True
    for service, app in APPS.items():
        nodes = [node for node, entries in sorted(sources.items()) if service in (entries or {})]
        if nodes != ["vps"]:
            # The live read goes to the VPS by its public address, like the Headscale drill.
            logger.error(f"drill: expected {service} captured on the vps in backup.sources, found {nodes or 'none'}")
            ok = False
            continue
        spec = sources["vps"][service] or {}
        absent = [k for k in ("sqlite", "pvc") if not spec.get(k)]
        absent += [f"pvc.{k}" for k in ("namespace", "claim") if spec.get("pvc") and not spec["pvc"].get(k)]
        if absent:
            names = ", ".join(f"backup.sources.vps.{service}.{k}" for k in absent)
            logger.error(f"drill: {service}: CANNOT CHECK — the SSOT does not declare {names}")
            ok = False
            continue
        key = cm.get_secret_by_path(app.key_path)
        if not key:
            logger.error(f"drill: {service}: CANNOT CHECK — {app.key_path} is not in SOPS for {env}")
            ok = False
            continue
        ok = (
            run_drill(
                app=app,
                database=str(spec["sqlite"]),
                repo=repo_url(dest, repository_name(cm, "vps")),
                restic_env=restic_env,
                staging_dir=staging_dir(root),
                key=str(key),
                kubeconfig=str(output_path(env)),
                namespace=str(spec["pvc"]["namespace"]),
                claim=str(spec["pvc"]["claim"]),
                ssh_target=f"{net['ssh_users']['cloud']}@{net['vps']['public_ip']}",
            )
            and ok
        )
    return ok
