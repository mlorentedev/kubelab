"""Unit tests for the backup source allow-list and its topology axis — BACKUP-044.

Pure SSOT assertions: NO SSH, no live node, no restic. Runs under ``make test``
(marker-less → collected by ``-m "not e2e and not infra"``).

Why these tests exist, and what they deliberately do NOT cover:

``roles/backup`` enumerates every Docker volume and subtracts an exclude list.
Measuring the fleet for #449 showed why that model cannot work: on the Beelink,
Gitea is a **bind mount** (``/opt/gitea/data``) and so is MinIO, while
``docker volume ls`` returns only buildx caches and the runner toolcache. Pointed
at that node, an exclude-list backup archives rebuildable junk, misses both
services entirely, and reports success. #1092's AC3 inverts the model to an
allow-list, and this file encodes the declaration side of it.

**What lives here today** is only the topology axis the allow-list will derive
its trigger model from. The ``backup.sources`` block itself is deliberately NOT
here yet: the Beelink and RPi3 paths are measured, but the VPS's Headscale
database turned out to live inside the ``headscale_headscale_data`` volume rather
than under ``/opt``, and no ``pihole-FTL.db`` was found on the RPi4 at all.
Declaring guessed paths for a backup is worse than declaring none, so those two
nodes are measured first and the allow-list lands with them.

**The half that will never live here** is the one that actually catches an
omission: a stateful path that exists *on disk* on a covered node and is absent
from the SSOT. That needs a live node, so it belongs in ``tests/infra/`` behind
``require_vpn``. AC6 is not satisfied by this file, or by the allow-list alone —
an allow-list that only validates what it declares cannot report what it forgot,
which is the precise failure this spec documents.

The contract encoded here:

- **Every host in the node registry declares ``location``**, an enum, not a
  boolean. ADR-028 splits the fleet into always-on and on-demand, and until now
  that split lived only in prose. It cannot be inferred: `rpi3` sits in the
  homelab block (``networking.nodes``) yet is always-on, so the position-based
  category trick SSOT-014a uses for SSH users (vps+aws → cloud, nodes → homelab)
  cannot express this axis. A boolean would invite a silent default; an enum
  plus a completeness assertion makes an unclassified node go red. Same failure
  direction as the allow-list itself: absence is reported, never assumed.
- **The trigger model derives from ``location``**, so it is asserted here rather
  than redeclared inside the backup block. ADR-061 already reclassified a node
  once; a second SSOT would have to be remembered separately, and the miss is
  silent — a node promoted to always-on would keep uptime-bounded triggers and
  nothing would say so.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

COMMON_YAML = Path(__file__).parent.parent / "infra" / "config" / "values" / "common.yaml"

# ADR-028's two tiers. Anything else is a typo, and a typo that silently selects
# the wrong trigger model is exactly what an enum exists to prevent.
VALID_LOCATIONS = {"always-on", "on-demand"}

# ADR-028's own topology block, as data. `rpi3` is the entry that breaks
# inference: homelab hardware, always-on duty as prod's monitoring of record.
# A test below asserts this covers the registry exactly, so a host added without
# a classification here goes red instead of passing unverified.
ADR_028_TIERS = {
    "vps": "always-on",
    "aws": "always-on",
    "rpi3": "always-on",
    "ace1": "on-demand",
    "ace2": "on-demand",
    "rpi4": "on-demand",
    "beelink": "on-demand",
    "jetson": "on-demand",
}


@pytest.fixture(scope="module")
def common() -> dict[str, Any]:
    return yaml.safe_load(COMMON_YAML.read_text())


@pytest.fixture(scope="module")
def hosts(common: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every host in the registry, flattened.

    `vps` and `aws` are siblings of `nodes` rather than members of it, which is
    the same shape SSOT-014a's SSH-user inference keys off. Flattening here means
    a new cloud host cannot escape the completeness assertion by virtue of living
    outside `networking.nodes`.
    """
    net = common["networking"]
    flat: dict[str, dict[str, Any]] = dict(net["nodes"])
    for key in ("vps", "aws"):
        if key in net:
            flat[key] = net[key]
    return flat


class TestLocationAxis:
    """ADR-028's always-on/on-demand split, as machine-readable config."""

    def test_every_host_declares_a_location(self, hosts: dict[str, dict[str, Any]]) -> None:
        missing = sorted(name for name, cfg in hosts.items() if "location" not in cfg)
        assert not missing, (
            f"hosts with no `location` in the node registry: {missing}. "
            "ADR-028 classifies every node as always-on or on-demand; a host that "
            "does not declare it has no derivable backup trigger model, and "
            "defaulting one would be a guess about whether the node is ever off."
        )

    def test_locations_are_valid_enum_values(self, hosts: dict[str, dict[str, Any]]) -> None:
        bad = {n: c["location"] for n, c in hosts.items() if c.get("location") not in VALID_LOCATIONS}
        assert not bad, f"invalid `location` values (expected one of {sorted(VALID_LOCATIONS)}): {bad}"

    def test_the_expected_list_covers_every_host(self, hosts: dict[str, dict[str, Any]]) -> None:
        """The parametrised list below must not silently stop covering the fleet.

        Without this, a host added to the registry with a valid `location` passes
        every other test in this file while its classification goes unverified —
        the same absence-is-not-reported failure this file exists to prevent, left
        in the file's own scaffolding. Raised by review on #1107.
        """
        registry, expected = set(hosts), set(ADR_028_TIERS)
        assert registry == expected, (
            f"hosts in the registry but not classified below: {sorted(registry - expected)}; "
            f"classified below but absent from the registry: {sorted(expected - registry)}. "
            "Adding a host means classifying it here too, so its tier is asserted against "
            "ADR-028 rather than merely being a syntactically valid string."
        )

    @pytest.mark.parametrize(("host", "expected"), sorted(ADR_028_TIERS.items()))
    def test_location_matches_adr_028(self, hosts: dict[str, dict[str, Any]], host: str, expected: str) -> None:
        assert hosts[host].get("location") == expected, (
            f"{host} is classified {hosts[host].get('location')!r} but ADR-028 says {expected!r}. "
            "If the topology genuinely changed, amend ADR-028 and this list together — "
            "ADR-061 already reclassified a node once, and the point of this test is that "
            "the next one cannot happen silently."
        )
