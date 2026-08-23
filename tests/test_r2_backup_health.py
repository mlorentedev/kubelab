"""Unit tests for Cloudflare R2 Backup Health prober and notifier (OBS-015)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from toolkit.features.r2_backup_health import run_r2_backup_health_check


@pytest.fixture
def mock_cm() -> MagicMock:
    cm = MagicMock()
    cm.get_secret_by_path.return_value = "mock-notify-secret"
    cm.get_merged_config.return_value = {
        "apps": {
            "services": {
                "automation": {
                    "n8n": {
                        "domain": "n8n.kubelab.live"
                    }
                }
            }
        }
    }
    return cm


def test_r2_backup_health_success(mock_cm: MagicMock) -> None:
    with patch("toolkit.features.r2_backup_health.ConfigurationManager", return_value=mock_cm), \
         patch("toolkit.features.r2_backup_health.verify_destination", return_value=True), \
         patch("toolkit.features.r2_backup_health.coverage", return_value=True), \
         patch("toolkit.features.r2_backup_health._dispatch_notification") as mock_dispatch:

        result = run_r2_backup_health_check(env="prod", notify=True)
        assert result is True
        mock_dispatch.assert_called_once_with(
            mock_cm, env="prod", is_healthy=True, dest_ok=True, cov_ok=True
        )


def test_r2_backup_health_failure(mock_cm: MagicMock) -> None:
    with patch("toolkit.features.r2_backup_health.ConfigurationManager", return_value=mock_cm), \
         patch("toolkit.features.r2_backup_health.verify_destination", return_value=True), \
         patch("toolkit.features.r2_backup_health.coverage", return_value=False), \
         patch("toolkit.features.r2_backup_health._dispatch_notification") as mock_dispatch:

        result = run_r2_backup_health_check(env="prod", notify=True)
        assert result is False
        mock_dispatch.assert_called_once_with(
            mock_cm, env="prod", is_healthy=False, dest_ok=True, cov_ok=False
        )


def test_r2_backup_health_no_notify(mock_cm: MagicMock) -> None:
    with patch("toolkit.features.r2_backup_health.ConfigurationManager", return_value=mock_cm), \
         patch("toolkit.features.r2_backup_health.verify_destination", return_value=True), \
         patch("toolkit.features.r2_backup_health.coverage", return_value=True), \
         patch("toolkit.features.r2_backup_health._dispatch_notification") as mock_dispatch:

        result = run_r2_backup_health_check(env="prod", notify=False)
        assert result is True
        mock_dispatch.assert_not_called()
