"""Restore the newest Headscale capture from R2 and prove it brings the control plane back (BACKUP-067).

Headscale is the mesh's control plane and a bootstrap dependency (ADR-015). A
restore that loses the database or the server keys means every node registers
again by hand, so this restores the VPS's newest snapshot into a private temp
directory and passes only if:

- `PRAGMA integrity_check` answers `ok` on the restored `db.sqlite`;
- the restored `noise_private.key` and `derp_server_private.key` hash the same
  as live's. A client trusts the server by the noise key, so the same key is
  what lets a node reconnect without re-registering;
- the image live runs starts on the restored data with no network, and its CLI
  lists the nodes and users;
- every node and user live had when the snapshot was taken is in the restore,
  nodes under the same id with the same machine key.

"Complete", never "equal": a node registered after the snapshot is expected to
be missing, and one deleted since is expected to be there. Both are reported.
Nodes are matched by id, never by name: a node that re-registers keeps its name
and gets a new id.

The restore holds both private keys. It stays in a `0700` directory, only names,
ids and counts are printed (never a key, a hash or a machine key), and the
container and the directory are removed on every exit path. The image is
distroless, so nothing could wipe the directory from inside a container; the
container runs as the invoking user instead, which leaves every file it writes
removable by a plain `rmtree` on any host.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from toolkit.core.logging import logger
from toolkit.features.restore_drill import latest_snapshot, report, restore_source, scratch, wait_until

Run = Callable[..., "tuple[int, str, str]"]

#: Where the capture stages the Headscale volume, relative to the staging dir.
SERVICE = "headscale"

#: The live container, as `docker-compose.yml.j2` names it.
LIVE_CONTAINER = "headscale"

#: The files a restore cannot do without, and how each is reported.
KEYS = {"noise_private.key": "noise key", "derp_server_private.key": "DERP key"}
DATABASE = "db.sqlite"

#: Seconds the restored server gets before its CLI must answer.
READY_TIMEOUT = 60

#: `id -> (label, machine key, created_at in epoch seconds)`.
Entries = dict[int, tuple[str, str, float]]


def _default_run(argv: list[str], *, env: Optional[dict[str, str]] = None) -> tuple[int, str, str]:
    proc = subprocess.run(argv, capture_output=True, text=True, env={**os.environ, **(env or {})}, check=False)
    return proc.returncode, proc.stdout, proc.stderr


def parse_entries(payload: str, key: Optional[str]) -> Entries:
    """`headscale {nodes,users} list -o json`, keyed by id.

    A node is labelled by `given_name`, a user by `name`. A missing `created_at`
    reads as 0, the oldest possible, so it can never excuse an entry from the
    check. A missing or empty `key` is unreadable, not "": live and restored would
    both read "" and the comparison would pass with nothing compared (lesson-416).
    """
    entries: Entries = {}
    for raw in json.loads(payload) or []:
        label = raw.get("given_name") or raw.get("name") or ""
        created = float((raw.get("created_at") or {}).get("seconds", 0))
        value = str(raw.get(key) or "") if key else ""
        if key and not value:
            raise ValueError(f"{label or raw.get('id')} has no {key}")
        entries[int(raw["id"])] = (label, value, created)
    return entries


def snapshot_time(text: str) -> float:
    """restic's RFC 3339 time, with nanoseconds Python will not parse, as epoch seconds."""
    match = re.fullmatch(r"(.+?:\d\d)(?:\.\d+)?(Z|[+-]\d\d:\d\d)", text)
    if not match:
        raise ValueError(f"unreadable snapshot time {text!r}")
    zone = "+00:00" if match.group(2) == "Z" else match.group(2)
    return datetime.fromisoformat(match.group(1) + zone).timestamp()


def compare(
    *,
    live_nodes: Entries,
    restored_nodes: Entries,
    live_users: Entries,
    restored_users: Entries,
    taken: float,
) -> tuple[bool, list[str]]:
    """Every node and user live had at `taken` is in the restore. Machine keys are compared, never printed."""
    lines: list[str] = []
    ok = True
    for kind, live, restored in (("node", live_nodes, restored_nodes), ("user", live_users, restored_users)):
        for entry_id, (label, key, created) in sorted(live.items()):
            what = f"{label} (id {entry_id})" if kind == "node" else f"user {label}"
            if created > taken:
                lines.append(f"INFO {what}: newer than the snapshot")
            elif entry_id not in restored:
                ok = False
                lines.append(f"FAIL {what}: live had it at snapshot time; missing from the restore")
            elif restored[entry_id][1] != key:
                ok = False
                lines.append(f"FAIL {what}: restored with a different machine key")
        for entry_id, (label, _, _) in sorted(restored.items()):
            if entry_id not in live:
                what = f"{label} (id {entry_id})" if kind == "node" else f"user {label}"
                lines.append(f"INFO {what}: deleted since the snapshot")
    if ok:
        lines.append(f"ok {len(restored_nodes)} nodes, {len(restored_users)} users restored")
    return ok, lines


