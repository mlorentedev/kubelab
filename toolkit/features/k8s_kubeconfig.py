"""Fetch a per-cluster kubeconfig with a transport-agnostic server (ADR-052).

Reads the ``clusters`` SSOT in ``common.yaml``, SSHes to the cluster's k3s
server to read ``/etc/rancher/k3s/k3s.yaml``, rewrites the apiserver to a
stable local endpoint (``https://127.0.0.1:<local_port>``), and saves it to
``~/.kube/kubelab-<env>-config``.

The local port is mapped to the real apiserver by the *transport*
(``k8s connect``, ADR-052 Phase 2): direct for prod's public IP, an SSH
local-forward on the LAN, or ts-bridge over the mesh. Pinning the kubeconfig
to ``127.0.0.1`` is what lets one kubeconfig work from any machine — including
a non-admin box with no native Tailscale — because k3s' server certificate
SANs include ``127.0.0.1``, so TLS still verifies.

The pure helpers (``load_cluster_access``, ``rewrite_server``, ``fetch_argv``,
``output_path``) carry the logic and are unit-tested without a network; only
``fetch_kubeconfig`` does I/O (the SSH read needs interactive key auth).
"""

import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from toolkit.config.settings import settings
from toolkit.core.logging import logger
from toolkit.features.k8s_connect import (
    _load_config as _load_kubeconfig_config,
)
from toolkit.features.k8s_connect import (
    _node_block,
    find_free_port,
    resolve_ssh_tunnel_params,
    resolve_transport,
    ts_bridge_tunnel,
)

# k3s writes its admin kubeconfig here; the apiserver defaults to 127.0.0.1:6443.
_K3S_KUBECONFIG_PATH = "/etc/rancher/k3s/k3s.yaml"
_K3S_DEFAULT_SERVER = "https://127.0.0.1:6443"
_KUBECONFIG_OUT_PATTERN = "~/.kube/kubelab-{env}-config"
_REQUIRED_KEYS = ("node", "ssh_alias", "local_port")


@dataclass(frozen=True)
class ClusterAccess:
    """Operator-access metadata for one cluster (the ``clusters.<name>`` SSOT)."""

    name: str
    node: str
    ssh_alias: str
    local_port: int

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> "ClusterAccess":
        missing = [k for k in _REQUIRED_KEYS if k not in data]
        if missing:
            raise KeyError(f"clusters.{name} is missing required keys: {', '.join(missing)}")
        return cls(
            name=name,
            node=str(data["node"]),
            ssh_alias=str(data["ssh_alias"]),
            local_port=int(data["local_port"]),
        )


def _common_path() -> Path:
    return settings.project_root / "infra" / "config" / "values" / "common.yaml"


def load_clusters(common_path: Path | None = None) -> dict[str, ClusterAccess]:
    """Load every ``clusters.<name>`` entry from the common.yaml SSOT."""
    path = common_path or _common_path()
    with open(path) as f:
        config = yaml.safe_load(f) or {}
    raw = config.get("clusters") or {}
    return {name: ClusterAccess.from_dict(name, data) for name, data in raw.items()}


def load_cluster_access(env: str, common_path: Path | None = None) -> ClusterAccess:
    """Resolve one cluster's access metadata; the error lists the valid names."""
    clusters = load_clusters(common_path)
    try:
        return clusters[env]
    except KeyError:
        valid = ", ".join(sorted(clusters)) or "(none declared)"
        raise KeyError(f"unknown cluster {env!r}; declared clusters: {valid}") from None


def rewrite_server(kubeconfig_text: str, local_port: int) -> str:
    """Repoint the apiserver to the stable local endpoint (ADR-052 D1).

    ``k3s.yaml`` ships ``server: https://127.0.0.1:6443``. Only the port is
    rewritten (the host stays ``127.0.0.1``) so TLS still verifies against the
    k3s cert's ``127.0.0.1`` SAN. Raises if the expected default is absent —
    failing loudly beats writing a kubeconfig that points nowhere.
    """
    if _K3S_DEFAULT_SERVER not in kubeconfig_text:
        raise ValueError(
            f"expected {_K3S_DEFAULT_SERVER!r} in the fetched kubeconfig; the k3s "
            "default may have changed — refusing to write an unverified server"
        )
    return kubeconfig_text.replace(_K3S_DEFAULT_SERVER, f"https://127.0.0.1:{local_port}")


