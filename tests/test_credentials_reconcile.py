"""Tests for credential-to-service mapping and reconciliation."""

import pytest

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
            "apps.services.security.authelia.users_operator_password_hash",
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


@pytest.mark.parametrize("env", ["staging", "prod"])
class TestSSOTAdminUsername:
    """Verify the admin username is read from the identity SSOT (both envs).

    Rewritten for AUTH-004 C1 (ADR-062 D3). These assertions previously encoded
    SSOT-014b's design — `apps.auth.admin_username` plus an `is_admin: true`
    flag — and they passed right up until that design was replaced. Worth
    noting rather than quietly editing: a test that asserts *the current
    mechanism* rather than *the required property* has to be rewritten whenever
    the mechanism changes, and cannot warn you that the mechanism was wrong.
    The property here is unchanged: one identity, one declaration.
    """

    def test_common_yaml_declares_the_identity_map(self, env: str) -> None:
        from toolkit.features.configuration import ConfigurationManager

        cm = ConfigurationManager(env)
        config = cm.get_merged_config()
        identities = config.get("apps", {}).get("auth", {}).get("identities", {})
        assert identities.get("operator") == "operator"
        assert identities.get("superadmin"), "apps.auth.identities.superadmin must be declared"
        assert "admin_username" not in config.get("apps", {}).get("auth", {}), (
            "apps.auth.admin_username was removed by AUTH-004 C1 — two declarations of one "
            "identity is the defect, even when one of them is unused"
        )

    def test_authelia_admin_user_derives_from_ssot(self, env: str) -> None:
        """The admin entry names a declared identity and carries no literal username.

        `identity:` holds a KEY of `apps.auth.identities`, so renaming the person
        is one edit in that map. The entry must NOT also carry `username:` — that
        would be the second declaration this design exists to remove.
        """
        from toolkit.features.configuration import ConfigurationManager, resolve_user_identity

        cm = ConfigurationManager(env)
        config = cm.get_merged_config()
        users = config["apps"]["services"]["security"]["authelia"]["users"]
        declared = [u for u in users if u.get("identity")]
        assert len(declared) == 1, "Exactly one user must name a declared identity"
        assert "username" not in declared[0], (
            "A user that names an identity must NOT also carry `username` — it resolves "
            "through apps.auth.identities (SSOT)"
        )
        assert resolve_user_identity(declared[0], config), (
            f"`identity: {declared[0]['identity']!r}` resolves to nothing — it must name a key "
            "of apps.auth.identities, and an unresolvable entry is silently skipped by both generators"
        )


@pytest.mark.parametrize("env", ["staging", "prod"])
class TestSSOTContactEmail:
    """SSOT-014c: operator contact email is derived from apps.contact.email (both envs)."""

    def test_contact_email_ssot_is_set(self, env: str) -> None:
        from toolkit.features.configuration import ConfigurationManager

        cm = ConfigurationManager(env)
        config = cm.get_merged_config()
        contact = config.get("apps", {}).get("contact", {}).get("email")
        assert contact, "apps.contact.email SSOT must be non-empty"

    def test_loader_injects_acme_email_from_contact(self, env: str) -> None:
        """edge.traefik.acme_email is removed from common.yaml literal;
        loader fills it from apps.contact.email."""
        from toolkit.features.configuration import ConfigurationManager

        cm = ConfigurationManager(env)
        config = cm.get_merged_config()
        contact = config["apps"]["contact"]["email"]
        acme_email = config["edge"]["traefik"]["acme_email"]
        assert acme_email == contact, (
            f"edge.traefik.acme_email ({acme_email!r}) must derive from "
            f"apps.contact.email ({contact!r}) via loader injection (SSOT-014c)"
        )

    def test_loader_injects_uptime_kuma_admin_email_from_contact(self, env: str) -> None:
        from toolkit.features.configuration import ConfigurationManager

        cm = ConfigurationManager(env)
        config = cm.get_merged_config()
        contact = config["apps"]["contact"]["email"]
        admin_email = (
            config["apps"]["services"]["observability"]["uptime_kuma"]["admin_email"]
        )
        assert admin_email == contact, (
            f"uptime_kuma.admin_email ({admin_email!r}) must derive from "
            f"apps.contact.email ({contact!r}) via loader injection (SSOT-014c)"
        )

    def test_loader_injects_gitea_admin_email_from_contact(self, env: str) -> None:
        """SSOT-019: apps.services.core.gitea.admin_email derives from apps.contact.email.

        Surfaced 2026-05-26 during Phase B prod smoke (apply-secrets warning) and confirmed
        2026-05-26 in staging (gitea pod CreateContainerConfigError — missing ADMIN_EMAIL key
        in gitea-secrets Secret).
        """
        from toolkit.features.configuration import ConfigurationManager

        cm = ConfigurationManager(env)
        config = cm.get_merged_config()
        contact = config["apps"]["contact"]["email"]
        admin_email = config["apps"]["services"]["core"]["gitea"]["admin_email"]
        assert admin_email == contact, (
            f"gitea.admin_email ({admin_email!r}) must derive from "
            f"apps.contact.email ({contact!r}) via loader injection (SSOT-019)"
        )

    def test_loader_injects_authelia_admin_email_from_contact(self, env: str) -> None:
        from toolkit.features.configuration import ConfigurationManager

        cm = ConfigurationManager(env)
        config = cm.get_merged_config()
        contact = config["apps"]["contact"]["email"]
        admin_entries = [
            u
            for u in config["apps"]["services"]["security"]["authelia"]["users"]
            if u.get("identity")
        ]
        assert len(admin_entries) == 1
        assert admin_entries[0]["email"] == contact, (
            f"Authelia admin user email ({admin_entries[0]['email']!r}) must "
            f"derive from apps.contact.email ({contact!r}) via loader injection (SSOT-014c)"
        )
