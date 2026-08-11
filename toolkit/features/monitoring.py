"""Uptime Kuma API integration — export/import monitors as config-as-code."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from uptime_kuma_api import UptimeKumaApi

from toolkit.core.logging import logger
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.monitoring_diff import diff_monitors, embed_key, extract_key, strip_key

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
TAGS_FILE = "tags.json"


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
    """Strip volatile fields, keep only exportable config.

    Lifts the identity marker back out of `description` into a first-class `key`,
    so the seed stays human-readable and the round-trip is lossless: `apply`
    embeds the marker, `export` extracts it.
    """
    clean = {k: monitor[k] for k in _MONITOR_EXPORT_FIELDS if k in monitor}
    key = extract_key(clean.get("description"))
    if key is not None:
        clean["description"] = strip_key(clean["description"])
        clean = {"key": key, **clean}
    return clean


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


def _assert_deleted(api: UptimeKumaApi, deleted_ids: list[int], timeout: float = 30.0) -> None:
    """Block until every id is gone, or raise. Never proceed on an unmet precondition.

    Replaces a fixed `time.sleep(3)` whose result was computed, logged at SUCCESS
    level and then never branched on (#925) — a race with a reassuring message.

    The poll reads `get_monitor(id)` rather than `get_monitors()` on purpose:
    `get_monitors()` returns a client-side cache fed by socket events and can lag
    a write by many seconds, so polling it would replace a fixed guess with a
    longer one and still be racing. `get_monitor(id)` is an authoritative read.
    """
    if not deleted_ids:
        return

    deadline = time.monotonic() + timeout
    pending = list(deleted_ids)
    while pending and time.monotonic() < deadline:
        still_here = []
        for monitor_id in pending:
            try:
                api.get_monitor(monitor_id)
                still_here.append(monitor_id)
            except Exception:
                pass  # Gone — which is the outcome we are waiting for.
        pending = still_here
        if pending:
            time.sleep(0.5)

    if pending:
        raise RuntimeError(
            f"{len(pending)} monitor(s) still present {timeout}s after deletion: {pending}. "
            "Refusing to create — proceeding here is how the instance ends up with duplicates."
        )
    logger.success(f"Deleted {len(deleted_ids)} monitor(s), confirmed gone")


def apply_monitors(project_root: Path) -> None:
    """Declarative sync: converge the live instance onto the seed by upserting.

    The seed JSON is the source of truth. Monitors are matched by an immutable
    `key` carried in `description` (marker-first, name fallback), so a rename is
    an edit rather than a delete + create and uptime history survives a sync.
    Adds monitors one-by-one via API (avoids upload_backup timeout on RPi3).
    """
    api, info = _connect(project_root)

    try:
        export_dir = project_root / EXPORT_DIR
        monitors_path = export_dir / MONITORS_FILE

        if not monitors_path.exists():
            logger.error(f"No seed file at {monitors_path}. Run 'make monitoring-export' first.")
            raise SystemExit(1)

        seed_monitors = json.loads(monitors_path.read_text())

        # Ensure tags exist (from SSOT tags.json)
        tags_path = export_dir / TAGS_FILE
        tag_id_map: dict[str, int] = {}
        if tags_path.exists():
            seed_tags = json.loads(tags_path.read_text())
            existing_tags = {t["name"]: t["id"] for t in api.get_tags()}
            for t in seed_tags:
                if t["name"] in existing_tags:
                    tag_id_map[t["name"]] = existing_tags[t["name"]]
                else:
                    try:
                        result = api.add_tag(name=t["name"], color=t["color"])
                        tag_id_map[t["name"]] = result["id"]
                    except Exception:
                        pass
            logger.success(f"Tags ready: {len(tag_id_map)} ({', '.join(tag_id_map)})")

        # Decide before doing. The plan is computed by a pure function so it can
        # be tested without a live instance (tests/test_monitoring_diff.py).
        live = api.get_monitors()
        to_create, to_edit, to_delete = diff_monitors(seed_monitors, live)
        logger.info(
            f"Sync plan: {len(to_create)} create, {len(to_edit)} edit, "
            f"{len(to_delete)} delete (live={len(live)}, seed={len(seed_monitors)})"
        )

        # Deletes only for monitors the seed dropped — never the whole set. The
        # previous implementation deleted all 31 and recreated them, discarding
        # every monitor's accumulated uptime history on each run (#962).
        for m in to_delete:
            logger.info(f"Deleting '{m.get('name')}' (id={m['id']}) — not in seed")
            api.delete_monitor(m["id"])
        _assert_deleted(api, [m["id"] for m in to_delete])

        # Get default notification ID for linking
        default_notif_ids = [n["id"] for n in api.get_notifications() if n.get("isDefault")]

        # Only pass fields that _build_monitor_data accepts
        _ACCEPTED = {
            "type",
            "name",
            "url",
            "hostname",
            "port",
            "interval",
            "retryInterval",
            "maxretries",
            "method",
            "keyword",
            "ignoreTls",
            "upsideDown",
            "accepted_statuscodes",
            "description",
            "httpBodyEncoding",
            "maxredirects",
            "parent",
            "resendInterval",
            "body",
            "headers",
            "basic_auth_user",
            "basic_auth_pass",
            "proxyId",
            "timeout",
            # notificationIDList excluded — IDs change between instances.
            # After apply, link notifications manually or via separate sync step.
        }

        def _params(m: dict[str, Any]) -> dict[str, Any]:
            """Map a seed entry onto the fields the API accepts."""
            params: dict[str, Any] = {}
            for k, v in m.items():
                if v is None:
                    continue
                # Map snake_case export fields to camelCase API fields
                if k == "retry_interval":
                    params["retryInterval"] = v
                elif k in _ACCEPTED:
                    params[k] = v
            # The key rides inside description — Uptime Kuma has no custom field.
            if m.get("key"):
                params["description"] = embed_key(params.get("description", ""), m["key"])
            return params

        # Edits keep the monitor id, and with it the uptime history.
        edited = 0
        for m in to_edit:
            try:
                api.edit_monitor(m["id"], **_params(m["_seed"]))
                edited += 1
            except Exception as e:
                logger.warning(f"Failed to edit '{m.get('name')}': {type(e).__name__}: {e!r}")

        created = 0
        for m in to_create:
            try:
                # Uptime Kuma v2.x requires conditions (NOT NULL in DB)
                # Use low-level sio.call — lib's _call wrapper has issues with v2 responses
                monitor_data = api._build_monitor_data(**_params(m))
                monitor_data["conditions"] = []
                if default_notif_ids:
                    # Uptime Kuma v2 expects {id: true} format, not [id]
                    monitor_data["notificationIDList"] = {str(nid): True for nid in default_notif_ids}
                r = api.sio.call("add", monitor_data, timeout=api.timeout)
                if isinstance(r, dict) and not r.get("ok", True):
                    raise RuntimeError(r.get("msg", "Unknown error"))
                monitor_id = r.get("monitorID") if isinstance(r, dict) else None
                created += 1

                # Associate tags (if defined in seed and tag exists)
                if monitor_id and m.get("tags"):
                    for tag_name in m["tags"]:
                        if tag_name in tag_id_map:
                            try:
                                api.add_monitor_tag(tag_id_map[tag_name], monitor_id, "")
                            except Exception:
                                pass  # Non-critical — tag association failures are cosmetic
            except Exception as e:
                logger.warning(f"Failed to create '{m['name']}': {type(e).__name__}: {e!r}")

        logger.success(
            f"Synced: {created}/{len(to_create)} created, {edited}/{len(to_edit)} edited, {len(to_delete)} deleted"
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
