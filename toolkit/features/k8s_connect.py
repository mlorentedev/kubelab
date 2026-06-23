"""Cluster-access transport - bring up / tear down / inspect the local->apiserver
tunnel that backs the transport-agnostic kubeconfig (ADR-052 Phase 2 / TOOL-014).

The fetched kubeconfig pins ``server: https://127.0.0.1:<local_port>`` (see
``k8s_kubeconfig``). This module maps that local port to the real apiserver:

* **staging / hub** -> **ts-bridge**, a userspace ``tsnet`` TCP bridge over the
  Headscale mesh. It forwards ``127.0.0.1:<local_port>`` -> ``<node-mesh-ip>:6443``
  with no TUN and no admin, so it works on a corporate non-admin box.
* **prod** -> its **public** apiserver endpoint, reachable directly (the k3s prod
  cert SAN covers the public IP). No tunnel is started - ``connect`` only verifies
  reachability; the prod kubeconfig targets the public endpoint.

The transport *target* is **derived** from the ``clusters.<env>.node`` reference
against ``networking.{nodes.*, vps, aws}`` in ``common.yaml`` - no addresses are
duplicated into the ``clusters`` block, and nothing is hardcoded here.

The pure helpers (``resolve_transport``, ``ts_bridge_argv``, ``locate_ts_bridge``,
``TransportState`` (de)serialization) carry the logic and are unit-tested without a
network. ``connect`` / ``disconnect`` / ``status`` do the I/O (spawn, port probe,
terminate).
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Generator

import yaml

from toolkit.config.settings import settings
from toolkit.core.logging import logger

# k3s serves the apiserver on 6443; overridable per cluster via clusters.<env>.apiserver_port.
_DEFAULT_APISERVER_PORT = 6443

# ts-bridge binary discovery: env override -> well-known install dir -> PATH.
_TS_BRIDGE_ENV = "TS_BRIDGE_BIN"
_TS_BRIDGE_DEFAULTS: tuple[str, ...] = ("~/Apps/ts-bridge/ts-bridge.exe", "~/Apps/ts-bridge/ts-bridge")

# Per-env transport statefile, next to the kubeconfigs it pairs with.
_STATEFILE_PATTERN = "~/.kube/.kubelab-transport-{env}.json"

# How long connect waits for the local port to come up before declaring failure.
_HEALTHCHECK_TIMEOUT_S = 20.0
_HEALTHCHECK_INTERVAL_S = 0.5


@dataclass(frozen=True)
class ClusterTransport:
    """The resolved transport for one cluster (ADR-052 D3).

    ``kind`` is ``"ts-bridge"`` (mesh tunnel) or ``"public"`` (direct, no tunnel).
    ``target_host`` is the apiserver host the transport reaches - a mesh address
    for ts-bridge, the public IP for the direct path.
    """

    env: str
    kind: str
    target_host: str
    apiserver_port: int
    local_port: int


@dataclass(frozen=True)
class TransportState:
    """What ``connect`` recorded so ``disconnect`` / ``status`` can act on it."""

    env: str
    kind: str
    pid: int
    local_port: int
    target: str

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: Path) -> "TransportState | None":
        if not path.is_file():
            return None
        return cls(**json.loads(path.read_text()))


def _common_path() -> Path:
    return settings.project_root / "infra" / "config" / "values" / "common.yaml"


def _load_config(common_path: Path | None = None) -> dict[str, Any]:
    with open(common_path or _common_path()) as f:
        return yaml.safe_load(f) or {}


def _node_block(networking: dict[str, Any], node: str) -> dict[str, Any]:
    """Position-aware lookup of a cluster's node block (mirrors SSOT-014a).

    Homelab nodes live under ``networking.nodes.<node>``; the cloud nodes live at
    the top level (``networking.vps`` / ``networking.aws``), keyed by convention
    or by ``hostname``. Raises ``KeyError`` naming the node if none matches.
    """
    nodes = networking.get("nodes") or {}
    if node in nodes:
        return nodes[node]
    for key in ("vps", "aws"):
        block = networking.get(key)
        if block and (key == node or block.get("hostname") == node):
            return block
    raise KeyError(f"node {node!r} not found under networking.nodes / networking.vps / networking.aws")


def resolve_transport(env: str, common_path: Path | None = None) -> ClusterTransport:
    """Resolve a cluster's transport from the ``clusters`` + ``networking`` SSOT.

    A cluster whose node exposes a ``public_ip`` (prod's VPS) is reached directly
    (``kind="public"``, no tunnel); every other cluster is reached via ts-bridge
    over the mesh, targeting the node's ``tailscale_dns`` (preferred) or
    ``tailscale_ip``. The error for an unknown env lists the declared clusters.
    """
    config = _load_config(common_path)
    clusters = config.get("clusters") or {}
    try:
        cluster = clusters[env]
    except KeyError:
        valid = ", ".join(sorted(clusters)) or "(none declared)"
        raise KeyError(f"unknown cluster {env!r}; declared clusters: {valid}") from None

    networking = config.get("networking") or {}
    block = _node_block(networking, str(cluster["node"]))
    apiserver_port = int(cluster.get("apiserver_port", _DEFAULT_APISERVER_PORT))
    local_port = int(cluster["local_port"])

    public_ip = block.get("public_ip")
    if public_ip:
        return ClusterTransport(env, "public", str(public_ip), apiserver_port, local_port)

    mesh_host = block.get("tailscale_dns") or block.get("tailscale_ip")
    if not mesh_host:
        raise KeyError(
            f"cluster {env!r} node {cluster['node']!r} has no public_ip / tailscale_dns / tailscale_ip in the SSOT"
        )
    return ClusterTransport(env, "ts-bridge", str(mesh_host), apiserver_port, local_port)


def ts_bridge_argv(
    binary: str | os.PathLike[str],
    target_host: str,
    target_port: int,
    local_port: int,
) -> list[str]:
    """Build the ts-bridge argv for a manual-mode tunnel to target_host:target_port.

    ``--manual-mode`` pins the bind to ``--local-addr`` instead of auto-selecting a
    port from a range.  Auth (``TS_AUTHKEY``) and control-plane URL come from
    ts-bridge's own ``.env`` (loaded via the binary's working directory), so kubelab
    never handles the Headscale preauth key.

    Works for any TCP target — apiserver (port 6443) or SSH (port 22).
    """
    return [
        str(binary),
        "connect",
        "--manual-mode",
        "--target",
        f"{target_host}:{target_port}",
        "--local-addr",
        f"127.0.0.1:{local_port}",
    ]


def locate_ts_bridge() -> Path:
    """Find the ts-bridge binary, or fail with an actionable message.

    Resolution order: ``TS_BRIDGE_BIN`` env -> the well-known install dir -> ``PATH``.
    """
    override = os.getenv(_TS_BRIDGE_ENV)
    candidates = [override, *_TS_BRIDGE_DEFAULTS] if override else list(_TS_BRIDGE_DEFAULTS)
    for candidate in candidates:
        path = Path(os.path.expanduser(candidate))
        if path.is_file():
            return path
    on_path = shutil.which("ts-bridge")
    if on_path:
        return Path(on_path)
    raise FileNotFoundError(
        f"ts-bridge binary not found. Set {_TS_BRIDGE_ENV} to its path, install it under "
        "~/Apps/ts-bridge/, or put it on PATH. Releases: https://github.com/mlorentedev/ts-bridge/releases"
    )


def statefile_path(env: str) -> Path:
    return Path(os.path.expanduser(_STATEFILE_PATTERN.format(env=env)))


def find_free_port() -> int:
    """Return an OS-assigned free loopback port (bind 0, then close)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def resolve_ssh_user(networking: dict[str, Any], node: str) -> str:
    """Return the OS SSH user for *node* per SSOT-014a (networking.ssh_users.<category>).

    Nodes under ``networking.nodes.*`` are ``homelab``; ``vps`` / ``aws`` are ``cloud``.
    Raises ``KeyError`` with an actionable message when the category is missing.
    """
    nodes = networking.get("nodes") or {}
    category = "homelab" if node in nodes else "cloud"
    ssh_users = networking.get("ssh_users") or {}
    user = ssh_users.get(category)
    if not user:
        raise KeyError(f"networking.ssh_users.{category} not declared (node {node!r})")
    return str(user)