def rewrite_server_direct(kubeconfig_text: str, target_host: str, apiserver_port: int) -> str:
    """Repoint the apiserver at the node's own endpoint, with no transport between.

    The counterpart to ``rewrite_server``, for the case ADR-052 does not cover:
    an operator box that is *already* on the mesh. The tunnel exists so one
    kubeconfig works from a machine with no native Tailscale; on a machine that
    has it, the tunnel is a hop that buys nothing and costs a running process
    and its own credential.

    ``target_host`` is whatever ``resolve_transport`` resolved, and it is NOT
    always a MagicDNS name — an earlier version of this docstring claimed it was,
    while invoking the aws1 lesson to justify the claim. Measured, the three
    shapes in this fleet are:

    ===========  =====================  ====================================
    cluster      resolves to            why
    ===========  =====================  ====================================
    ``hub``      ``gcp1.kubelab.…``     cattle: ``tailscale_dns``, no ``_ip``
    ``prod``     ``162.55.57.175``      the VPS declares a ``public_ip``
    ``staging``  ``100.64.0.11``        ace1 declares a stable ``tailscale_ip``
    ===========  =====================  ====================================

    All three are correct. The aws1 lesson is that an address which ROTATES must
    not be cached, and it binds exactly where rotation happens: the hubs, whose
    machine is replaced on every preemption, and which the SSOT marks by carrying
    ``tailscale_dns`` with no ``tailscale_ip``. A literal for a node that never
    moves is redundant, not wrong. Stating that here rather than restating the
    rule as an absolute, because the absolute version was false about this very
    function.

    TLS verifies in all three cases, and for the same reason the ``127.0.0.1``
    form does: k3s puts each of these in the serving certificate's SANs
    (measured — ``DNS:aws1.kubelab.internal`` on the hub, the public IP on the
    VPS). Nothing here is insecure-skip.

    Raises for the same reason ``rewrite_server`` does — an unrecognised server
    means the k3s default moved, and writing an unverified endpoint is worse
    than failing.
    """
    if _K3S_DEFAULT_SERVER not in kubeconfig_text:
        raise ValueError(
            f"expected {_K3S_DEFAULT_SERVER!r} in the fetched kubeconfig; the k3s "
            "default may have changed — refusing to write an unverified server"
        )
    return kubeconfig_text.replace(_K3S_DEFAULT_SERVER, f"https://{target_host}:{apiserver_port}")


def fetch_argv(ssh_alias: str, accept_new: bool = False) -> list[str]:
    """SSH argv that prints the remote k3s admin kubeconfig to stdout.

    ``accept_new`` adds ``StrictHostKeyChecking=accept-new``, and is set only
    for a node whose identity the SSOT marks ephemeral — see
    ``node_identity_is_ephemeral``. It records an unknown key instead of
    prompting; it still REFUSES a changed one, which is why the purge below has
    to happen first and why this flag alone would not fix anything.
    """
    opts = ["-o", "StrictHostKeyChecking=accept-new"] if accept_new else []
    return ["ssh", *opts, ssh_alias, "sudo", "cat", _K3S_KUBECONFIG_PATH]


def node_identity_is_ephemeral(env: str, common_path: Path | None = None) -> bool:
    """True iff the SSOT marks this cluster's node as recreated rather than restarted.

    The marker is the one `wait-node-ready.yml` already uses: ``tailscale_dns``
    with **no** ``tailscale_ip``. `networking.gcp` records the hub that way
    deliberately — it is a Spot VM in a MIG, so a preemption self-heals by
    creating a new machine, and every stable node in the fleet declares an IP.

    Scoped on purpose. A host key is a real protection, and a node whose machine
    outlives its key rotation should keep failing loudly when that key changes.
    """
    config = _load_kubeconfig_config(common_path)
    clusters = config.get("clusters") or {}
    cluster = clusters.get(env)
    if not cluster:
        return False
    block = _node_block(config.get("networking") or {}, str(cluster["node"]))
    return bool(block.get("tailscale_dns")) and not block.get("tailscale_ip")


