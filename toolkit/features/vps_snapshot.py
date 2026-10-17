"""Take the prod VPS's snapshot: the rollback of last resort (PREP-002, #244).

A snapshot is an ACTION that produces an artifact, not state to converge, so it is a
toolkit command against the Hetzner Cloud API rather than a Terraform resource (the
state of an immutable point in time has nothing to refresh, and the Terraform roots
are frozen by TF-015). The token is `hetzner.api_key`, already in SOPS.

Crash-consistent only (ADR-024): SQLite may be torn mid-write, so this is the way
back from a failed cutover, not a backup. Backups are `node_backup` (restic to R2).

Properties, each pinned by `tests/test_vps_snapshot.py`:
- idempotent per UTC day (the description carries the date; a second run is a no-op);
- labelled `managed-by=kubelab-toolkit`, and only labelled snapshots are ever pruned;
- the server is found by its Hetzner NAME and refused unless its address equals
  `networking.vps.public_ip`, the guard the firewall module already applies;
- the run waits for the action and re-reads the image: `creating` is not a snapshot.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import requests

API = "https://api.hetzner.cloud/v1"
MANAGED_LABEL = ("managed-by", "kubelab-toolkit")
TOKEN_SECRET_KEY = "hetzner.api_key"
PREFIX = "kubelab-vps-"
#: How many managed snapshots `toolkit infra vps snapshot` leaves behind unless told otherwise (OPS-036).
#: Each is billed and nothing else removes one; the newest is the rollback point until the next replaces it.
DEFAULT_KEEP = 3
#: With pruning off, more managed snapshots than this are worth a warning.
WARN_ABOVE = DEFAULT_KEEP


class SnapshotError(Exception):
    """The snapshot cannot be taken, or did not complete; the message names the fix."""


class PruneError(SnapshotError):
    """The snapshot WAS taken and is `available`; deleting an older one failed.

    Kept apart from `SnapshotError` so a caller can report the rollback point that exists
    instead of letting a failed cleanup read as "no snapshot".
    """

    def __init__(self, message: str, image: dict[str, Any]) -> None:
        super().__init__(message)
        self.image = image


def today_utc() -> date:
    """The UTC day a snapshot is named for; one seam so tests need not race the clock."""
    return datetime.now(UTC).date()


def description_for(day: date) -> str:
    return f"{PREFIX}{day.isoformat()}"


class HetznerClient:
    """Just the Hetzner Cloud calls the snapshot needs."""

    def __init__(self, token: str, timeout: int = 30) -> None:
        self._token = token
        self.timeout = timeout
        self.session = requests.Session()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        kwargs.setdefault("headers", {"Authorization": f"Bearer {self._token}"})
        kwargs.setdefault("timeout", self.timeout)
        resp = self.session.request(method, f"{API}{path}", **kwargs)
        if not resp.ok:
            raise SnapshotError(f"Hetzner API {method} {path} answered {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else {}

    def servers_named(self, name: str) -> list[dict[str, Any]]:
        return list(self._request("GET", "/servers", params={"name": name}).get("servers", []))

    def managed_snapshots(self, server_name: str) -> list[dict[str, Any]]:
        selector = f"{MANAGED_LABEL[0]}={MANAGED_LABEL[1]},server={server_name}"
        images: list[dict[str, Any]] = []
        page: int | None = 1
        while page:
            params = {"type": "snapshot", "label_selector": selector, "per_page": 50, "page": page}
            data = self._request("GET", "/images", params=params)
            images += list(data.get("images", []))
            page = ((data.get("meta") or {}).get("pagination") or {}).get("next_page")
        return images

    def create_snapshot(self, server_id: int, description: str, labels: dict[str, str]) -> dict[str, Any]:
        body = {"type": "snapshot", "description": description, "labels": labels}
        return dict(self._request("POST", f"/servers/{server_id}/actions/create_image", json=body))

    def action(self, action_id: int) -> dict[str, Any]:
        return dict(self._request("GET", f"/actions/{action_id}")["action"])

    def image(self, image_id: int) -> dict[str, Any]:
        return dict(self._request("GET", f"/images/{image_id}")["image"])

    def delete_image(self, image_id: int) -> None:
        self._request("DELETE", f"/images/{image_id}")


@dataclass(frozen=True)
class Plan:
    server_id: int
    server_name: str
    description: str
    labels: dict[str, str]
    existing: dict[str, Any] | None
    prune: list[dict[str, Any]] = field(default_factory=list)
    #: Every managed snapshot that exists now, today's included: what accumulates without `keep`.
    managed_count: int = 0

    @property
    def exists(self) -> bool:
        return self.existing is not None


def _vps(config: dict[str, Any]) -> tuple[str, str]:
    vps = (config.get("networking") or {}).get("vps") or {}
    for key in ("hetzner_server_name", "public_ip"):
        if not vps.get(key):
            raise SnapshotError(
                f"networking.vps.{key} is empty or absent in common.yaml; nothing identifies the server"
            )
    return str(vps["hetzner_server_name"]), str(vps["public_ip"])


def plan(client: HetznerClient, config: dict[str, Any], *, today: date, keep: int | None = None) -> Plan:
    """Read-only: find the server, find today's snapshot, and list what `keep` would prune."""
    if keep is not None and keep < 1:
        raise SnapshotError("--keep must be at least 1: pruning to zero would delete the rollback it exists to protect")
    name, public_ip = _vps(config)

    servers = client.servers_named(name)
    if len(servers) != 1:
        raise SnapshotError(
            f"expected exactly one Hetzner server named {name!r}, found {len(servers)}; "
            "networking.vps.hetzner_server_name must be the account's name, not the OS hostname"
        )
    server = servers[0]
    address = ((server.get("public_net") or {}).get("ipv4") or {}).get("ip")
    if address != public_ip:
        raise SnapshotError(
            f"server {name!r} is at {address}, not networking.vps.public_ip {public_ip}; "
            "refusing to snapshot what may not be the VPS"
        )

    description = description_for(today)
    managed = client.managed_snapshots(name)
    existing = next((i for i in managed if i.get("description") == description), None)

    doomed: list[dict[str, Any]] = []
    if keep is not None:
        # The one being taken counts toward `keep`, so a fresh run never prunes it.
        # Only restorable images compete for a slot: a `creating` or `unavailable` one is
        # neither a rollback point nor safe to delete (it may still be in flight).
        survivors = sorted(
            (i for i in managed if i.get("description") != description and i.get("status") == "available"),
            key=lambda i: str(i.get("created", "")),
            reverse=True,
        )
        # Today's snapshot, new or existing, takes one of the `keep` slots.
        doomed = survivors[keep - 1 :]
    labels = {MANAGED_LABEL[0]: MANAGED_LABEL[1], "server": name}
    return Plan(int(server["id"]), name, description, labels, existing, doomed, len(managed))


