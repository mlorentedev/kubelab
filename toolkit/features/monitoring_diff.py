"""Pure decision layer for the declarative Uptime Kuma monitor sync (OPS-016).

Split out of `monitoring.apply_monitors`, which interleaved deciding and doing in
a single loop and therefore could not be tested without a live instance. Nothing
here talks to Uptime Kuma; it takes the seed and the live state and returns what
should happen.

**Identity.** A monitor's identity is an immutable `key` carried in the seed, not
its name — keying on the name would make a rename read as delete + create and
silently discard that monitor's uptime history, which is the exact defect #962
exists to remove. Uptime Kuma persists only its own fields (`_MONITOR_EXPORT_FIELDS`)
and offers nowhere to store a custom one, so the key travels inside `description`
as a marker. `export` strips it back out, keeping the seed clean.

**Matching is marker-first with a name fallback**, and the fallback is what makes
migration free: the first sync against an instance that has never been marked
adopts its 31 existing monitors by name and stamps them, rather than deleting
them all and starting over.
"""

from __future__ import annotations

import re
from typing import Any

# Fields excluded from the comparison, applied to BOTH sides.
#
# The rule is: compare exactly the fields the sync would write. A field that the
# apply path never sends can never be reconciled, so flagging it as a difference
# produces an edit that cannot clear the flag — the monitor is then rewritten on
# every run, forever. An earlier version stripped these from the live side only,
# which made all 31 real monitors permanently dirty.
_IGNORED_IN_COMPARISON = frozenset(
    {
        "key",  # ours, not Uptime Kuma's — it travels inside `description`
        "id",  # assigned by the instance
        "active",  # paused/resumed at runtime, not owned by the seed
        "tags",  # applied through add_monitor_tag, not through edit
        "notificationIDList",  # excluded from `_ACCEPTED`: ids differ per instance
    }
)

_MARKER_TEMPLATE = "[kuma-key:{key}]"
_MARKER_RE = re.compile(r"\n?\[kuma-key:(?P<key>[A-Za-z0-9._-]+)\]")


def extract_key(description: str | None) -> str | None:
    """Return the embedded key, or None when the description carries no marker."""
    if not description:
        return None
    match = _MARKER_RE.search(description)
    return match.group("key") if match else None


def strip_key(description: str | None) -> str:
    """Return the description with any marker removed — the human-authored text."""
    if not description:
        return ""
    return _MARKER_RE.sub("", description)


def embed_key(description: str | None, key: str) -> str:
    """Return the description carrying exactly one marker for `key`.

    Idempotent, and replaces a stale key rather than appending a second marker:
    this runs on every sync, so a version that appended would grow the field
    without bound.
    """
    base = strip_key(description)
    marker = _MARKER_TEMPLATE.format(key=key)
    return f"{base}\n{marker}" if base else marker


def _comparable(monitor: dict[str, Any]) -> dict[str, Any]:
    """Project a monitor onto the fields that decide whether it differs.

    Both sides go through this, with the same exclusion set — an asymmetric
    projection is what made every monitor look permanently dirty.
    """
    out = {k: v for k, v in monitor.items() if k not in _IGNORED_IN_COMPARISON}
    # The marker is an implementation detail of identity, not a user-visible
    # difference — compare the human text so a stamped monitor is not seen as
    # permanently drifted from its own seed entry.
    if "description" in out:
        out["description"] = strip_key(out["description"])
    return out


def _needs_edit(seed_entry: dict[str, Any], live_monitor: dict[str, Any]) -> bool:
    """True when the live monitor does not already match its seed entry.

    Only fields the seed actually declares are compared. The live monitor carries
    dozens of Uptime Kuma defaults the seed never mentions, and treating those as
    differences would mark every monitor dirty on every run — the no-op case is
    the one that matters most here.
    """
    if seed_entry.get("key") and extract_key(live_monitor.get("description")) is None:
        # Converged in content but unmarked: it still needs one edit to stamp the
        # key, or identity never lands and the next rename falls back to matching
        # by name forever.
        #
        # Gated on the seed actually declaring a key. Without the guard a seed
        # that has not been keyed yet — which is every seed until the migration
        # lands — would report all 31 monitors dirty on every single run, so the
        # steady state would never be a no-op.
        return True

    desired = _comparable(seed_entry)
    current = _comparable(live_monitor)
    return any(current.get(field) != value for field, value in desired.items())


def diff_monitors(
    seed: list[dict[str, Any]],
    live: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (to_create, to_edit, to_delete) for a declarative sync.

    - `to_create` — seed entries with no counterpart on the instance.
    - `to_edit` — live monitors that matched a seed entry and differ from it. Each
      carries the live `id` plus the seed fields to apply, under `_seed`.
    - `to_delete` — live monitors matching no seed entry. The seed is the source
      of truth, so an unmatched monitor is one the seed dropped.

    A live monitor is claimed at most once, so two seed entries sharing a name
    cannot both adopt it — the second is created instead.
    """
    by_key: dict[str, dict[str, Any]] = {}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for monitor in live:
        key = extract_key(monitor.get("description"))
        if key is not None:
            by_key.setdefault(key, monitor)
        by_name.setdefault(monitor.get("name", ""), []).append(monitor)

    claimed: set[int] = set()
    to_create: list[dict[str, Any]] = []
    to_edit: list[dict[str, Any]] = []

    for entry in seed:
        key = entry.get("key")
        match = by_key.get(key) if key is not None else None

        if match is None or match["id"] in claimed:
            # Fallback: adopt an unclaimed live monitor with the same name.
            match = next(
                (m for m in by_name.get(entry.get("name", ""), []) if m["id"] not in claimed),
                None,
            )

        if match is None:
            to_create.append(entry)
            continue

        claimed.add(match["id"])
        if _needs_edit(entry, match):
            to_edit.append({**match, "_seed": entry})

    to_delete = [m for m in live if m["id"] not in claimed]
    return to_create, to_edit, to_delete
