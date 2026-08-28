"""Vikunja platform reconciler: idempotently provisions namespaces, labels, and webhooks."""

from __future__ import annotations

from dataclasses import dataclass

from toolkit.core.logging import logger
from toolkit.features.vikunja_client import VikunjaClient

DEFAULT_NAMESPACES = (
    "kubelab",
    "personal",
    "teledyne",
)

DEFAULT_LABELS = {
    "type:spec": "#2ecc71",
    "type:bug": "#e74c3c",
    "type:chore": "#95a5a6",
    "agent:delegable": "#4a90e2",
    "priority:P0": "#c0392b",
    "priority:P1": "#e67e22",
    "priority:P2": "#f1c40f",
    "priority:P3": "#3498db",
}


@dataclass(frozen=True)
class ReconcileResult:
    """Result of a Vikunja platform reconciliation run."""

    namespaces_created: int
    labels_created: int
    webhooks_created: int

    @property
    def changed(self) -> bool:
        return (self.namespaces_created + self.labels_created + self.webhooks_created) > 0


class VikunjaReconciler:
    """Idempotently synchronizes desired namespaces, labels, and webhooks to Vikunja."""

    def __init__(self, client: VikunjaClient) -> None:
        self.client = client

    def reconcile(self, n8n_webhook_url: str = "http://n8n:5678/webhook/agent-dispatcher") -> ReconcileResult:
        """Run full platform reconciliation. Safe to re-run anytime (changed=0 on re-run)."""
        namespaces_created = self._reconcile_namespaces()
        labels_created = self._reconcile_labels()
        webhooks_created = self._reconcile_webhooks(n8n_webhook_url=n8n_webhook_url)

        result = ReconcileResult(
            namespaces_created=namespaces_created,
            labels_created=labels_created,
            webhooks_created=webhooks_created,
        )

        if result.changed:
            logger.info(
                f"Vikunja reconciled: created {result.namespaces_created} namespaces, "
                f"{result.labels_created} labels, {result.webhooks_created} webhooks."
            )
        else:
            logger.info("Vikunja already in desired state (changed=0).")

        return result

    def _reconcile_namespaces(self) -> int:
        existing = {ns.get("title", ""): ns for ns in self.client.get_namespaces()}
        created = 0

        for desired in DEFAULT_NAMESPACES:
            if desired not in existing:
                logger.info(f"Creating missing Vikunja namespace: {desired}")
                self.client.create_namespace(title=desired)
                created += 1

        return created

    def _reconcile_labels(self) -> int:
        existing = {lbl.get("title", ""): lbl for lbl in self.client.get_labels()}
        created = 0

        for label_title, color in DEFAULT_LABELS.items():
            if label_title not in existing:
                logger.info(f"Creating missing Vikunja label: {label_title} ({color})")
                self.client.create_label(title=label_title, hex_color=color)
                created += 1

        return created

    def _reconcile_webhooks(self, n8n_webhook_url: str) -> int:
        projects = self.client.get_projects()
        created = 0

        for proj in projects:
            proj_id = proj.get("id")
            if not proj_id:
                continue

            existing_webhooks = self.client.get_webhooks(proj_id)
            has_webhook = any(wh.get("target_url") == n8n_webhook_url for wh in existing_webhooks)
            if not has_webhook:
                logger.info(f"Registering n8n webhook on project {proj_id} ({proj.get('title')})")
                self.client.create_webhook(
                    project_id=proj_id,
                    target_url=n8n_webhook_url,
                    events=["task.updated", "task.created"],
                )
                created += 1

        return created