def apply(client: HetznerClient, plan_: Plan, *, interval: float = 10.0, timeout: float = 1800.0) -> dict[str, Any]:
    """Take the snapshot (or return today's), wait until it is `available`, then prune."""
    if plan_.exists:
        image = plan_.existing or {}
        # A timed-out earlier run leaves today's image behind unfinished. Finding it by
        # description is not proof it can restore anything, so the same `available` bar
        # as a fresh snapshot applies before the rerun reports success.
        if image.get("status") != "available":
            raise SnapshotError(
                f"today's snapshot {image.get('id')} is {image.get('status')!r}, not 'available'; "
                "wait for Hetzner to finish it and rerun, or delete the image and rerun"
            )
    else:
        created = client.create_snapshot(plan_.server_id, plan_.description, plan_.labels)
        action_id = int(created["action"]["id"])
        image_id = int(created["image"]["id"])
        deadline = time.monotonic() + timeout
        while True:
            action = client.action(action_id)
            if action.get("status") == "success":
                break
            if action.get("status") == "error":
                detail = (action.get("error") or {}).get("message", "no detail")
                raise SnapshotError(f"Hetzner failed the snapshot action {action_id}: {detail}")
            if time.monotonic() >= deadline:
                raise SnapshotError(
                    f"snapshot action {action_id} did not finish within {timeout:.0f}s; check the Hetzner console"
                )
            time.sleep(interval)
        image = client.image(image_id)
        if image.get("status") != "available":
            raise SnapshotError(
                f"image {image_id} is {image.get('status')!r} after a successful action, not 'available'"
            )
    failed: list[str] = []
    for old in plan_.prune:
        try:
            client.delete_image(int(old["id"]))
        except SnapshotError as exc:
            failed.append(f"{old.get('description')} (id {old.get('id')}): {exc}")
    if failed:
        raise PruneError(
            f"snapshot {image.get('id')} is available, but pruning failed for: " + "; ".join(failed), image
        )
    return image
