"""Uptime Kuma API integration — export/import monitors as config-as-code."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from uptime_kuma_api import UptimeKumaApi

from toolkit.core.logging import logger
from toolkit.features.configuration import ConfigurationManager

# Fields to export per monitor (skip volatile/internal fields)
_MONITOR_EXPORT_FIELDS = [
    "name",
    "type",
    "url",
    "hostname",
    "port",
    "interval",
    "retry_interval",
    "maxretries",
    "method",
    "keyword",
    "ignoreTls",
    "upsideDown",
    "accepted_statuscodes",
    "description",
    "active",
    "httpBodyEncoding",
    "maxredirects",
    "notificationIDList",
    "parent",
    "tags",
]

_NOTIFICATION_EXPORT_FIELDS = [
    "name",
    "type",
    "isDefault",
    "active",
    "config",
]

EXPORT_DIR = "infra/config/uptime-kuma"
MONITORS_FILE = "monitors.json"
NOTIFICATIONS_FILE = "notifications.json"


def _get_kuma_creds(project_root: Path) -> dict[str, str]:
    """Load Uptime Kuma URL and credentials from SSOT config + SOPS."""
    cm = ConfigurationManager("staging", project_root)
    merged = cm.get_merged_config()

    node = merged.get("networking", {}).get("nodes", {}).get("rpi3", {})
    svc = merged.get("apps", {}).get("services", {}).get("observability", {}).get("uptime_kuma", {})
    host = node.get("tailscale_ip", "")
    port = svc.get("default_port", 3001)

    secrets = cm._decrypt_sops(cm.secrets_path / "common.enc.yaml") or {}
    uk_secrets = secrets.get("apps", {}).get("services", {}).get("observability", {}).get("uptime_kuma", {})

    username = uk_secrets.get("admin_user", "admin")
    password = uk_secrets.get("admin_password", "")

    if not password:
        logger.error(
            "Uptime Kuma admin_password not found in SOPS. "
            "Run: toolkit secrets set apps.services.observability.uptime_kuma.admin_password <password> --env common"
        )
        raise SystemExit(1)

    return {"url": f"http://{host}:{port}", "host": host, "username": username, "password": password}


def _connect(project_root: Path) -> tuple[UptimeKumaApi, dict[str, Any]]:
    """Connect to Uptime Kuma via API using SOPS credentials."""
    creds = _get_kuma_creds(project_root)
    logger.info(f"Connecting to Uptime Kuma at {creds['url']}...")
    api = UptimeKumaApi(creds["url"], timeout=60)
    api.login(creds["username"], creds["password"])
    logger.success("Connected to Uptime Kuma")
    return api, {"url": creds["url"], "host": creds["host"]}


def _clean_monitor(monitor: dict[str, Any]) -> dict[str, Any]:
    """Strip volatile fields, keep only exportable config."""
    return {k: monitor[k] for k in _MONITOR_EXPORT_FIELDS if k in monitor}


def _clean_notification(notification: dict[str, Any]) -> dict[str, Any]:
    """Strip volatile fields from notification."""
    return {k: notification[k] for k in _NOTIFICATION_EXPORT_FIELDS if k in notification}


def export_monitors(project_root: Path) -> Path:
    """Export all monitors and notifications to JSON files."""
    api, info = _connect(project_root)

    try:
        monitors = api.get_monitors()
        notifications = api.get_notifications()

        clean_monitors = [_clean_monitor(m) for m in monitors]
        clean_notifications = [_clean_notification(n) for n in notifications]

        export_dir = project_root / EXPORT_DIR
        export_dir.mkdir(parents=True, exist_ok=True)

        monitors_path = export_dir / MONITORS_FILE
        monitors_path.write_text(json.dumps(clean_monitors, indent=2, default=str) + "\n")
        logger.success(f"Exported {len(clean_monitors)} monitors → {monitors_path}")

        notifications_path = export_dir / NOTIFICATIONS_FILE
        notifications_path.write_text(json.dumps(clean_notifications, indent=2, default=str) + "\n")
        logger.success(f"Exported {len(clean_notifications)} notifications → {notifications_path}")

        return monitors_path
    finally:
        api.disconnect()


def import_monitors(project_root: Path) -> None:
    """Import monitors and notifications from JSON seed files."""
    api, info = _connect(project_root)

    try:
        export_dir = project_root / EXPORT_DIR
        monitors_path = export_dir / MONITORS_FILE
        notifications_path = export_dir / NOTIFICATIONS_FILE

        if not monitors_path.exists():
            logger.error(f"No monitors file found at {monitors_path}. Run export first.")
            raise SystemExit(1)

        monitors_data = json.loads(monitors_path.read_text())
        notifications_data = json.loads(notifications_path.read_text()) if notifications_path.exists() else []

        # Use Uptime Kuma's backup import format
        backup_data = json.dumps(
            {
                "version": "1.23.0",
                "notificationList": notifications_data,
                "monitorList": monitors_data,
                "proxyList": [],
            }
        )

        api.upload_backup(json_data=backup_data, import_handle="skip")
        logger.success(
            f"Imported {len(monitors_data)} monitors + {len(notifications_data)} notifications (skipped existing)"
        )
    finally:
        api.disconnect()


def bootstrap(project_root: Path) -> None:
    """Full bootstrap: create admin user (if fresh) + import monitors from seed.

    Credentials come from SOPS (SSOT). Idempotent — skips setup if user exists,
    skips monitors that already exist.
    """
    creds = _get_kuma_creds(project_root)
    api = UptimeKumaApi(creds["url"], timeout=60)

    # Try setup (first run — no user yet)
    fresh_install = False
    try:
        api.setup(creds["username"], creds["password"])
        logger.success(f"Created admin user '{creds['username']}' from SOPS credentials")
        fresh_install = True
    except Exception:
        # Already set up — login instead
        logger.info("Admin user already exists, logging in...")
        api.login(creds["username"], creds["password"])

    # Only import on fresh install (existing monitors = already configured)
    if not fresh_install:
        existing = api.get_monitors()
        if existing:
            logger.success(f"Instance has {len(existing)} monitors — skipping import")
            api.disconnect()
            return

    # Import monitors + notifications from seed
    try:
        export_dir = project_root / EXPORT_DIR
        monitors_path = export_dir / MONITORS_FILE
        notifications_path = export_dir / NOTIFICATIONS_FILE

        if not monitors_path.exists():
            logger.warning(f"No seed file at {monitors_path} — skipping import")
            return

        monitors_data = json.loads(monitors_path.read_text())
        notifications_data = json.loads(notifications_path.read_text()) if notifications_path.exists() else []

        backup_data = json.dumps(
            {
                "version": "1.23.0",
                "notificationList": notifications_data,
                "monitorList": monitors_data,
                "proxyList": [],
            }
        )
        api.upload_backup(json_data=backup_data, import_handle="skip")
        logger.success(f"Imported {len(monitors_data)} monitors + {len(notifications_data)} notifications")
    finally:
        api.disconnect()
