"""Tests for credential-to-service mapping and reconciliation."""

from toolkit.features.credentials import (
    CREDENTIAL_SERVICE_MAP,
    IMMUTABLE_SECRETS,
    CredentialsManager,
)


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
            "apps.services.security.authelia.users_manu_password_hash",
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


class TestImmutableSecrets:
    """Verify IMMUTABLE_SECRETS protection logic."""

    def test_immutable_secrets_defined(self) -> None:
        assert len(IMMUTABLE_SECRETS) == 4

    def test_storage_encryption_key_is_immutable(self) -> None:
        assert "apps.services.security.authelia.storage_encryption_key" in IMMUTABLE_SECRETS

    def test_session_secret_is_immutable(self) -> None:
        assert "apps.services.security.authelia.session_secret" in IMMUTABLE_SECRETS

    def test_jwt_secret_is_immutable(self) -> None:
        assert "apps.services.security.authelia.jwt_secret_reset_password" in IMMUTABLE_SECRETS

    def test_oidc_hmac_is_immutable(self) -> None:
        assert "apps.services.security.authelia.oidc_hmac_secret" in IMMUTABLE_SECRETS

    def test_preserve_existing_values(self) -> None:
        """Existing immutable secrets must not be overwritten."""
        cm = CredentialsManager()
        generated = {
            "apps.services.security.authelia.storage_encryption_key": "NEW_VALUE",
            "apps.services.security.authelia.session_secret": "NEW_VALUE",
            "apps.services.security.authelia.oidc_hmac_secret": "NEW_VALUE",
            "apps.services.security.authelia.jwt_secret_reset_password": "NEW_VALUE",
            "basic_auth.user": "manu",
        }
        existing = {
            "apps.services.security.authelia.storage_encryption_key": "EXISTING_KEY",
            "apps.services.security.authelia.session_secret": "EXISTING_SESSION",
            "apps.services.security.authelia.oidc_hmac_secret": "EXISTING_HMAC",
            "apps.services.security.authelia.jwt_secret_reset_password": "EXISTING_JWT",
        }
        result = cm._preserve_immutable(generated, existing)

        # Immutable secrets preserved
        assert result["apps.services.security.authelia.storage_encryption_key"] == "EXISTING_KEY"
        assert result["apps.services.security.authelia.session_secret"] == "EXISTING_SESSION"
        assert result["apps.services.security.authelia.oidc_hmac_secret"] == "EXISTING_HMAC"
        assert result["apps.services.security.authelia.jwt_secret_reset_password"] == "EXISTING_JWT"
        # Non-immutable secrets use new values
        assert result["basic_auth.user"] == "manu"

    def test_first_run_uses_generated_values(self) -> None:
        """When no existing secrets, generated values are used."""
        cm = CredentialsManager()
        generated = {
            "apps.services.security.authelia.storage_encryption_key": "FRESH_KEY",
            "apps.services.security.authelia.session_secret": "FRESH_SESSION",
        }
        result = cm._preserve_immutable(generated, existing={})

        assert result["apps.services.security.authelia.storage_encryption_key"] == "FRESH_KEY"
        assert result["apps.services.security.authelia.session_secret"] == "FRESH_SESSION"


class TestFlattenDict:
    """Verify nested dict flattening for SOPS reading."""

    def test_flat_dict(self) -> None:
        result = CredentialsManager._flatten_dict({"a": 1, "b": 2})
        assert result == {"a": 1, "b": 2}

    def test_nested_dict(self) -> None:
        result = CredentialsManager._flatten_dict({"a": {"b": {"c": "val"}}})
        assert result == {"a.b.c": "val"}

    def test_mixed_depth(self) -> None:
        result = CredentialsManager._flatten_dict({
            "basic_auth": {"user": "manu"},
            "apps": {"services": {"security": {"authelia": {"session_secret": "abc"}}}},
        })
        assert result["basic_auth.user"] == "manu"
        assert result["apps.services.security.authelia.session_secret"] == "abc"


class TestSSOTAdminUsername:
    """Verify admin username is read from common.yaml SSOT."""

    def test_common_yaml_has_admin_username(self) -> None:
        from toolkit.features.configuration import ConfigurationManager

        cm = ConfigurationManager("staging")
        config = cm.get_merged_config()
        username = config.get("apps", {}).get("auth", {}).get("admin_username")
        assert username == "manu"

    def test_authelia_users_matches_ssot(self) -> None:
        from toolkit.features.configuration import ConfigurationManager

        cm = ConfigurationManager("staging")
        config = cm.get_merged_config()
        ssot_username = config["apps"]["auth"]["admin_username"]
        authelia_username = config["apps"]["services"]["security"]["authelia"]["users"][0]["username"]
        assert ssot_username == authelia_username
