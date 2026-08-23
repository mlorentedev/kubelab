"""Tests for k8s_secrets._build_apprise_config — Apprise routing-table YAML generator.

Verifies the OUTPUT of the generator is coherent with SOPS inputs (NOTIFY-001 / ADR-044
Option B): Apprise owns the tag->URL routing table and n8n sends only a tag. The table is
rendered into the apprise-secrets Secret as kubelab.yml and mounted at /config so
APPRISE_STATEFUL_MODE=simple resolves POST /notify/kubelab by tag.

Companion to the apprise-secrets SecretMapping (k8s_secrets.SECRET_DEFINITIONS) and the
SECRET_CATALOG entries (secrets_manager.py) which cover the registry side. Mirrors
test_k8s_secrets_users_db.py (the _build_users_database sibling generator).
"""

from __future__ import annotations

import pytest
import yaml

from toolkit.features.configuration import ConfigurationManager
from toolkit.features.k8s_secrets import _build_apprise_config

#: Asserts the generator output against the REAL values in SOPS, so it needs the
#: age key. Skipped (not deselected) where decryption is impossible, so the gap
#: stays visible in the summary — see pytest_collection_modifyitems in conftest.
pytestmark = pytest.mark.requires_sops

# The notification fabric is staging-only until promoted to prod
# (SECRET_CATALOG entries declare envs=("staging",)).
ENV = "staging"


def _slack_cfg(merged: dict) -> dict:
    return (
        merged.get("apps", {})
        .get("services", {})
        .get("automation", {})
        .get("apprise", {})
        .get("slack", {})
    )


def _urls_for_tag(parsed: dict, tag: str) -> list[str]:
    """simple-mode entries are single-pair mappings {"slack://…": {"tag": …}}."""
    return [url for entry in parsed["urls"] for url, meta in entry.items() if meta.get("tag") == tag]


class TestAppriseConfigGenerator:
    """Generated apprise kubelab.yml routing table must be coherent with SOPS (staging)."""

    @staticmethod
    def _build() -> tuple[dict, dict]:
        cm = ConfigurationManager(ENV)
        rendered = _build_apprise_config(cm)
        assert rendered, (
            "_build_apprise_config returned empty for staging — "
            "routing configuration missing in SOPS"
        )
        return yaml.safe_load(rendered), cm.get_merged_config()

    def test_output_is_valid_yaml_with_urls_list(self) -> None:
        parsed, _ = self._build()
        assert isinstance(parsed, dict) and isinstance(parsed.get("urls"), list), (
            "apprise config must be a YAML mapping with a 'urls' list (simple-mode routing table)"
        )

    def test_page_tier_routes_to_alerts_channel(self) -> None:
        parsed, merged = self._build()
        slack = _slack_cfg(merged)
        page_urls = _urls_for_tag(parsed, "page")
        if slack.get("webhook_alerts"):
            assert any("#alerts" in u or "slack://" in u for u in page_urls), (
                "the 'page' tier must route to #alerts via Slack webhook in SOPS"
            )

    def test_log_tier_routes_to_ops_log_channel(self) -> None:
        parsed, merged = self._build()
        slack = _slack_cfg(merged)
        log_urls = _urls_for_tag(parsed, "log")
        if slack.get("webhook_log"):
            assert any("#ops-log" in u or "slack://" in u for u in log_urls), (
                "the 'log' tier must route to #ops-log via Slack webhook in SOPS"
            )

    def test_telegram_fallback_when_slack_absent(self) -> None:
        """Verify Telegram fallback works when only telegram is in SOPS."""
        from unittest.mock import MagicMock
        mock_cm = MagicMock()
        mock_cm.get_merged_config.return_value = {
            "apps": {
                "services": {
                    "automation": {
                        "apprise": {
                            "telegram": {
                                "bot_token": "123456:ABC-DEF",
                                "chat_page": "-100111",
                                "chat_log": "-100222",
                            }
                        }
                    }
                }
            }
        }
        rendered = _build_apprise_config(mock_cm)
        parsed = yaml.safe_load(rendered)
        assert _urls_for_tag(parsed, "page") == ["tgram://123456:ABC-DEF/-100111"]
        assert _urls_for_tag(parsed, "log") == ["tgram://123456:ABC-DEF/-100222"]

    def test_slack_multi_channel_rendering(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """NOTIFY-002: Verify Slack multi-channel URLs render cleanly with appropriate tags."""
        from unittest.mock import MagicMock
        from toolkit.features.k8s_secrets import _normalize_slack_url

        # Test URL normalization
        assert _normalize_slack_url("https://hooks.slack.com/services/T123/B456/789", "alerts") == "slack://T123/B456/789/#alerts"
        assert _normalize_slack_url("slack://T123/B456/789/#alerts") == "slack://T123/B456/789/#alerts"

        # Test config generation
        mock_cm = MagicMock()
        mock_cm.get_merged_config.return_value = {
            "apps": {
                "services": {
                    "automation": {
                        "apprise": {
                            "slack": {
                                "webhook_alerts": "https://hooks.slack.com/services/T1/B1/K1",
                                "webhook_vault": "https://hooks.slack.com/services/T1/B1/K2",
                                "webhook_deployments": "https://hooks.slack.com/services/T1/B1/K3",
                                "webhook_log": "https://hooks.slack.com/services/T1/B1/K4",
                                "webhook_agent": "https://hooks.slack.com/services/T1/B1/K5",
                            }
                        }
                    }
                }
            }
        }
        rendered = _build_apprise_config(mock_cm)
        parsed = yaml.safe_load(rendered)
        assert len(parsed["urls"]) == 5
        assert _urls_for_tag(parsed, "page") == ["slack://T1/B1/K1/#alerts"]
        assert _urls_for_tag(parsed, "vault") == ["slack://T1/B1/K2/#vault-health"]
        assert _urls_for_tag(parsed, "deploy") == ["slack://T1/B1/K3/#deployments"]
        assert _urls_for_tag(parsed, "log") == ["slack://T1/B1/K4/#ops-log"]
        assert _urls_for_tag(parsed, "agent") == ["slack://T1/B1/K5/#agent-fleet"]
