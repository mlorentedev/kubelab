"""Tests for k8s_secrets._build_users_database — Authelia users_database YAML generator.

Verifies the OUTPUT of the generator is coherent with SSOT inputs:
  - SSOT-014b: admin username derives from apps.auth.admin_username
  - SSOT-014c: admin email derives from apps.contact.email (loader-injected)

Companion to `test_credentials_reconcile.py::TestSSOTAdminUsername` /
`TestSSOTContactEmail`, which cover the INPUT side (config has the SSOT).
"""

from __future__ import annotations

import pytest
import yaml

from toolkit.features.configuration import ConfigurationManager
from toolkit.features.k8s_secrets import _build_users_database


@pytest.mark.parametrize("env", ["staging", "prod"])
class TestUsersDatabaseGenerator:
    """Generated Authelia users_database.yml must be coherent with SSOT (both envs)."""

    @staticmethod
    def _build(env: str) -> tuple[dict, dict]:
        cm = ConfigurationManager(env)
        users_db_yaml = _build_users_database(cm)
        assert users_db_yaml, f"_build_users_database returned empty for {env}"
        return yaml.safe_load(users_db_yaml), cm.get_merged_config()

    def test_output_is_valid_yaml_with_users_root(self, env: str) -> None:
        parsed, _ = self._build(env)
        assert isinstance(parsed, dict) and "users" in parsed, (
            f"users_database for {env} must be a YAML mapping with 'users' root key"
        )

    def test_admin_username_from_ssot_is_present(self, env: str) -> None:
        parsed, merged = self._build(env)
        admin_username = merged["apps"]["auth"]["admin_username"]
        assert admin_username in parsed["users"], (
            f"users_database for {env} must contain admin user '{admin_username}' "
            f"(derived from apps.auth.admin_username SSOT)"
        )

    def test_admin_email_matches_contact_ssot(self, env: str) -> None:
        parsed, merged = self._build(env)
        admin_username = merged["apps"]["auth"]["admin_username"]
        contact_email = merged["apps"]["contact"]["email"]
        admin_entry = parsed["users"][admin_username]
        assert admin_entry["email"] == contact_email, (
            f"Admin '{admin_username}' email ({admin_entry['email']!r}) in {env} "
            f"must match apps.contact.email SSOT ({contact_email!r}) via loader injection (SSOT-014c)"
        )

    def test_admin_has_admins_group(self, env: str) -> None:
        parsed, merged = self._build(env)
        admin_username = merged["apps"]["auth"]["admin_username"]
        admin_entry = parsed["users"][admin_username]
        assert "admins" in admin_entry.get("groups", []), (
            f"Admin '{admin_username}' in {env} must have 'admins' group"
        )

    def test_admin_has_password_hash(self, env: str) -> None:
        parsed, merged = self._build(env)
        admin_username = merged["apps"]["auth"]["admin_username"]
        admin_entry = parsed["users"][admin_username]
        password = admin_entry.get("password", "")
        assert password.startswith("$argon2"), (
            f"Admin '{admin_username}' password in {env} must be an argon2 hash "
            f"(got prefix: {password[:20]!r}) — check users_<{admin_username}>_password_hash in SOPS"
        )
