"""Refuse a Terraform plan that deletes something nobody said it may delete (TF-013).

An apply with `-auto-approve` shows nobody its plan. That is fine for creates
and in-place updates, which is what the DNS, GCP and AWS roots normally carry.
It is not fine for a delete. A replace is a delete followed by a create, and a
resource that Terraform marked tainted is planned as one. lesson-543: a
Cloudflare create that timed out had landed, Terraform tainted it, and the next
auto-approved apply would have deleted a live record that SSO was already
redirecting to.

The guard reads `terraform show -json <plan>` and names every change whose
actions include `delete`. The caller then applies that same saved plan, so what
was checked is exactly what runs. It knows nothing about any provider or root.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Change:
    address: str
    actions: tuple[str, ...]
    reason: str | None = None

    @property
    def kind(self) -> str:
        return "replace" if "create" in self.actions else "delete"

    def describe(self) -> str:
        why = f" ({self.reason})" if self.reason else ""
        return f"{self.kind} {self.address}{why}"


def changes(plan: dict[str, Any]) -> list[Change]:
    """Every resource change in the plan, no-ops and reads included."""
    return [
        Change(
            address=rc["address"],
            actions=tuple(rc.get("change", {}).get("actions", [])),
            reason=rc.get("action_reason"),
        )
        for rc in plan.get("resource_changes", [])
    ]


def summary(plan: dict[str, Any]) -> Counter[str]:
    """Counts of create, update and delete, the way `terraform plan` states them."""
    counts: Counter[str] = Counter()
    for change in changes(plan):
        for action in change.actions:
            if action in {"create", "update", "delete"}:
                counts[action] += 1
    return counts


def refused(
    plan: dict[str, Any], *, allow_destroy: bool = False, allowed: frozenset[str] = frozenset()
) -> list[Change]:
    """The changes that delete and were not allowed, by flag or by address."""
    if allow_destroy:
        return []
    return [c for c in changes(plan) if "delete" in c.actions and c.address not in allowed]
