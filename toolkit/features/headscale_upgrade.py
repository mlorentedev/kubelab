"""Decide whether the Headscale v0.28 -> v0.29 upgrade may start (VPN-ACL-006, AC1).

The preflight is a pure function of the facts it is handed: the running and
candidate image references, the registry's platform list per digest, the node
records Headscale reports and the client version of every node the upgrade must
not lose. It runs no command and opens no connection, so nothing can be mutated
before it refuses. Collecting those facts read-only is the caller's job.

It reports every refusal at once, each with a stable code, rather than stopping
at the first: the operator fixes the whole list in one pass.

Why each check exists (upstream release notes, v0.29.0-v0.29.6):
- `client-version`: v0.29 supports Tailscale >= 1.80.0, and v0.29.3 rejects
  `/key` below that floor, so an old client is cut off rather than degraded.
  An unknown version is refused too: a bridge's release number is not the
  version of the Tailscale it embeds.
- `transition`: upgrades must go one minor at a time, a minor downgrade is
  blocked, and v0.29.0 drops the user of nodes stored with `tags='null'`
  (fixed in v0.29.1).
- `image-unverified`: a tag is mutable, and the VPS is ARM, so the pin must be a
  digest the registry lists with a linux/arm64 image.
- `expired-online`: v0.29.4 ends the map session of an expired node, so a node
  that is online today on an expired key goes offline at upgrade.
- `random-suffix`: v0.29.0 renames name collisions with a numeric suffix
  (`laptop-1`) instead of eight random characters, so `gcp1-mj5bsge9` changes
  its MagicDNS name at upgrade.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

MIN_CLIENT_VERSION = (1, 80, 0)
KNOWN_BAD_TARGETS = frozenset({(0, 29, 0)})
# Go's zero time.Time, which versions before v0.29 stored for a node that never expires.
GO_ZERO_TIME = datetime(1, 1, 1, tzinfo=timezone.utc)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_CLIENT = re.compile(r"^(\d+)\.(\d+)\.(\d+)")
_RANDOM_SUFFIX = re.compile(r"^[a-z0-9]{8}$")


@dataclass(frozen=True)
class NodeState:
    hostname: str
    given_name: str
    online: bool
    expiry: datetime | None


@dataclass(frozen=True)
class Facts:
    current_image: str
    target_image: str
    registry_index: Mapping[str, Collection[str]]
    nodes: Sequence[NodeState]
    required: Mapping[str, str | None]
    approved: bool


@dataclass(frozen=True)
class Refusal:
    code: str
    detail: str


@dataclass(frozen=True)
class Verdict:
    refusals: tuple[Refusal, ...]

    @property
    def eligible(self) -> bool:
        return not self.refusals


def _expiry(raw: object) -> datetime | None:
    """When the node key expires, or None if it never does.

    Absent and Go's zero time are the only two ways to say never. A Timestamp
    arrives as an object whose `seconds` is a number (encoding/json) or a string
    (protojson), or as an RFC 3339 string. Any other moment is real, even one
    before 1970, and any other shape raises: reading it as "never" would pass an
    expired node silently.
    """
    if raw is None:
        return None
    try:
        if isinstance(raw, dict) and "seconds" in raw:
            moment = _EPOCH + timedelta(seconds=int(raw["seconds"]))
        elif isinstance(raw, str):
            moment = datetime.fromisoformat(raw)
            if moment.tzinfo is None:
                raise ValueError("no UTC offset")
        else:
            raise ValueError("unknown shape")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"unreadable node expiry: {raw!r}") from exc
    return None if moment == GO_ZERO_TIME else moment


def parse_node_states(payload: str) -> list[NodeState]:
    """`headscale nodes list --output json`. An absent `online` means offline (proto3 omits false).

    Raises ValueError on an expiry it cannot read, rather than treating the node as never expiring.
    """
    return [
        NodeState(
            hostname=entry.get("name", ""),
            given_name=entry.get("given_name", ""),
            online=bool(entry.get("online", False)),
            expiry=_expiry(entry.get("expiry")),
        )
        for entry in json.loads(payload)
    ]


def _image(reference: str) -> tuple[tuple[int, int, int] | None, str | None]:
    name, _, digest = reference.partition("@")
    match = _TAG.match(name.rpartition(":")[2])
    version = (int(match[1]), int(match[2]), int(match[3])) if match else None
    return version, digest or None


def _transition(facts: Facts) -> list[Refusal]:
    current, _ = _image(facts.current_image)
    target, _ = _image(facts.target_image)
    if current is None or target is None:
        return [Refusal("transition", f"{facts.current_image} -> {facts.target_image}: both need a vX.Y.Z tag")]
    adjacent = target[0] == current[0] and target[1] == current[1] + 1
    if not adjacent or target in KNOWN_BAD_TARGETS:
        return [Refusal("transition", f"{facts.current_image} -> {facts.target_image} is not a supported upgrade")]
    return []


def _pin(facts: Facts) -> list[Refusal]:
    _, digest = _image(facts.target_image)
    if digest is None or not _DIGEST.match(digest):
        return [Refusal("image-unverified", f"{facts.target_image} is not pinned by a sha256 digest")]
    platforms = facts.registry_index.get(digest)
    if platforms is None:
        return [Refusal("image-unverified", f"the registry does not list {digest}")]
    if not any(p == "linux/arm64" or p.startswith("linux/arm64/") for p in platforms):
        return [Refusal("image-unverified", f"{digest} has no linux/arm64 image")]
    return []


def _client(hostname: str, version: str | None) -> list[Refusal]:
    match = _CLIENT.match(version or "")
    if match is None:
        return [Refusal("client-version", f"{hostname}: client version unknown ({version!r})")]
    if (int(match[1]), int(match[2]), int(match[3])) < MIN_CLIENT_VERSION:
        return [Refusal("client-version", f"{hostname}: Tailscale {version} is below 1.80.0")]
    return []


def _node(hostname: str, nodes: Sequence[NodeState], now: datetime) -> list[Refusal]:
    records = [n for n in nodes if n.hostname == hostname]
    if not records:
        return [Refusal("node-missing", f"{hostname}: Headscale has no node with this hostname")]
    refusals = []
    for record in records:
        if record.online and record.expiry is not None and record.expiry <= now:
            refusals.append(Refusal("expired-online", f"{record.given_name}: online on a key that expired"))
        prefix = f"{hostname.lower()}-"
        if record.given_name.startswith(prefix) and _RANDOM_SUFFIX.match(record.given_name[len(prefix) :]):
            refusals.append(Refusal("random-suffix", f"{record.given_name}: reclaim the name {hostname} first"))
    return refusals


def evaluate(facts: Facts, now: datetime | None = None) -> Verdict:
    now = now or datetime.now(timezone.utc)
    refusals = [*_transition(facts), *_pin(facts)]
    for hostname, version in sorted(facts.required.items()):
        refusals += _client(hostname, version) + _node(hostname, facts.nodes, now)
    if not facts.approved:
        refusals.append(Refusal("approval", "no production approval was given for this upgrade"))
    return Verdict(tuple(refusals))
