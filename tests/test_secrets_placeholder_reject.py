"""Tests for TOOL-019: secrets audit + K8s apply must reject placeholder values.

The K8s overlay `secrets.yaml` manifests ship `REPLACE_WITH_SOPS_VALUE` by design,
and `audit()` previously marked any non-empty value `present`. So a half-configured
vault (a SOPS key still holding a placeholder) reported clean, and a placeholder
could reach a cluster. These tests pin (audit finding C6):

1. `is_placeholder()` recognises the known sentinels.
2. `audit()` classifies a placeholder-valued key as MISSING, not present.
3. `apply_secrets()` refuses (fails, no kubectl) when a mapped source is a placeholder.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from toolkit.config.constants import VAULT_PLACEHOLDERS, is_placeholder
from toolkit.config.settings import PROJECT_ROOT
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.k8s_secrets import apply_secrets
from toolkit.features.secrets_manager import SecretsManager


class TestIsPlaceholder:
    @pytest.mark.parametrize("value", sorted(VAULT_PLACEHOLDERS))
    def test_known_sentinels_are_placeholders(self, value: str) -> None:
        assert is_placeholder(value) is True

    def test_surrounding_whitespace_is_stripped(self) -> None:
        assert is_placeholder("  REPLACE_WITH_SOPS_VALUE  ") is True

    def test_real_value_is_not_a_placeholder(self) -> None:
        assert is_placeholder("$argon2id$v=19$m=65536,t=3,p=4$realhash") is False

    def test_empty_and_none_are_not_placeholders(self) -> None:
        assert is_placeholder("") is False
        assert is_placeholder(None) is False


class TestAuditRejectsPlaceholders:
    def test_placeholder_value_is_missing_not_present(self) -> None:
        # basic_auth.user is a catalog secret in every env; feed it a placeholder and
        # basic_auth.password a real value via a mocked decrypt.
        fake = {"basic_auth": {"user": "REPLACE_WITH_SOPS_VALUE", "password": "a-real-password"}}
        with patch.object(ConfigurationManager, "_decrypt_sops", return_value=fake):
            result = SecretsManager(PROJECT_ROOT).audit("staging")

        assert "basic_auth.user" in result.missing, "a placeholder must be reported missing"
        assert "basic_auth.user" not in result.present
        assert "basic_auth.password" in result.present, "a real value must stay present"


class TestApplySecretsRefusesPlaceholders:
    def test_refuses_and_does_not_call_kubectl(self, mocker: "pytest.MonkeyPatch") -> None:
        run = mocker.patch("toolkit.features.k8s_secrets.subprocess.run")
        fake_cm = mocker.Mock()
        # One mapped source (api-secrets BEEHIIV_API_KEY) still holds a placeholder.
        fake_cm.get_env_vars.return_value = {"APPS_PLATFORM_API_BEEHIIV_API_KEY": "REPLACE_WITH_SOPS_VALUE"}
        mocker.patch("toolkit.features.k8s_secrets.ConfigurationManager", return_value=fake_cm)

        ok = apply_secrets("staging", Path("."), dry_run=False)

        assert ok is False, "apply must refuse a vault holding a placeholder"
        run.assert_not_called()