def resolve_ssh_hostname(ssh_alias: str) -> str:
    """The hostname SSH will actually connect to for ``ssh_alias``.

    Asked of ssh itself (``ssh -G``) rather than assumed, because
    ``known_hosts`` is keyed by the resolved hostname and not by the alias:
    measured, alias ``gcp1`` resolves to ``gcp1.kubelab.internal``, so purging
    the alias would be a no-op that looks like it worked. Falls back to the
    alias if ssh cannot be asked — the purge then no-ops, which is the same
    place we were before.
    """
    result = subprocess.run(["ssh", "-G", ssh_alias], capture_output=True, text=True)
    if result.returncode != 0:
        return ssh_alias
    for line in result.stdout.splitlines():
        if line.startswith("hostname "):
            return line.split(" ", 1)[1].strip()
    return ssh_alias


def forget_host_key(hostname: str) -> bool:
    """Drop ``hostname`` from known_hosts. Idempotent: absent means no-op.

    Uses ``ssh-keygen -R`` rather than editing the file, and that is not a
    stylistic choice: with ``HashKnownHosts`` on — the default on this
    workstation, measured — hostnames are stored hashed, so no text search can
    find the entry. ``ssh-keygen`` hashes the candidate and compares.

    **This is a mitigation, not the fix**, and it should not be read as one.
    Purging means trusting whatever key the host now presents — TOFU, every
    time. The exposure is bounded only because every path to these nodes rides
    Tailscale and WireGuard has already authenticated the peer, which makes the
    SSH host key a weaker second check of the same fact. It is not nothing: a
    compromised node holding valid Tailscale credentials would still be caught
    by a host key, and this gives that up.

    The real fix is SSH host certificates — trust a CA instead of a list of
    machines. Tracked as #1261, WHICH ALSO REQUIRES DELETING THIS FUNCTION:
    leaving both means the purge silently covers for a broken CA. Deliberately
    the same wording as `wait-node-ready.yml:98`, which made this decision first
    for the Ansible path; two mechanisms with one policy, not two policies.
    """
    result = subprocess.run(["ssh-keygen", "-R", hostname], capture_output=True, text=True)
    return result.returncode == 0


def output_path(env: str) -> Path:
    """Local kubeconfig path for a cluster (``~/.kube/kubelab-<env>-config``)."""
    return Path(os.path.expanduser(_KUBECONFIG_OUT_PATTERN.format(env=env)))


# SSH exit code 255 signals a connection-layer failure.  These stderr substrings
# identify *network* failures where a tunnel fallback is appropriate.  Auth failures
# ("Permission denied", "publickey") also exit 255 but must NOT trigger the fallback
# — they indicate a key/permission problem that the tunnel won't fix.
_SSH_CONNECT_FAILURES = (
    "timed out",
    "no route to host",
    "connection refused",
    "network is unreachable",
    "temporary failure in name resolution",
    "name or service not known",
    "connection reset by peer",
)


def _is_connect_failure(returncode: int, stderr: str) -> bool:
    """True iff the SSH failure is a *network/routing* error safe to fall back from."""
    if returncode != 255:
        return False
    s = stderr.lower()
    return any(pattern in s for pattern in _SSH_CONNECT_FAILURES)


