"""Cloudflare R2 Backup Health & Snapshot Coverage Prober (OBS-015 / BACKUP-044).

Runs the isolation probe (each node's bucket refuses the other nodes' pairs and
locks its own data) and coverage (cross-node snapshot verification), then dispatches
a structured SRE notification to n8n /webhook/notify.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from toolkit.core.logging import logger
from toolkit.features.backup_destination import coverage
from toolkit.features.backup_isolation import probe_fleet
from toolkit.features.configuration import ConfigurationManager

_NOTIFY_SECRET_PATH = "apps.services.automation.notify.webhook_secret"
_N8N_DOMAIN_PATH = "apps.services.automation.n8n.domain"


def run_r2_backup_health_check(
    env: str = "prod",
    notify: bool = True,
    project_root: Optional[Path] = None,
) -> bool:
    """Execute full R2 backup verification and dispatch notification."""
    cm = ConfigurationManager(env, project_root)

    logger.info(f"[{env.upper()}] Step 1/2: Probing the node buckets' isolation and lock...")
    isolation_ok = probe_fleet(env, cm=cm)

    logger.info(f"[{env.upper()}] Step 2/2: Verifying fleet snapshot coverage...")
    cov_ok = coverage(env=env, project_root=project_root)

    is_healthy = isolation_ok and cov_ok

    if is_healthy:
        logger.success(f"[{env.upper()}] Cloudflare R2 backup integrity and fleet coverage: HEALTHY")
    else:
        logger.error(f"[{env.upper()}] Cloudflare R2 backup: FAILED (isolation={isolation_ok}, cov={cov_ok})")

    if notify:
        _dispatch_notification(cm, env=env, is_healthy=is_healthy, isolation_ok=isolation_ok, cov_ok=cov_ok)

    return is_healthy


def _dispatch_notification(
    cm: ConfigurationManager,
    env: str,
    is_healthy: bool,
    isolation_ok: bool,
    cov_ok: bool,
) -> bool:
    """Send structured notification to n8n /webhook/notify."""
    secret = cm.get_secret_by_path(_NOTIFY_SECRET_PATH)
    if not secret:
        logger.warning("Notification secret not found in SOPS — skipping alert dispatch.")
        return False

    merged = cm.get_merged_config()
    n8n_domain = (
        merged.get("apps", {})
        .get("services", {})
        .get("automation", {})
        .get("n8n", {})
        .get("domain", f"n8n.{env}.kubelab.live" if env != "prod" else "n8n.kubelab.live")
    )

    url = f"https://{n8n_domain}/webhook/notify"

    if is_healthy:
        payload = {
            "domain": "ops",
            "severity": "log",
            "title": f"[{env.upper()}] Cloudflare R2 Backup Health: 100% HEALTHY",
            "body": "Node bucket isolation and lock held and all active fleet node snapshots verified.",
            "source": "k8s/r2-backup-health",
            "url": "https://argo.kubelab.live",
            "url_title": "Open in Argo CD",
        }
    else:
        payload = {
            "domain": "ops",
            "severity": "page",
            "title": f"[{env.upper()}] Cloudflare R2 Backup Health: FAILED",
            "body": (
                f"Backup verification failure: isolation_and_lock={isolation_ok}, "
                f"snapshot_coverage={cov_ok}. Check node logs in #ops-log."
            ),
            "source": "k8s/r2-backup-health",
            "url": "https://github.com/mlorentedev/kubelab/issues",
            "url_title": "View GitHub Issues",
        }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {secret}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                logger.success(f"Dispatched R2 backup health alert to {url} (HTTP 200)")
                return True
            logger.warning(f"Notification returned HTTP {resp.status}")
            return False
    except Exception as exc:
        logger.error(f"Failed to dispatch R2 backup health alert: {exc}")
        return False
