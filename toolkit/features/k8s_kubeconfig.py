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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from toolkit.config.settings import settings
from toolkit.core.logging import logger
from toolkit.features import command

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


def fetch_argv(ssh_alias: str) -> list[str]:
    """SSH argv that prints the remote k3s admin kubeconfig to stdout."""
    return ["ssh", ssh_alias, "sudo", "cat", _K3S_KUBECONFIG_PATH]


def output_path(env: str) -> Path:
    """Local kubeconfig path for a cluster (``~/.kube/kubelab-<env>-config``)."""
    return Path(os.path.expanduser(_KUBECONFIG_OUT_PATTERN.format(env=env)))


def fetch_kubeconfig(env: str) -> Path:
    """Fetch, rewrite, and save the kubeconfig for one cluster. Returns the path.

    The SSH read uses the operator's ``~/.ssh/config`` and needs interactive key
    auth (passphrase / ssh-agent), so this runs from an operator shell, not an
    unattended one.
    """
    access = load_cluster_access(env)
    logger.section(f"Fetch kubeconfig — {env} (node {access.node}, ssh {access.ssh_alias})")

    result = command.run_list(fetch_argv(access.ssh_alias))
    rewritten = rewrite_server(result.stdout, access.local_port)

    dest = output_path(env)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(rewritten)
    dest.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600 — kubeconfig holds admin certs

    logger.success(
        f"Saved {dest} (server https://127.0.0.1:{access.local_port}). "
        f"Bring up the transport for {env} before using kubectl (ADR-052 `k8s connect`)."
    )
    return dest
