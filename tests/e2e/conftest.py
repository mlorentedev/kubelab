"""E2E test fixtures — httpx client, service discovery, connectivity checks."""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from toolkit.features.configuration import ConfigurationManager
from toolkit.features.health_check import HealthChecker, ServiceHealthConfig

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _build_connectivity_domains() -> dict[str, str]:
    """Build probe domains from config values (single source of truth)."""
    common_path = _REPO_ROOT / "infra" / "config" / "values" / "common.yaml"
    with open(common_path) as f:
        common = yaml.safe_load(f)
    default_domain = common["global"]["base_domain"]

    domains: dict[str, str] = {}
    for env in ("dev", "staging", "prod"):
        env_path = _REPO_ROOT / "infra" / "config" / "values" / f"{env}.yaml"
        if env_path.exists():
            with open(env_path) as f:
                env_config = yaml.safe_load(f) or {}
            base = env_config.get("global", {}).get("base_domain", default_domain)
        else:
            base = default_domain
        domains[env] = f"traefik.{base}"
    return domains


# Domain used to verify network connectivity before running tests
_CONNECTIVITY_DOMAINS = _build_connectivity_domains()


def _can_resolve(hostname: str) -> bool:
    """Check if a hostname resolves (DNS reachable)."""
    try:
        socket.getaddrinfo(hostname, 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
        return True
    except socket.gaierror:
        return False


def _can_connect(hostname: str, port: int = 443, timeout: float = 3.0) -> bool:
    """Check if a TCP connection can be established."""
    try:
        with socket.create_connection((hostname, port), timeout=timeout):
            return True
    except (OSError, TimeoutError):
        return False


# ---------------------------------------------------------------------------
# Session fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def e2e_config(env: str) -> dict[str, Any]:
    """Merged configuration for the target environment."""
    cm = ConfigurationManager(env)
    return cm.get_merged_config()


@pytest.fixture(scope="session")
def services(e2e_config: dict[str, Any]) -> list[ServiceHealthConfig]:
    """All services with domain + health_path from merged config."""
    checker = HealthChecker.__new__(HealthChecker)
    return checker._extract_service_configs(e2e_config)


@pytest.fixture(scope="session")
def services_by_name(services: list[ServiceHealthConfig]) -> dict[str, ServiceHealthConfig]:
    """Services indexed by name for easy lookup."""
    return {svc.name: svc for svc in services}


@pytest.fixture(scope="session")
def services_by_category(services: list[ServiceHealthConfig]) -> dict[str, list[ServiceHealthConfig]]:
    """Services grouped by category."""
    grouped: dict[str, list[ServiceHealthConfig]] = {}
    for svc in services:
        grouped.setdefault(svc.category, []).append(svc)
    return grouped


@pytest.fixture(scope="session")
def base_url(env: str, e2e_config: dict[str, Any]) -> str:
    """Base URL scheme (always https for all envs)."""
    return "https"


@pytest.fixture(scope="session")
def http_client(env: str) -> httpx.Client:
    """Configured httpx client for e2e tests.

    - dev: skip TLS verification (mkcert self-signed)
    - staging/prod: verify TLS (Let's Encrypt)
    - follow_redirects=False so we can assert on redirect behavior
    """
    verify = env != "dev"
    client = httpx.Client(
        timeout=httpx.Timeout(10.0, connect=5.0),
        verify=verify,
        follow_redirects=False,
    )
    yield client  # type: ignore[misc]
    client.close()


@pytest.fixture(scope="session")
def http_client_follow(env: str) -> httpx.Client:
    """httpx client that follows redirects (for full flow tests)."""
    verify = env != "dev"
    client = httpx.Client(
        timeout=httpx.Timeout(10.0, connect=5.0),
        verify=verify,
        follow_redirects=True,
    )
    yield client  # type: ignore[misc]
    client.close()


# ---------------------------------------------------------------------------
# Auth fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def authelia_test_credentials(e2e_config: dict[str, Any]) -> tuple[str, str] | None:
    """Return (username, password) for Authelia testuser, or None if unavailable.

    Reads from E2E_AUTH_USER / E2E_AUTH_PASSWORD env vars first,
    falls back to SOPS-merged config at apps.testing.authelia_test_password.
    """
    user = os.environ.get("E2E_AUTH_USER", "testuser")
    password = os.environ.get("E2E_AUTH_PASSWORD")

    if not password:
        testing = e2e_config.get("apps", {}).get("testing", {})
        password = testing.get("authelia_test_password")

    if not password:
        return None
    return user, password


@pytest.fixture(scope="session")
def authenticated_client(
    env: str,
    services_by_name: dict[str, ServiceHealthConfig],
    authelia_test_credentials: tuple[str, str] | None,
) -> httpx.Client | None:
    """httpx client with a valid Authelia session cookie.

    Performs first-factor auth against Authelia's /api/firstfactor endpoint.
    Returns None if credentials are unavailable or login fails.
    """
    if authelia_test_credentials is None:
        yield None  # type: ignore[misc]
        return

    authelia = services_by_name.get("authelia")
    if not authelia:
        yield None  # type: ignore[misc]
        return

    username, password = authelia_test_credentials
    verify = env != "dev"

    client = httpx.Client(
        timeout=httpx.Timeout(10.0, connect=5.0),
        verify=verify,
        follow_redirects=True,
    )

    login_ok = False
    try:
        r = client.post(
            f"https://{authelia.domain}/api/firstfactor",
            json={
                "username": username,
                "password": password,
                "keepMeLoggedIn": True,
                "targetURL": f"https://{authelia.domain}/",
                "requestMethod": "GET",
            },
        )
        login_ok = r.status_code == 200
    except (httpx.HTTPError, httpx.TimeoutException):
        pass

    if not login_ok:
        client.close()
        yield None  # type: ignore[misc]
        return

    yield client  # type: ignore[misc]
    client.close()


# ---------------------------------------------------------------------------
# Auto-skip if environment unreachable
# ---------------------------------------------------------------------------


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip all e2e tests if the target environment is unreachable."""
    env = config.getoption("--env", default="dev")
    probe_host = _CONNECTIVITY_DOMAINS.get(env, "")

    if not probe_host:
        return

    if not _can_resolve(probe_host):
        skip = pytest.mark.skip(reason=f"DNS resolution failed for {probe_host} — is VPN active?")
        for item in items:
            if "e2e" in str(item.fspath):
                item.add_marker(skip)
        return

    if not _can_connect(probe_host):
        skip = pytest.mark.skip(reason=f"Cannot connect to {probe_host}:443 — is the environment up?")
        for item in items:
            if "e2e" in str(item.fspath):
                item.add_marker(skip)
