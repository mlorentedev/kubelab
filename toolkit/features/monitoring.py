"""Uptime Kuma API integration — export/import monitors as config-as-code."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from uptime_kuma_api import UptimeKumaApi

from toolkit.core.logging import logger
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.monitoring_diff import (
    SEED_TO_API_FIELD,
    WRITABLE_FIELDS,
    diff_monitors,
    embed_key,
    extract_key,
    strip_key,
)

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

        def _params(m: dict[str, Any]) -> dict[str, Any]:
            """Map a seed entry onto the fields the API accepts.

            Both the payload and the diff's comparison derive from
            `WRITABLE_FIELDS`, so "compare exactly what you write" holds by
            construction instead of by two hand-maintained lists.
            """
            params: dict[str, Any] = {}
            for k, v in m.items():
                if v is None or k not in WRITABLE_FIELDS:
                    continue
                params[SEED_TO_API_FIELD.get(k, k)] = v
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


# A just-opened Kuma v2 socket needs to settle before its first call gets a
# reply. Measured against a throwaway instance: `need_setup()` and the raw
# `setup` emit both timed out as the first thing sent on a fresh connection,
# every time, without this — `login()` elsewhere in this file has never shown
# the symptom, so the settle is scoped to bootstrap's cold-connection path
# rather than added everywhere. One constant, so both call sites below agree
# on the value instead of carrying their own independent guess.
_SOCKET_SETTLE_SECONDS = 1.0


def _settle(api: UptimeKumaApi) -> None:
    """Block briefly so a just-opened socket is ready for its first call."""
    time.sleep(_SOCKET_SETTLE_SECONDS)


def _run_setup(api: UptimeKumaApi, username: str, password: str) -> None:
    """Create the admin user by emitting `setup` on the raw socket.

    `UptimeKumaApi.setup()` (`api.sio.call("setup", ...)`) times out against
    Kuma v2 — the installed `uptime-kuma-api` wrapper predates v2's setup
    handshake. A manually-polled `emit` gets a real `{"ok": True, ...}` ack, the
    same workaround already proven in `test_monitoring_integration.py`'s fixture.

    Raises on timeout or a negative ack rather than returning silently: the bug
    this replaces was a bare `except Exception` around `api.setup()` that read a
    timeout as "admin already exists" and fell through to `login()`, which then
    failed with the wrong error on a genuinely fresh instance (#962).

    Settles the connection itself (rather than trusting the caller already
    did) so the function is safe to call directly on a cold connection too —
    which is exactly how the integration test's fixture uses it.
    """
    result: dict[str, Any] = {}
    _settle(api)
    api.sio.emit("setup", (username, password), callback=lambda r: result.update(r or {}))
    deadline = time.monotonic() + api.timeout
    while not result and time.monotonic() < deadline:
        time.sleep(0.5)
    if not result:
        raise TimeoutError(f"Uptime Kuma setup did not acknowledge within {api.timeout}s")
    if not result.get("ok", False):
        raise RuntimeError(f"Uptime Kuma setup failed: {result}")


def bootstrap(project_root: Path) -> None:
    """Full bootstrap: create the admin user (if fresh) + import the seed.

    Credentials come from SOPS (SSOT). Runs unattended on every rpi3 provision
    (Ansible), not just the first one, so an already-configured instance MUST
    be left completely untouched — only a genuinely fresh install (no admin,
    therefore no monitors yet) imports the seed. `apply_monitors` is safe to
    call for that import specifically because a from-scratch instance has zero
    live monitors, so its diff can only ever produce creates, never edits or
    deletes; calling it unconditionally here would give an automated, unattended
    path the power to delete monitors from a live instance the seed has drifted
    from — the exact hazard #962/#925 removed from `apply_monitors` itself.

    Does not recreate notifications: `infra/config/uptime-kuma/notifications.json`
    deliberately omits the Slack webhook's `config` (it is a secret, and this
    file is committed to git), so a from-scratch instance needs one manual
    notification setup regardless of this function (see OBS-014).
    """
    creds = _get_kuma_creds(project_root)
    api = UptimeKumaApi(creds["url"], timeout=60)
    _settle(api)

    # `need_setup()` decides the branch authoritatively — a read with no v1/v2
    # handshake mismatch — instead of inferring "already set up" from whichever
    # exception `setup()` happened to raise, which is what let a timeout pass
    # for success (#962).
    fresh_install = api.need_setup()
    if fresh_install:
        _run_setup(api, creds["username"], creds["password"])
        logger.success(f"Created admin user '{creds['username']}' from SOPS credentials")
    else:
        logger.info("Admin user already exists — instance already configured, nothing to do")
    api.disconnect()

    if not fresh_install:
        return

    # `upload_backup`'s v1 backup envelope times out against Kuma v2 — flagged
    # as untested in #962 and confirmed broken while verifying this fix live.
    # `apply_monitors` already owns a working, tested create path (every
    # monitor on a from-scratch instance goes through it too), so bootstrap
    # delegates to it instead of carrying a second, broken import mechanism.
    apply_monitors(project_root)