def fetch_kubeconfig(env: str, direct: bool = False) -> Path:
    """Fetch, rewrite, and save the kubeconfig for one cluster. Returns the path.

    Tries a direct ``ssh <alias>`` first.  If the connection fails due to a
    network/routing error (e.g., mesh IP not reachable from a non-admin box),
    it re-routes the read through a transient ts-bridge SSH tunnel.  An auth
    failure always raises immediately — the tunnel won't fix a key problem.

    Interactive key auth (passphrase / ssh-agent) is still required; this runs
    from an operator shell, not an unattended one.

    ``direct`` selects ``rewrite_server_direct`` — the mesh-native form, for an
    operator box already on the tailnet. It is an explicit flag rather than a
    detection of what happens to be installed, deliberately: a file whose
    contents depend on the ambient toolchain is a file whose provenance nobody
    can read back, which is how the hand-made hub kubeconfig came to exist in
    the first place.

    Note ``direct`` changes only what is *written*. The fetch itself is SSH
    either way, so ``clusters.<env>.ssh_alias`` must resolve regardless.
    """
    access = load_cluster_access(env)
    logger.section(f"Fetch kubeconfig — {env} (node {access.node}, ssh {access.ssh_alias})")

    # A node the SSOT marks ephemeral presents a new host key after every
    # recreate, and a CHANGED key stops ssh dead — on the recovery path of the
    # thing most likely to need recovering (#1380). Purge first, then let
    # `accept-new` record what the new machine presents.
    #
    # This also fixes the failure that looks unrelated: `x509: certificate
    # signed by unknown authority` against the hub is a STALE CACHED
    # kubeconfig, because the recreate rotated the k3s CA too and that CA
    # travels inside the file this function fetches. One cause, two symptoms,
    # and the host key blocked the remedy for the other.
    ephemeral = node_identity_is_ephemeral(env)
    if ephemeral:
        hostname = resolve_ssh_hostname(access.ssh_alias)
        forget_host_key(hostname)
        logger.info(f"{access.node} is recreated rather than restarted; forgot any stale host key for {hostname}.")

    argv = fetch_argv(access.ssh_alias, accept_new=ephemeral)
    result = subprocess.run(argv, capture_output=True, text=True)

    if result.returncode == 0:
        raw = result.stdout
    elif _is_connect_failure(result.returncode, result.stderr):
        logger.info(
            f"Direct SSH to {access.ssh_alias!r} unreachable "
            f"({result.stderr.strip()!r}); routing via ts-bridge SSH tunnel..."
        )
        raw = _fetch_via_tunnel(env, access)
    else:
        raise RuntimeError(f"SSH fetch failed (code {result.returncode}): {result.stderr.strip()}")

    if direct:
        transport = resolve_transport(env)
        rewritten = rewrite_server_direct(raw, transport.target_host, transport.apiserver_port)
        endpoint = f"https://{transport.target_host}:{transport.apiserver_port}"
        follow_up = "no transport needed — this box reaches the mesh natively."
    else:
        rewritten = rewrite_server(raw, access.local_port)
        endpoint = f"https://127.0.0.1:{access.local_port}"
        follow_up = f"Bring up the transport for {env} before using kubectl (ADR-052 `k8s connect`)."

    dest = output_path(env)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(rewritten)
    dest.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600 — kubeconfig holds admin certs

    logger.success(f"Saved {dest} (server {endpoint}). {follow_up}")
    return dest


def _fetch_via_tunnel(env: str, access: ClusterAccess, common_path: Path | None = None) -> str:
    """Read k3s.yaml via a transient ts-bridge SSH tunnel (non-admin box fallback).

    The tunnel forwards ``127.0.0.1:<ephemeral>`` -> ``<mesh_host>:22`` so the SSH
    command never touches the mesh IP directly.  The tunnel is torn down by
    ``ts_bridge_tunnel``'s ``finally`` block regardless of success or failure.

    ``known_hosts`` behaviour: ``UserKnownHostsFile=/dev/null`` + ``accept-new``
    avoids "host key changed" errors when the same local port maps to different real
    hosts across runs.
    """
    ssh_user, mesh_host = resolve_ssh_tunnel_params(env, common_path)
    local_port = find_free_port()

    logger.info(f"ts-bridge SSH tunnel: 127.0.0.1:{local_port} -> {mesh_host}:22 ({ssh_user}@)")
    with ts_bridge_tunnel(mesh_host, 22, local_port):
        result = subprocess.run(
            [
                "ssh",
                "-p",
                str(local_port),
                "-o",
                "UserKnownHostsFile=/dev/null",
                "-o",
                "StrictHostKeyChecking=accept-new",
                f"{ssh_user}@127.0.0.1",
                "sudo",
                "cat",
                _K3S_KUBECONFIG_PATH,
            ],
            capture_output=True,
            text=True,
        )

    if result.returncode != 0:
        raise RuntimeError(f"SSH via tunnel failed (code {result.returncode}): {result.stderr.strip()}")
    return result.stdout
