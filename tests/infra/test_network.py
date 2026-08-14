"""Infrastructure: Network connectivity — VPS, Tailscale mesh, DNS resolution."""

from __future__ import annotations

import socket
import subprocess

import pytest
import yaml

from .fixtures import _COMMON, _REPO_ROOT, NodeInfo, node_ssh_run

pytestmark = pytest.mark.infra

_VPS_PUBLIC_IP = _COMMON["networking"]["vps"]["public_ip"]


def _get_base_domain(env: str) -> str:
    """Read base_domain for the given environment from config values."""
    env_path = _REPO_ROOT / "infra" / "config" / "values" / f"{env}.yaml"
    if env_path.exists():
        with open(env_path) as f:
            env_config = yaml.safe_load(f) or {}
        domain = env_config.get("global", {}).get("base_domain")
        if domain:
            return domain
    return _COMMON["global"]["base_domain"]


class TestVPSConnectivity:
    """VPS must be publicly reachable on port 443."""

    def test_vps_public_https(self, vps_node: NodeInfo) -> None:
        """VPS must accept TCP connections on port 443."""
        try:
            with socket.create_connection((_VPS_PUBLIC_IP, 443), timeout=5):
                pass
        except (OSError, TimeoutError) as exc:
            pytest.fail(f"VPS public IP ({_VPS_PUBLIC_IP}) not reachable on 443: {exc}")


class TestTailscaleMesh:
    """All nodes must be reachable via Tailscale."""

    def test_tailscale_ping_all_nodes(
        self,
        inventory: list[NodeInfo],
    ) -> None:
        """Tailscale ping must succeed to all inventory nodes (direct or relayed)."""
        errors: list[str] = []
        for node in inventory:
            try:
                result = subprocess.run(
                    ["tailscale", "ping", "--c", "1", "--timeout", "5s", node.host],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                has_pong = "pong" in result.stdout.lower()
                if result.returncode != 0 and not has_pong:
                    errors.append(f"{node.name} ({node.host}): unreachable — {result.stderr.strip()}")
            except subprocess.TimeoutExpired:
                errors.append(f"{node.name} ({node.host}): ping timed out")
            except FileNotFoundError:
                pytest.skip("tailscale CLI not available")

        assert not errors, "Tailscale mesh connectivity failures:\n" + "\n".join(errors)


class TestDNSResolution:
    """DNS resolution must work for kubelab domains."""

    def test_dns_from_rpi4(
        self,
        gateway_nodes: list[NodeInfo],
    ) -> None:
        """RPi4 (DNS gateway) must resolve kubelab domains."""
        rpi4 = next((n for n in gateway_nodes if "rpi4" in n.name), None)
        if not rpi4:
            pytest.skip("RPi4 not in inventory")

        domains_to_check = [
            f"traefik.{_get_base_domain('staging')}",
            _get_base_domain("prod"),
        ]

        errors: list[str] = []
        for domain in domains_to_check:
            # Query CoreDNS directly — RPi4's /etc/resolv.conf may not point to localhost
            result = node_ssh_run(rpi4, f"dig +short {domain} @127.0.0.1 2>/dev/null | head -1")
            if result.returncode != 0 or not result.stdout.strip():
                errors.append(f"{domain}: DNS resolution failed from RPi4 CoreDNS (@127.0.0.1)")

        assert not errors, "DNS resolution failures:\n" + "\n".join(errors)

    def test_local_dns_entries(self, env: str) -> None:
        """Dev environment must have local DNS entries for *.kubelab.test."""
        if env != "dev":
            pytest.skip("Local DNS check only relevant for dev")

        dev_domain = _get_base_domain("dev")
        domains = [
            f"traefik.{dev_domain}",
            f"api.{dev_domain}",
            f"auth.{dev_domain}",
        ]
        errors: list[str] = []

        for domain in domains:
            try:
                socket.getaddrinfo(domain, 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
            except socket.gaierror:
                errors.append(f"{domain}: not resolvable (check /etc/hosts)")

        assert not errors, "Local DNS failures:\n" + "\n".join(errors)


class TestExternalServiceBackends:
    """Services fronted by K3s Traefik but running on another host.

    The `kubelab.live/location: external` pattern (Service + EndpointSlice →
    a node's Tailscale IP) is only sound if the cluster's node can actually open
    a connection to that address. Nothing in the Kustomize render can show this:
    an EndpointSlice pointing at an unreachable address renders perfectly and
    fails at request time as a 502, indistinguishable from the backend being
    down on purpose.

    It matters most for Gitea (ADR-061), where the fronting cluster is the
    always-on prod VPS and the backend is the on-demand Beelink — the one pairing
    in this fleet that crosses the always-on/on-demand boundary, and therefore
    the one whose reachability is least obvious.
    """

    def test_vps_reaches_gitea_on_the_beelink(
        self,
        vps_node: NodeInfo,
        inventory: list[NodeInfo],
    ) -> None:
        target_ip = _COMMON["networking"]["nodes"]["beelink"]["tailscale_ip"]
        port = _COMMON["apps"]["services"]["core"]["gitea"]["default_port"]

        # Matched by address, not by name: the inventory prefixes hostnames
        # (`kubelab-beelink`) while the SSOT key does not, and a name-based lookup
        # silently skips — which is how a check like this quietly stops running.
        if not any(n.host == target_ip for n in inventory):
            pytest.fail(f"no inventory node at {target_ip} — networking.nodes.beelink and the inventory disagree")

        # Probed from the VPS, not from here: the workstation reaching the
        # Beelink proves nothing about the host that actually has to proxy to it.
        probe = f"timeout 5 bash -c 'exec 3<>/dev/tcp/{target_ip}/{port}' && echo REACHABLE || echo UNREACHABLE"
        result = node_ssh_run(vps_node, probe, timeout=20)

        if result.returncode != 0 and "REACHABLE" not in result.stdout:
            pytest.skip(f"could not probe from VPS (ssh rc={result.returncode}): {result.stderr.strip()}")

        if "UNREACHABLE" in result.stdout:
            # The homelab being off is the expected steady state, not a failure —
            # that is what `location: on-demand` means. Distinguish the two by
            # checking from here, where the tailnet is known good.
            try:
                with socket.create_connection((target_ip, int(port)), timeout=5):
                    pytest.fail(
                        f"VPS cannot reach Gitea at {target_ip}:{port}, but this workstation can. "
                        "The backend is up, so the prod IngressRoute would serve a permanent 502 — "
                        "check Headscale ACLs and the Beelink's port bind address."
                    )
            except OSError:
                pytest.skip(f"Beelink is powered off ({target_ip}:{port} unreachable from here too)")

        assert "REACHABLE" in result.stdout, (
            f"unexpected probe output from VPS for {target_ip}:{port}: {result.stdout.strip()!r}"
        )
