"""The staging-zone consumers render exactly what master rendered before EDGE-001.

`tests/fixtures/edge_dns/` holds the Corefile, the Pi-hole forwarding file, the
Headscale split DNS and the pod-side hairpin as master rendered them on
2026-11-13, when `staging.imagesensortool.com` had been applied by hand. The
derived manifest must reproduce them byte for byte: those files are what is live
on the RPi4, the VPS and the clusters, so any difference here is a change an
operator's `CHECK=1` would report, and the derivation promised none.

When a product is onboarded the zones change on purpose: regenerate the fixtures
in the same PR, so the diff shows the reviewer what the edge will receive.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests import edge_dns_render as render

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "edge_dns"


@pytest.mark.parametrize(
    ("fixture", "rendered"),
    [
        ("Corefile", render.rendered_corefile),
        ("pihole-forwarding.conf", render.rendered_pihole_forwarding),
        ("coredns-custom.yaml", render.rendered_hairpin),
    ],
)
def test_the_rendered_file_is_byte_identical_to_the_golden_copy(fixture: str, rendered) -> None:
    assert rendered() == (FIXTURES / fixture).read_text(encoding="utf-8")


def test_headscale_split_dns_is_identical_to_the_golden_copy() -> None:
    golden = json.loads((FIXTURES / "headscale-split.json").read_text(encoding="utf-8"))
    split = render.headscale_split()
    # Order matters too: config.yaml.j2 renders the map in insertion order.
    assert list(split.items()) == list(golden.items())


def test_the_golden_copies_name_every_staging_zone() -> None:
    """Guard against a golden copy that compares nothing: each fixture names imagesensortool's zone."""
    for name in ("Corefile", "pihole-forwarding.conf", "coredns-custom.yaml", "headscale-split.json"):
        assert "staging.imagesensortool.com" in (FIXTURES / name).read_text(encoding="utf-8"), name
