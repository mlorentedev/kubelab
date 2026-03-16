"""Tests for credential-to-service mapping and reconciliation."""

from toolkit.features.credentials import CREDENTIAL_SERVICE_MAP


class TestCredentialServiceMap:
    """Verify the mapping from secret key prefixes to affected services."""

    def test_basic_auth_maps_to_traefik(self) -> None:
        assert "traefik" in CREDENTIAL_SERVICE_MAP["basic_auth"]

    def test_authelia_maps_to_authelia(self) -> None:
        assert "authelia" in CREDENTIAL_SERVICE_MAP["apps.services.security.authelia"]

    def test_grafana_maps_to_grafana(self) -> None:
        assert "grafana" in CREDENTIAL_SERVICE_MAP["apps.services.observability.grafana"]

    def test_minio_maps_to_minio(self) -> None:
        assert "minio" in CREDENTIAL_SERVICE_MAP["apps.services.data.minio"]

    def test_crowdsec_maps_to_crowdsec(self) -> None:
        assert "crowdsec" in CREDENTIAL_SERVICE_MAP["apps.services.security.crowdsec"]


class TestAffectedServiceResolution:
    """Verify that secret keys correctly resolve to affected services."""

    @staticmethod
    def _resolve_affected(keys: list[str]) -> set[str]:
        """Replicate the resolution logic from _reconcile_services."""
        affected: set[str] = set()
        for key in keys:
            for prefix, services in CREDENTIAL_SERVICE_MAP.items():
                if key.startswith(prefix):
                    affected.update(services)
        return affected

    def test_basic_auth_credential_key(self) -> None:
        affected = self._resolve_affected(["basic_auth.credentials"])
        assert affected == {"traefik"}

    def test_grafana_admin_password(self) -> None:
        affected = self._resolve_affected(
            ["apps.services.observability.grafana.admin_password"]
        )
        assert affected == {"grafana"}

    def test_crowdsec_bouncer_key(self) -> None:
        affected = self._resolve_affected(
            ["apps.services.security.crowdsec.bouncer_api_key"]
        )
        assert affected == {"crowdsec"}

    def test_multiple_keys_combine(self) -> None:
        affected = self._resolve_affected([
            "basic_auth.user",
            "apps.services.security.authelia.session_secret",
            "apps.services.data.minio.root_password",
        ])
        assert affected == {"traefik", "authelia", "minio"}

    def test_full_generate_output(self) -> None:
        """All keys from setup_authelia_secrets should map to services."""
        all_keys = [
            "basic_auth.user",
            "basic_auth.password",
            "basic_auth.credentials",
            "apps.services.security.authelia.users_admin_password_hash",
            "apps.services.security.authelia.oidc_hmac_secret",
            "apps.services.security.authelia.session_secret",
            "apps.services.security.authelia.storage_encryption_key",
            "apps.services.security.authelia.jwt_secret_reset_password",
            "apps.services.security.authelia.oidc_client_secret",
            "apps.services.security.authelia.oidc_client_secret_hash",
            "apps.services.observability.grafana.admin_user",
            "apps.services.observability.grafana.admin_password",
            "apps.services.security.authelia.oidc_client_secret_grafana",
            "apps.services.security.authelia.oidc_client_secret_grafana_hash",
            "apps.services.data.minio.root_user",
            "apps.services.data.minio.root_password",
            "apps.services.data.minio.oidc_client_secret",
            "apps.services.security.authelia.oidc_client_secret_minio_hash",
            "apps.services.security.crowdsec.bouncer_api_key",
        ]
        affected = self._resolve_affected(all_keys)
        assert "traefik" in affected
        assert "authelia" in affected
        assert "grafana" in affected
        assert "minio" in affected
        assert "crowdsec" in affected

    def test_unknown_key_no_services(self) -> None:
        affected = self._resolve_affected(["some.unknown.key"])
        assert affected == set()