def ssh(run: Run, target: str, command: str) -> tuple[int, str, str]:
    return run(["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes", target, command])


def _live_key_hashes(run: Run, target: str, volume: str) -> Optional[dict[str, str]]:
    """SHA-256 of each live key file, by file name. None when either cannot be read."""
    files = " ".join(f'"$m/{name}"' for name in KEYS)
    rc, out, _ = ssh(
        run, target, f"m=$(docker volume inspect -f '{{{{.Mountpoint}}}}' {volume}) && sudo -n sha256sum {files}"
    )
    hashes = {Path(path).name: digest for digest, _, path in (line.partition("  ") for line in out.splitlines())}
    if rc != 0 or set(hashes) != set(KEYS):
        return None
    return hashes


def sqlite_intact(database: Path) -> bool:
    """`PRAGMA integrity_check`, read-only, before anything opens the file for writing."""
    try:
        con = sqlite3.connect(f"file:{database}?mode=ro&immutable=1", uri=True)
        try:
            return bool(con.execute("PRAGMA integrity_check").fetchone() == ("ok",))
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return False


def _drill_config(cidr: str) -> str:
    """A config that serves the restored database and nothing else.

    No DERP map download, no MagicDNS and no listener outside the container, so
    the only network value in it is the address pool, `networking.tailscale_cidr`
    passed in by the caller. The socket sits
    in the data directory because the container runs as the invoking user, who
    cannot write `/var/run`. The embedded DERP server is on so that it loads the
    restored DERP key the way live does.
    """
    data = "/var/lib/headscale"
    return yaml.safe_dump(
        {
            "server_url": "https://drill.invalid",
            "listen_addr": "127.0.0.1:8080",
            "metrics_listen_addr": "127.0.0.1:9090",
            "grpc_listen_addr": "127.0.0.1:50443",
            "noise": {"private_key_path": f"{data}/noise_private.key"},
            "prefixes": {"v4": cidr, "allocation": "sequential"},
            "derp": {
                "server": {
                    "enabled": True,
                    "region_id": 999,
                    "region_code": "drill",
                    "region_name": "drill",
                    "stun_listen_addr": "127.0.0.1:3478",
                    "private_key_path": f"{data}/derp_server_private.key",
                    "automatically_add_embedded_derp_region": True,
                },
                "urls": [],
                "paths": [],
                "auto_update_enabled": False,
            },
            "dns": {"magic_dns": False, "override_local_dns": False},
            "database": {"type": "sqlite", "sqlite": {"path": f"{data}/{DATABASE}"}},
            "disable_check_updates": True,
            "unix_socket": f"{data}/headscale.sock",
            "unix_socket_permission": "0770",
            "logtail": {"enabled": False},
            "policy": {"mode": "database"},
        },
        sort_keys=False,
    )


