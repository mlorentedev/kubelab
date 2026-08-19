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
from collections.abc import Mapping
from typing import Any

# The fields the sync actually writes, named as they appear in the seed.
#
# This is the SSOT for both halves of the contract: `monitoring._params()` builds
# its payload from it, and the comparison below is restricted to it. Deriving one
# from the other is the point — the rule "compare exactly the fields you write"
# has to be structural, because maintaining it as two hand-kept lists is how the
# seed ended up with 31 permanently-dirty monitors.
#
# A field absent here is one the apply path never sends via `_params()`, so
# flagging it as a difference would request an edit that cannot clear the flag.
# Known members of that set, all observed live: `expiryNotification` (in the
# seed but in neither `_MONITOR_EXPORT_FIELDS` nor the API payload — 20
# monitors), `tags` (applied via add_monitor_tag), `active` (paused/resumed at
# runtime), `id`, and `key` (ours; it travels in `description`).
#
# `notificationIDList` is deliberately NOT here despite the apply path writing
# it on every create/edit (#912): its comparison is boolean presence against
# `muted_tags`/`has_default_notification`, not the field-equality check this
# set drives — see `_needs_edit`, `wants_notifications`.
WRITABLE_FIELDS = frozenset(
    {
        "type",
        "name",
        "url",
        "hostname",
        "port",
        "interval",
        "retry_interval",  # sent as `retryInterval`
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
        # A push monitor's token is writable state like any other field, and it
        # is here for the failure it prevents rather than for completeness: a
        # token rotated in the Kuma UI leaves a monitor whose endpoint no longer
        # matches the one its sender posts to. Absent from this set that reads
        # as converged, and a dead-man's-switch that is silently deaf is worse
        # than none — it reports UP forever, having stopped listening.
        #
        # The VALUE never travels in the seed; `hydrate_push_tokens` injects it
        # from the secret store just before the diff. See its docstring.
        "pushToken",
    }
)

# Seed field names that the API expects under a different name.
SEED_TO_API_FIELD = {"retry_interval": "retryInterval"}

#: Uptime Kuma's `push` monitor type. Its endpoint is `/api/push/<pushToken>`,
#: so the token is not a setting on the monitor — it IS the monitor's address
#: and its only authentication. Named here rather than spelled inline because
#: three call sites branch on it.
PUSH_MONITOR_TYPE = "push"


class PushTokenError(Exception):
    """A push monitor's token is missing from the secret store, or inline in the seed."""


