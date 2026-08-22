"""Detach a project's billing account when a budget threshold is crossed.

GCP budgets notify; they do not cap. The only hard stop Google offers is
removing the billing account from the project, which stops every billable
resource in it. This is that stop.

WHAT IT ACTS ON COMES FROM THE ENVIRONMENT, NEVER FROM THE MESSAGE.

A real budget notification carries `budgetDisplayName`, `costAmount`,
`budgetAmount` and `currencyCode` -- and nothing identifying a project to act
on. Reading a target out of the payload would therefore add a branch that never
executes in production, and the only test able to reach it would be a synthetic
message: the test would prove a test-only path.

Putting the target in `TARGET_PROJECT` is also what makes the real test
possible. Point it at an empty scratch project on the same billing account,
publish a message shaped like a genuine notification, and the function
exercises the same `updateBillingInfo` call it would make for real -- without
spending anything and without taking the hub down.

There is deliberately no DRY_RUN mode. It would skip exactly the one API call
that can be wrong.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

import functions_framework
import google.auth
from googleapiclient import discovery

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("billing-killswitch")


def _billing_client() -> Any:
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return discovery.build("cloudbilling", "v1", credentials=credentials, cache_discovery=False)


def _detach(project_id: str) -> None:
    """Remove the billing account, stopping every billable resource.

    An empty `billingAccountName` is the documented way to disable billing; there
    is no separate "disable" call.
    """
    client = _billing_client()
    name = f"projects/{project_id}"
    result = client.projects().updateBillingInfo(name=name, body={"billingAccountName": ""}).execute()
    log.warning("BILLING DETACHED for %s -> billingEnabled=%s", project_id, result.get("billingEnabled"))


@functions_framework.cloud_event
def kill_switch(cloud_event: Any) -> None:
    """Pub/Sub entry point. One budget notification in, at most one detach out."""
    target = os.environ.get("TARGET_PROJECT", "").strip()
    if not target:
        # Refuse rather than guess. A kill switch that silently no-ops is
        # indistinguishable from one that works, right up until it is needed.
        raise RuntimeError("TARGET_PROJECT is unset; refusing to act on an unnamed project")

    encoded = cloud_event.data.get("message", {}).get("data", "")
    payload = json.loads(base64.b64decode(encoded).decode()) if encoded else {}

    cost = float(payload.get("costAmount", 0) or 0)
    budget = float(payload.get("budgetAmount", 0) or 0)
    label = payload.get("budgetDisplayName", "<unnamed budget>")

    # Budgets publish on EVERY threshold and periodically besides, so the great
    # majority of messages are routine and must not trigger anything. A budget of
    # 0 would make `cost >= budget` true for a message reporting no spend at all.
    if budget <= 0:
        log.info("%s: budgetAmount is %s; ignoring", label, budget)
        return

    if cost < budget:
        log.info("%s: %.2f of %.2f, under threshold", label, cost, budget)
        return

    log.warning("%s: %.2f of %.2f -- detaching billing from %s", label, cost, budget, target)
    _detach(target)
