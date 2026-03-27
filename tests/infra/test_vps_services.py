"""VPS production service endpoint tests.

Verifies all Ansible-managed services on the VPS are reachable
and responding correctly via their kubelab.live domains.
Requires Tailscale VPN connection.
"""

from __future__ import annotations

import subprocess

import pytest

from .fixtures import VPS_NODE, _COMMON

pytestmark = [pytest.mark.infra]

VPS_IP = _COMMON["networking"]["vps"]["public_ip"]


def _curl(url: str, *, follow: bool = False, auth: str = "") -> tuple[int, str]:
    """Curl a URL and return (status_code, body). Uses -k to skip cert verify."""
    cmd = ["curl", "-sk", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "10"]
    if follow:
        cmd.append("-L")
    if auth:
        cmd.extend(["-u", auth])
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    code = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0
    return code, result.stderr


def _curl_body(url: str) -> tuple[int, str]:
    """Curl a URL and return (status_code, body)."""
    cmd = ["curl", "-sk", "--max-time", "10", url]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    # Get status code separately
    cmd_code = ["curl", "-sk", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "10", url]
    code_result = subprocess.run(cmd_code, capture_output=True, text=True, check=False)
    code = int(code_result.stdout.strip()) if code_result.stdout.strip().isdigit() else 0
    return code, result.stdout


class TestHeadscale:
    """Headscale VPN control plane."""

    def test_health(self, require_vpn: None) -> None:
        code, body = _curl_body("https://vpn.kubelab.live/health")
        assert code == 200
        assert '"pass"' in body


class TestTraefikDashboard:
    """Traefik dashboard behind Authelia."""

    def test_requires_auth(self, require_vpn: None) -> None:
        code, _ = _curl("https://traefik.kubelab.live")
        assert code in (302, 401), f"Expected Authelia redirect (302) or auth challenge (401), got {code}"


class TestGrafana:
    """Grafana observability dashboard."""

    def test_reachable(self, require_vpn: None) -> None:
        code, _ = _curl("https://grafana.kubelab.live")
        assert code in (200, 302)


class TestN8N:
    """N8N workflow automation (behind Authelia)."""

    def test_reachable(self, require_vpn: None) -> None:
        code, _ = _curl("https://n8n.kubelab.live")
        assert code in (200, 302), f"Expected n8n reachable (200) or Authelia redirect (302), got {code}"


class TestAPI:
    """KubeLab API."""

    def test_health(self, require_vpn: None) -> None:
        code, body = _curl_body("https://api.kubelab.live/health")
        assert code == 200
        assert '"healthy"' in body


class TestWeb:
    """mlorente.dev personal site."""

    def test_reachable(self, require_vpn: None) -> None:
        code, _ = _curl("https://mlorente.dev")
        assert code == 200


class TestUptimeKuma:
    """Uptime Kuma status page (RPi3 proxied via VPS)."""

    def test_reachable(self, require_vpn: None) -> None:
        code, _ = _curl("https://status.kubelab.live")
        assert code in (200, 302)


class TestTLSCertificate:
    """Wildcard TLS certificate for *.kubelab.live."""

    def test_wildcard_cert_valid(self, require_vpn: None) -> None:
        result = subprocess.run(
            [
                "openssl", "s_client",
                "-servername", "grafana.kubelab.live",
                "-connect", f"{VPS_IP}:443",
            ],
            input="",
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        assert "kubelab.live" in result.stdout, "Expected *.kubelab.live cert"
        assert "TRAEFIK DEFAULT CERT" not in result.stdout, "Still using Traefik default cert"
