"""Infrastructure: Network connectivity — VPS, Tailscale mesh, DNS resolution."""

from __future__ import annotations

import socket
import subprocess

import pytest
import yaml

from .fixtures import _COMMON, _REPO_ROOT, NodeInfo, ssh_run

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
            result = ssh_run(rpi4.host, f"dig +short {domain} @127.0.0.1 2>/dev/null | head -1")
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