@dataclass(frozen=True)
class LiveState:
    """What live Headscale holds: the drill's reference, read once on the workstation (BACKUP-071).

    Read apart from the restore so the restore can run on a host with no ssh path
    to the VPS. `hashes` are digests of the private keys, never the keys, and are
    still never printed.
    """

    nodes: Entries
    users: Entries
    hashes: dict[str, str]

    def to_payload(self) -> dict[str, Any]:
        """JSON-safe form: JSON objects key by string and have no tuples."""
        return {
            "nodes": {str(k): list(v) for k, v in self.nodes.items()},
            "users": {str(k): list(v) for k, v in self.users.items()},
            "hashes": dict(self.hashes),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "LiveState":
        def entries(raw: dict[str, Any]) -> Entries:
            return {int(k): (str(v[0]), str(v[1]), float(v[2])) for k, v in raw.items()}

        return cls(nodes=entries(payload["nodes"]), users=entries(payload["users"]), hashes=dict(payload["hashes"]))


def read_live(run: Run, ssh_target: str, volume: str) -> Optional[LiveState]:
    """Read live nodes, users and key hashes over ssh. None, after naming what failed, when any is unreadable."""
    # Live first: every check of the restore is "for each thing live has" (lesson-416).
    reads = {}
    for kind in ("nodes", "users"):
        rc, out, err = ssh(run, ssh_target, f"docker exec {LIVE_CONTAINER} headscale {kind} list -o json")
        try:
            reads[kind] = parse_entries(out, "machine_key" if kind == "nodes" else None) if rc == 0 else {}
        except (ValueError, KeyError) as exc:
            logger.error(f"drill: CANNOT CHECK — live Headscale {kind} could not be read: {str(exc)[:160]}")
            return None
        if not reads[kind]:
            logger.error(f"drill: CANNOT CHECK — live Headscale listed no {kind}: {err.strip()[:160]}")
            return None
    hashes = _live_key_hashes(run, ssh_target, volume)
    if hashes is None:
        logger.error("drill: CANNOT CHECK — the live key files could not be hashed (`sudo -n` on the VPS)")
        return None
    return LiveState(nodes=reads["nodes"], users=reads["users"], hashes=hashes)


def run_drill(
    *,
    repo: str,
    restic_env: dict[str, str],
    staging_dir: str,
    image: str,
    cidr: str,
    live: LiveState,
    run: Run = _default_run,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Restore the newest Headscale capture in `repo` and check it against `live`. True only on a whole restore.

    Opens no connection to the VPS: `live` comes from `read_live`, possibly on another host.
    """
    snapshot = latest_snapshot(run, repo, restic_env)
    if snapshot is None:
        return False

    ok = False
    with scratch(run, "hsdrill", holds="Headscale's private keys") as box:
        ok = _restore_and_check(
            run=run,
            repo=repo,
            restic_env=restic_env,
            snapshot=snapshot["short_id"],
            taken=snapshot_time(snapshot["time"]),
            source=f"{staging_dir}/{SERVICE}",
            workdir=box.workdir,
            name=box.name,
            image=image,
            cidr=cidr,
            live_nodes=live.nodes,
            live_users=live.users,
            live_hashes=live.hashes,
            sleep=sleep,
            clock=clock,
        )
    # A restore that passed but left the keys behind is not a pass.
    return ok and box.clean


def _restore_and_check(
    *,
    run: Run,
    repo: str,
    restic_env: dict[str, str],
    snapshot: str,
    taken: float,
    source: str,
    workdir: Path,
    name: str,
    image: str,
    cidr: str,
    live_nodes: Entries,
    live_users: Entries,
    live_hashes: dict[str, str],
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> bool:
    started = clock()
    data = restore_source(run, repo=repo, restic_env=restic_env, snapshot=snapshot, source=source, workdir=workdir)
    if data is None or not _capture_matches(data, live_hashes):
        return False
    logger.success(f"drill: restored {source} and checked it in {clock() - started:.0f}s")

    if not _serve(run, name, data, workdir, image, cidr, sleep, clock):
        return False
    ready = clock()
    restored = _restored_lists(run, name)
    if restored is None:
        return False

    ok, lines = compare(
        live_nodes=live_nodes,
        restored_nodes=restored[0],
        live_users=live_users,
        restored_users=restored[1],
        taken=taken,
    )
    report(lines)
    logger.info(f"drill: RTO {ready - started:.0f}s from download to a server that answers")
    if ok:
        logger.success(f"drill: snapshot {snapshot} restores Headscale completely")
    return ok


def _capture_matches(data: Path, live_hashes: dict[str, str]) -> bool:
    """The capture holds an intact database and the same private keys live runs with."""
    missing = [f for f in (DATABASE, *KEYS) if not (data / f).is_file()]
    if missing:
        logger.error(f"FAIL the capture lacks {', '.join(missing)}")
        return False
    if not sqlite_intact(data / DATABASE):
        logger.error(f"FAIL {DATABASE}: PRAGMA integrity_check did not answer ok")
        return False
    logger.success(f"drill: {DATABASE} integrity_check ok")

    keys_ok = True
    for file, label in KEYS.items():
        same = hashlib.sha256((data / file).read_bytes()).hexdigest() == live_hashes[file]
        keys_ok = keys_ok and same
        (logger.success if same else logger.error)(f"drill: {label}: {'match' if same else 'mismatch'}")
    return keys_ok


def _serve(
    run: Run,
    name: str,
    data: Path,
    workdir: Path,
    image: str,
    cidr: str,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> bool:
    """Start the restored server with no network and wait until its CLI answers."""
    config = workdir / "config"
    config.mkdir()
    (config / "config.yaml").write_text(_drill_config(cidr))
    # No network: a copy of the control plane must never be reachable by a node.
    rc, _, err = run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--network",
            "none",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "-v",
            f"{data}:/var/lib/headscale",
            "-v",
            f"{config}:/etc/headscale:ro",
            image,
            "serve",
        ]
    )
    if rc != 0:
        logger.error(f"drill: the restored server did not start: {err.strip()[:160]}")
        return False
    nodes_list = ["docker", "exec", name, "headscale", "nodes", "list", "-o", "json"]
    if not wait_until(lambda: run(nodes_list)[0] == 0, timeout=READY_TIMEOUT, sleep=sleep, clock=clock):
        logger.error(f"drill: the restored server did not answer within {READY_TIMEOUT}s")
        return False
    return True


def _restored_lists(run: Run, name: str) -> Optional[tuple[Entries, Entries]]:
    """The restored server's nodes and users, or None after naming what could not be read."""
    rc, nodes_out, err = run(["docker", "exec", name, "headscale", "nodes", "list", "-o", "json"])
    if rc == 0:
        rc, users_out, err = run(["docker", "exec", name, "headscale", "users", "list", "-o", "json"])
    try:
        if rc != 0:
            raise ValueError(err.strip()[:160])
        return parse_entries(nodes_out, "machine_key"), parse_entries(users_out, None)
    except (ValueError, KeyError) as exc:
        # The same guard as the live reads: an unreadable answer names itself.
        logger.error(f"drill: CANNOT CHECK — the restored server's lists could not be read: {str(exc)[:160]}")
        return None


def resolve_inputs(env: str = "prod", project_root: Optional[Path] = None) -> Optional[dict[str, Any]]:
    """Every input the drill takes, live state included, resolved on this machine. JSON-safe.

    None, after naming what is missing. Live is read here, over ssh and `sudo -n`
    on the VPS, so a host that runs the restore needs neither (BACKUP-071).
    """
    from toolkit.features.backup_destination import DestinationError, repo_url, repository_name, restic_context
    from toolkit.features.configuration import ConfigurationManager
    from toolkit.features.postgres_drill import staging_dir

    cm = ConfigurationManager(env, project_root)
    root = Path(project_root or cm.project_root)
    try:
        dest, restic_env = restic_context(cm)
    except DestinationError as exc:
        logger.error(str(exc))
        return None

    merged = cm.get_merged_config()
    sources = (merged.get("backup", {}) or {}).get("sources", {}) or {}
    nodes = [node for node, entries in sorted(sources.items()) if SERVICE in (entries or {})]
    if len(nodes) != 1:
        logger.error(f"drill: expected one node capturing {SERVICE} in backup.sources, found {nodes or 'none'}")
        return None
    net = merged["networking"]
    live = read_live(
        _default_run,
        f"{net['ssh_users']['cloud']}@{net['vps']['public_ip']}",
        str(sources[nodes[0]][SERVICE]["volume"]),
    )
    if live is None:
        return None
    return {
        "repo": repo_url(dest, repository_name(cm, nodes[0])),
        "restic_env": dict(restic_env),
        "staging_dir": staging_dir(root),
        "image": str(merged["apps"]["services"]["core"]["headscale"]["image"]),
        "cidr": str(net["tailscale_cidr"]),
        "live": live.to_payload(),
    }


def run_from_inputs(inputs: dict[str, Any]) -> bool:
    """Run the restore half on resolved inputs. Opens no connection to the VPS and reads no config."""
    return run_drill(
        repo=str(inputs["repo"]),
        restic_env={str(k): str(v) for k, v in inputs["restic_env"].items()},
        staging_dir=str(inputs["staging_dir"]),
        image=str(inputs["image"]),
        cidr=str(inputs["cidr"]),
        live=LiveState.from_payload(inputs["live"]),
        run=_default_run,
    )


def drill_headscale(env: str = "prod", project_root: Optional[Path] = None) -> bool:
    """Resolve every input from the SSOT, read live, and run the drill on this machine."""
    logger.section(f"headscale restore drill — newest capture in R2 into a scratch container ({env})")
    inputs = resolve_inputs(env, project_root)
    return inputs is not None and run_from_inputs(inputs)