def hydrate_push_tokens(seed: list[dict[str, Any]], tokens: Mapping[str, str]) -> list[dict[str, Any]]:
    """Return `seed` with each push monitor's `pushToken` injected from the secret store.

    **The seed file is not the source of truth for this one field, and must never
    become it.** `monitors.json` is committed to a public repository, and the
    push endpoint is publicly routed — a token in that file is a live credential
    that lets anyone post "still alive" to the very monitor whose purpose is to
    notice silence. So the token lives in SOPS, keyed by the monitor's immutable
    `key`, and is married to the seed here, in memory, at apply time.

    That is also why `pushToken` is deliberately absent from
    `monitoring._MONITOR_EXPORT_FIELDS`: export strips it, which looks like a
    round-trip losing data and is in fact the invariant holding. Nothing is lost,
    because the JSON was never where the value lived.

    Fails closed, in both directions and loudly:

    - A push entry whose token is missing raises rather than proceeding. The
      alternative is worse than an error — `uptime_kuma_api` mints a random
      token for a tokenless push monitor, so a silent fallback would create a
      working-looking monitor at an address no sender knows, i.e. a watchdog
      that alerts forever and a heartbeat that arrives nowhere.
    - A push entry that carries an inline `pushToken` raises too. That is the
      leak this design exists to prevent, and it can only arrive by someone
      hand-editing the seed, so it is a mistake worth naming rather than
      quietly honouring.

    Pure, and takes the resolved tokens rather than reading SOPS itself, so the
    decision half stays testable without secrets — the same split the rest of
    this module is built on.
    """
    hydrated: list[dict[str, Any]] = []
    inline: list[str] = []
    unresolved: list[str] = []

    for entry in seed:
        if entry.get("type") != PUSH_MONITOR_TYPE:
            hydrated.append(entry)
            continue

        key = entry.get("key")
        label = f"{entry.get('name') or '<unnamed>'} (key={key!r})"

        if entry.get("pushToken"):
            inline.append(label)
            continue

        token = tokens.get(key) if key else None
        if not token:
            unresolved.append(label)
            continue

        hydrated.append({**entry, "pushToken": token})

    if inline:
        raise PushTokenError(
            "push monitor(s) carry an inline pushToken in the seed: "
            + ", ".join(inline)
            + ". The seed is committed to a public repository and the push endpoint is "
            "publicly routed, so the token belongs in SOPS under "
            "apps.services.observability.uptime_kuma.push_tokens.<key>, never here. "
            "Remove the field from monitors.json and store the value with: "
            "toolkit secrets set apps.services.observability.uptime_kuma.push_tokens.<key> "
            "<token> --env common"
        )
    if unresolved:
        raise PushTokenError(
            "no push token in SOPS for: "
            + ", ".join(unresolved)
            + ". Refusing to sync — Uptime Kuma would mint a random token, producing a "
            "monitor whose endpoint no sender knows. Store one with: "
            "toolkit secrets set apps.services.observability.uptime_kuma.push_tokens.<key> "
            "<token> --env common"
        )
    return hydrated


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

    Both sides go through this, restricted to the same set — an asymmetric
    projection is what made every monitor look permanently dirty.
    """
    out = {k: v for k, v in monitor.items() if k in WRITABLE_FIELDS}
    # The marker is an implementation detail of identity, not a user-visible
    # difference — compare the human text so a stamped monitor is not seen as
    # permanently drifted from its own seed entry.
    if "description" in out:
        out["description"] = strip_key(out["description"])
    return out


def _normalize_notif_ids(value: Any) -> frozenset[str]:
    """Reduce a notificationIDList to a comparable set of ids, whatever shape it's in.

    Live reads (`get_monitor`, `get_monitors`) return a plain list of ints —
    verified directly against a v2 instance, and consistent with what the
    current seed already carries (an artifact of an earlier `monitoring-export`
    run). The write path takes a `{"1": True}`-shaped dict instead, so a
    `_params()`-built payload could in principle end up compared too — handle
    both rather than assume only the read shape ever reaches this function.
    """
    if isinstance(value, dict):
        return frozenset(str(k) for k, v in value.items() if v)
    if isinstance(value, list):
        return frozenset(str(v) for v in value)
    return frozenset()


def wants_notifications(seed_entry: dict[str, Any], muted_tags: frozenset[str]) -> bool:
    """Whether the apply path should attach the default notification(s) to this entry.

    True unless the entry carries a muted tag. Whether there is a default
    notification to attach *at all* is a separate question — callers gate the
    whole comparison on `has_default_notification` before consulting this.
    """
    tags = set(seed_entry.get("tags") or [])
    return not (tags & muted_tags)


def _needs_edit(
    seed_entry: dict[str, Any],
    live_monitor: dict[str, Any],
    muted_tags: frozenset[str] = frozenset(),
    has_default_notification: bool = True,
) -> bool:
    """True when the live monitor does not already match its seed entry.

    Only fields the seed actually declares are compared. The live monitor carries
    dozens of Uptime Kuma defaults the seed never mentions, and treating those as
    differences would mark every monitor dirty on every run — the no-op case is
    the one that matters most here.

    Notification presence is compared at the boolean level ("has at least one
    id" vs. "has none"), not by exact id set — the apply path always attaches
    every default notification or none, so that is the only distinction that
    can ever actually be true or false in this seed's model (#912).

    Skipped entirely when `has_default_notification` is False, rather than
    comparing against "wants none": an instance with no default notification
    configured (a from-scratch install, OBS-014) has nothing to converge
    *toward*. Treating "nothing to attach" as "seed wants nothing" would flag
    every monitor with any live notification as dirty and, on the next apply,
    write an empty `notificationIDList` — wiping real links on any instance
    whose default notification happens not to carry `isDefault: true`. Skipping
    is fail-safe; converging to zero is fail-destructive on an unattended path.
    """
    if has_default_notification:
        live_has_notifications = bool(_normalize_notif_ids(live_monitor.get("notificationIDList")))
        if live_has_notifications != wants_notifications(seed_entry, muted_tags):
            return True

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
    # A `None` in the seed is skipped by the apply path rather than written, so it
    # cannot be reconciled either. 11 seed entries carry `httpBodyEncoding: null`
    # against a live `'json'`, which is Uptime Kuma's own default.
    return any(current.get(field) != value for field, value in desired.items() if value is not None)


def diff_monitors(
    seed: list[dict[str, Any]],
    live: list[dict[str, Any]],
    *,
    muted_tags: frozenset[str],
    has_default_notification: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (to_create, to_edit, to_delete) for a declarative sync.

    - `to_create` — seed entries with no counterpart on the instance.
    - `to_edit` — live monitors that matched a seed entry and differ from it. Each
      carries the live `id` plus the seed fields to apply, under `_seed`.
    - `to_delete` — live monitors matching no seed entry. The seed is the source
      of truth, so an unmatched monitor is one the seed dropped.

    A live monitor is claimed at most once, so two seed entries sharing a name
    cannot both adopt it — the second is created instead.

    `muted_tags` and `has_default_notification` are required and keyword-only
    on purpose: both directions of a default would be wrong for some caller
    (see `_needs_edit`), so there is no safe implicit value — the caller must
    thread live truth in explicitly instead of inheriting a guess.
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
        if _needs_edit(entry, match, muted_tags, has_default_notification):
            to_edit.append({**match, "_seed": entry})

    to_delete = [m for m in live if m["id"] not in claimed]
    return to_create, to_edit, to_delete