def resolve_ssh_tunnel_params(env: str, common_path: Path | None = None) -> tuple[str, str]:
    """Return ``(ssh_user, mesh_host)`` for SSH-tunnelling into cluster *env*.

    Used by ``fetch_kubeconfig`` when the direct SSH alias is unreachable and the
    read must be routed through a transient ts-bridge SSH tunnel.
    """
    config = _load_config(common_path)
    clusters = config.get("clusters") or {}
    try:
        cluster = clusters[env]
    except KeyError:
        valid = ", ".join(sorted(clusters)) or "(none declared)"
        raise KeyError(f"unknown cluster {env!r}; declared clusters: {valid}") from None

    networking = config.get("networking") or {}
    node = str(cluster["node"])
    block = _node_block(networking, node)

    mesh_host = block.get("tailscale_dns") or block.get("tailscale_ip")
    if not mesh_host:
        raise KeyError(f"cluster {env!r} node {node!r} has no mesh address for SSH tunnel fallback")

    return resolve_ssh_user(networking, node), str(mesh_host)


@contextmanager
def ts_bridge_tunnel(target_host: str, target_port: int, local_port: int) -> Generator[int, None, None]:
    """Transient ts-bridge tunnel; guaranteed teardown even when the body raises.

    Spawns ts-bridge in ``--manual-mode`` forwarding ``127.0.0.1:<local_port>``
    to ``target_host:target_port``, waits for the local port to accept connections,
    yields the child PID for the caller to inspect, then terminates the process in
    the ``finally`` block regardless of whether the body succeeds or raises.

    Use this for short-lived tunnels (e.g., an SSH read of ``k3s.yaml``) that must
    not outlive the operation.  For persistent tunnels use ``connect`` / ``disconnect``.
    """
    binary = locate_ts_bridge()
    argv = ts_bridge_argv(binary, target_host, target_port, local_port)
    proc = subprocess.Popen(
        argv,
        cwd=str(binary.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + _HEALTHCHECK_TIMEOUT_S
        while time.monotonic() < deadline:
            if _port_listening(local_port):
                break
            if proc.poll() is not None:
                raise RuntimeError(
                    f"ts-bridge exited early (code {proc.returncode}); check auth in {binary.parent}/.env"
                )
            time.sleep(_HEALTHCHECK_INTERVAL_S)
        else:
            raise TimeoutError(
                f"ts-bridge tunnel {target_host}:{target_port} -> 127.0.0.1:{local_port} "
                f"did not come up in {_HEALTHCHECK_TIMEOUT_S:.0f}s"
            )
        yield proc.pid
    finally:
        _terminate(proc.pid)


def _port_listening(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    """True iff a TCP connect to host:port succeeds (the transport is up)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def _terminate(pid: int) -> None:
    """Best-effort cross-platform terminate of a detached child by pid."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"], check=False, capture_output=True)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def connect(env: str) -> bool:
    """Bring up the transport for ``env`` (idempotent). Returns True on success.

    For ``public`` (prod) this is a reachability check, not a tunnel. For
    ``ts-bridge`` it is a no-op when the local port already answers; otherwise it
    spawns ts-bridge detached, waits for the local port, and records the statefile.
    """
    transport = resolve_transport(env)
    endpoint = f"{transport.target_host}:{transport.apiserver_port}"
    logger.section(f"Cluster access - connect {env} ({transport.kind} -> {endpoint})")

    if transport.kind == "public":
        reachable = _port_listening(transport.apiserver_port, host=transport.target_host, timeout=5.0)
        if reachable:
            logger.success(f"prod apiserver reachable at {endpoint} - direct public endpoint, no tunnel")
            return True
        logger.error(f"prod apiserver NOT reachable at {endpoint} (public endpoint). Check network/firewall.")
        return False

    if _port_listening(transport.local_port):
        logger.success(f"transport already up: 127.0.0.1:{transport.local_port} is listening - no-op")
        return True

    try:
        binary = locate_ts_bridge()
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return False

    argv = ts_bridge_argv(binary, transport.target_host, transport.apiserver_port, transport.local_port)
    logger.info(f"Starting ts-bridge: {' '.join(argv)} (cwd {binary.parent})")
    # Detach so the bridge outlives this CLI; run in the binary's dir to reuse its .env auth.
    proc = subprocess.Popen(
        argv,
        cwd=str(binary.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )

    deadline = time.monotonic() + _HEALTHCHECK_TIMEOUT_S
    while time.monotonic() < deadline:
        if _port_listening(transport.local_port):
            TransportState(
                env=env,
                kind=transport.kind,
                pid=proc.pid,
                local_port=transport.local_port,
                target=endpoint,
            ).save(statefile_path(env))
            logger.success(f"transport up: 127.0.0.1:{transport.local_port} -> {endpoint} (pid {proc.pid})")
            return True
        if proc.poll() is not None:
            logger.error(f"ts-bridge exited early (code {proc.returncode}); check auth in {binary.parent}/.env")
            return False
        time.sleep(_HEALTHCHECK_INTERVAL_S)

    logger.error(f"timed out after {_HEALTHCHECK_TIMEOUT_S:.0f}s waiting for 127.0.0.1:{transport.local_port}")
    _terminate(proc.pid)
    return False


def disconnect(env: str) -> bool:
    """Tear down the transport for ``env`` (idempotent). Returns True on success."""
    transport = resolve_transport(env)
    logger.section(f"Cluster access - disconnect {env}")

    if transport.kind == "public":
        logger.info("prod uses the direct public endpoint - nothing to tear down")
        return True

    path = statefile_path(env)
    state = TransportState.load(path)
    if state is None and not _port_listening(transport.local_port):
        logger.info("transport already down - no-op")
        return True

    if state is not None:
        logger.info(f"terminating ts-bridge (pid {state.pid})")
        _terminate(state.pid)
        path.unlink(missing_ok=True)
    else:
        logger.warning(f"127.0.0.1:{transport.local_port} listening but no statefile - not ours, leaving it")
        return False

    logger.success(f"transport for {env} torn down")
    return True


def status(env: str) -> bool:
    """Report the transport state for ``env``. Returns True iff it is usable."""
    transport = resolve_transport(env)
    endpoint = f"{transport.target_host}:{transport.apiserver_port}"
    logger.section(f"Cluster access - status {env}")

    if transport.kind == "public":
        reachable = _port_listening(transport.apiserver_port, host=transport.target_host, timeout=5.0)
        verdict = "reachable" if reachable else "UNREACHABLE"
        logger.info(f"transport: direct public endpoint (no tunnel) -> {endpoint} [{verdict}]")
        logger.info("prod kubeconfig should target the public apiserver directly")
        return reachable

    up = _port_listening(transport.local_port)
    state = TransportState.load(statefile_path(env))
    pid = f"pid {state.pid}" if state else "no statefile"
    logger.info(f"transport: ts-bridge -> {endpoint}")
    logger.info(f"local endpoint 127.0.0.1:{transport.local_port}: {'UP' if up else 'down'} ({pid})")
    return up
