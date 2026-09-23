"""SSOT-017: `apps.services.security.authelia.oidc_clients` is the only declaration of an OIDC client.

The guard at the bottom compares what Authelia is actually configured with — the
committed K8s config files, read as Authelia reads them — against what the SSOT
resolves to. It needs no SOPS: `client_secret` is the one field it does not
compare, so it runs in CI, where the OIDC hash drift check is skipped.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.features import oidc_clients

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _values(clients: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "apps": {
            "services": {
                "security": {"authelia": {"oidc_clients": clients}},
                "observability": {"grafana": {"domain": "grafana.example.test"}},
            }
        },
    }


def _grafana(**overrides: Any) -> dict[str, Any]:
    client = {
        "client_id": "grafana",
        "client_name": "Grafana",
        "envs": ["staging", "prod"],
        "redirect": {"domain": "apps.services.observability.grafana.domain", "path": "/login/generic_oauth"},
        "scopes": ["openid", "profile", "email", "groups"],
        "token_endpoint_auth_method": "client_secret_basic",
        "authorization_policy": "one_factor",
        "consent_mode": "implicit",
    }
    client.update(overrides)
    return client


class TestResolve:
    def test_resolves_redirect_host_from_the_declared_domain(self) -> None:
        [client] = oidc_clients.resolve_clients(_values([_grafana()]), "prod")

        assert client["redirect_uris"] == ["https://grafana.example.test/login/generic_oauth"]
        assert client["public"] is False
        assert "envs" not in client and "redirect" not in client

    def test_a_client_is_absent_from_an_env_it_does_not_declare(self) -> None:
        assert oidc_clients.resolve_clients(_values([_grafana(envs=["prod"])]), "staging") == []

    @pytest.mark.parametrize("field", ["token_endpoint_auth_method", "authorization_policy"])
    def test_a_missing_required_field_fails_naming_the_client(self, field: str) -> None:
        client = _grafana()
        del client[field]

        with pytest.raises(oidc_clients.OidcClientError, match=rf"grafana.*{field}"):
            oidc_clients.resolve_clients(_values([client]), "prod")

    def test_a_domain_reference_that_resolves_to_nothing_fails(self) -> None:
        client = _grafana(redirect={"domain": "apps.services.observability.nope.domain", "path": "/cb"})

        with pytest.raises(oidc_clients.OidcClientError, match="grafana"):
            oidc_clients.resolve_clients(_values([client]), "prod")

    def test_an_unknown_env_fails(self) -> None:
        with pytest.raises(oidc_clients.OidcClientError, match="grafana"):
            oidc_clients.resolve_clients(_values([_grafana(envs=["prdo"])]), "prod")


class TestDigestKey:
    @pytest.mark.parametrize(
        ("client_id", "key"),
        [
            ("grafana", "apps.services.security.authelia.oidc_client_secret_grafana_hash"),
            ("vikunja-oidc", "apps.services.security.authelia.oidc_client_secret_vikunja_hash"),
            ("some-thing", "apps.services.security.authelia.oidc_client_secret_some_thing_hash"),
        ],
    )
    def test_convention(self, client_id: str, key: str) -> None:
        assert oidc_clients.digest_key(client_id) == key


def _committed_clients(env: str) -> list[dict[str, Any]]:
    """Clients as Authelia sees them: every file in the env's authelia-config, merged."""
    clients: list[dict[str, Any]] = []
    for path in oidc_clients.config_files(env):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        found = ((doc.get("identity_providers") or {}).get("oidc") or {}).get("clients")
        if found is not None:
            clients.extend(found)
    return clients


def _without_secret(clients: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    stripped = {}
    for client in copy.deepcopy(clients):
        client.pop("client_secret", None)
        stripped[client["client_id"]] = client
    return stripped


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_oidc_clients_match_ssot(env: str) -> None:
    """AC1: the committed config registers exactly the SSOT's clients for `env`, field for field."""
    expected = _without_secret(oidc_clients.resolve_clients(oidc_clients.load_values(env), env))
    actual = _without_secret(_committed_clients(env))

    assert sorted(actual) == sorted(expected), f"{env}: registered client set differs from the SSOT"
    for client_id, fields in expected.items():
        assert actual[client_id] == fields, f"{env}: {client_id} differs from the SSOT"
