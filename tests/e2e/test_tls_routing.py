"""E2E: TLS certificate validity and routing checks — parametrized over all domains."""

from __future__ import annotations

import socket
import ssl
import warnings

import httpx
import pytest

from toolkit.features.health_check import ServiceHealthConfig

from .expectations import EXPECTATIONS

pytestmark = pytest.mark.e2e


def _testable_domains(
    services: list[ServiceHealthConfig], env: str,
) -> list[str]:
    """Extract unique domains for services expected to work in this environment.

    Filters out:
    - Services not in EXPECTATIONS (internal, like errors)
    - Services with skip_in_envs matching the current env (no IngressRoute)
    """
    seen: set[str] = set()
    domains: list[str] = []
    for svc in services:
        exp = EXPECTATIONS.get(svc.name)
        if not exp or env in exp.skip_in_envs:
            continue
        if svc.domain not in seen:
            seen.add(svc.domain)
            domains.append(svc.domain)
    return domains


class TestTLSCertificates:
    """Verify TLS certificates are valid for all service domains."""

    def test_all_certificates_valid(
        self, services: list[ServiceHealthConfig], env: str,
    ) -> None:
        if env == "dev":
            pytest.skip("Dev uses mkcert self-signed certs")

        domains = _testable_domains(services, env)
        if not domains:
            pytest.skip("No testable domains in this environment")

        errors: list[str] = []
        unreachable: list[str] = []
        for domain in domains:
            try:
                ctx = ssl.create_default_context()
                with socket.create_connection((domain, 443), timeout=5) as sock:
                    with ctx.wrap_socket(sock, server_hostname=domain) as ssock:
                        cert = ssock.getpeercert()
                        assert cert is not None
            except ConnectionRefusedError:
                unreachable.append(domain)
            except (ssl.SSLError, OSError, TimeoutError) as exc:
                errors.append(f"{domain}: {exc}")

        if unreachable:
            warnings.warn(
                f"Unreachable domains (host down?): {', '.join(unreachable)}",
                stacklevel=1,
            )
        assert not errors, "TLS errors:\n" + "\n".join(errors)


class TestHTTPSRedirect:
    """Verify HTTP -> HTTPS redirect for all domains."""

    def test_http_redirects_to_https(
        self, services: list[ServiceHealthConfig], env: str,
    ) -> None:
        if env == "dev":
            pytest.skip("Dev Traefik may not enforce HTTP redirect")

        domains = _testable_domains(services, env)
        if not domains:
            pytest.skip("No testable domains in this environment")

        errors: list[str] = []
        for domain in domains:
            try:
                r = httpx.get(f"http://{domain}/", follow_redirects=False, timeout=5.0)
                if r.status_code not in (301, 302, 307, 308):
                    errors.append(f"{domain}: got {r.status_code}, expected redirect")
                elif "location" in r.headers:
                    location = r.headers["location"]
                    if not location.startswith("https://"):
                        errors.append(f"{domain}: redirects to {location}, not HTTPS")
            except httpx.ConnectError:
                pass  # Port 80 not open is acceptable

        assert not errors, "HTTP->HTTPS redirect failures:\n" + "\n".join(errors)


class TestUnknownHostRouting:
    """Verify Traefik returns 404 for unknown hosts."""

    def test_unknown_host_returns_404(
        self,
        http_client: httpx.Client,
        services_by_name: dict[str, ServiceHealthConfig],
        env: str,
    ) -> None:
        """Send fake Host header to test default backend routing."""
        # Use a service with a valid IngressRoute/cert in the current env.
        # On staging, traefik dashboard has no IngressRoute (self-signed cert).
        target = None
        for name in ("authelia", "grafana", "loki"):
            svc = services_by_name.get(name)
            if not svc:
                continue
            exp = EXPECTATIONS.get(name)
            if exp and env in exp.skip_in_envs:
                continue
            target = svc
            break
        if not target:
            target = services_by_name.get("traefik")
        if not target:
            pytest.skip("No service available to test unknown host routing")

        r = http_client.get(
            f"https://{target.domain}/",
            headers={"Host": "nonexistent-e2e-probe.invalid"},
        )
        assert r.status_code in (404, 421, 502), (
            f"Expected 404/421/502 for unknown host, got {r.status_code}"
        )

    def test_unknown_host_shows_custom_error_page(
        self,
        http_client_follow: httpx.Client,
        env: str,
    ) -> None:
        """Unknown subdomains on staging should return errors custom 404 page."""
        if env == "dev":
            pytest.skip("No catch-all IngressRoute in dev")
        if env != "staging":
            pytest.skip("Test targets staging wildcard cert")

        try:
            r = http_client_follow.get(
                "https://nonexistent-e2e-probe.staging.kubelab.live/",
                timeout=10.0,
            )
        except httpx.ConnectError:
            pytest.skip("Cannot connect to wildcard subdomain — cert may not be ready")

        assert r.status_code == 404, (
            f"Expected 404 for unknown host, got {r.status_code}"
        )
        assert "página no encontrada" in r.text.lower(), (
            "Unknown host should show errors custom 404 page"
        )
