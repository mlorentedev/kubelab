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

import yaml

from toolkit.features.configuration import ConfigurationManager
from toolkit.features.k8s_secrets import _build_apprise_config

# The notification fabric is staging-only until promoted to prod
# (SECRET_CATALOG entries declare envs=("staging",)).
ENV = "staging"


def _telegram_cfg(merged: dict) -> dict:
    return (
        merged.get("apps", {})
        .get("services", {})
        .get("automation", {})
        .get("apprise", {})
        .get("telegram", {})
    )


def _urls_for_tag(parsed: dict, tag: str) -> list[str]:
    """simple-mode entries are single-pair mappings {"tgram://…": {"tag": …}}."""
    return [url for entry in parsed["urls"] for url, meta in entry.items() if meta.get("tag") == tag]


class TestAppriseConfigGenerator:
    """Generated apprise kubelab.yml routing table must be coherent with SOPS (staging)."""

    @staticmethod
    def _build() -> tuple[dict, dict]:
        cm = ConfigurationManager(ENV)
        rendered = _build_apprise_config(cm)
        assert rendered, (
            "_build_apprise_config returned empty for staging — "
            "bot_token/chat_page missing in SOPS (criterion #1 should have set them)"
        )
        return yaml.safe_load(rendered), cm.get_merged_config()

    def test_output_is_valid_yaml_with_urls_list(self) -> None:
        parsed, _ = self._build()
        assert isinstance(parsed, dict) and isinstance(parsed.get("urls"), list), (
            "apprise config must be a YAML mapping with a 'urls' list (simple-mode routing table)"
        )

    def test_page_tier_routes_to_chat_page(self) -> None:
        parsed, merged = self._build()
        tg = _telegram_cfg(merged)
        page_urls = _urls_for_tag(parsed, "page")
        assert page_urls == [f"tgram://{tg.get('bot_token', '')}/{tg.get('chat_page', '')}"], (
            "the 'page' tier must route to apps.services.automation.apprise.telegram.chat_page "
            "via the shared bot_token"
        )

    def test_log_tier_present_only_when_chat_log_set(self) -> None:
        parsed, merged = self._build()
        tg = _telegram_cfg(merged)
        chat_log = tg.get("chat_log", "")
        log_urls = _urls_for_tag(parsed, "log")
        if chat_log:
            assert log_urls == [f"tgram://{tg.get('bot_token', '')}/{chat_log}"], (
                "the 'log' tier must route to chat_log when it is set in SOPS"
            )
        else:
            assert not log_urls, (
                "the 'log' tier must be omitted (graceful degradation) when chat_log is unset"
            )
