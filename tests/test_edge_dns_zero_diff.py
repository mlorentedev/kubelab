"""The staging-zone consumers render exactly what master rendered before EDGE-001.

`tests/fixtures/edge_dns/` holds the Corefile, the Pi-hole forwarding file, the
Headscale split DNS and the pod-side hairpin as master rendered them on
2026-11-13 from the hand list, when `staging.imagesensortool.com` had been
applied by hand. Each consumer is rendered here from its own declaration, now a
lookup of `edge.json`, with that file standing in as a manifest frozen at the
same three zones. Byte equality proves the switch of source moved nothing that is
live on the RPi4, the VPS or the clusters, so an operator's `CHECK=1` has nothing
to report.

The frozen manifest keeps this independent of the registry: onboarding a product
changes the committed `edge.json`, never these fixtures, so no product needs a
hand edit here. `test_edge_dns.py` holds the committed manifest to the derivation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from tests import edge_dns_render as render

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "edge_dns"
FROZEN_ZONES = ["staging.kubelab.live", "staging.mlorente.dev", "staging.imagesensortool.com"]


@pytest.fixture
def manifest(tmp_path: Path) -> Path:
    path = tmp_path / "edge.json"
    path.write_text(json.dumps({"staging_zones": FROZEN_ZONES}), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("fixture", "rendered"),
    [
        ("Corefile", render.rendered_corefile),
        ("pihole-forwarding.conf", render.rendered_pihole_forwarding),
    ],
)
def test_the_rendered_file_is_byte_identical_to_the_golden_copy(fixture: str, rendered, manifest: Path) -> None:
    assert rendered(manifest) == (FIXTURES / fixture).read_text(encoding="utf-8")


def test_the_hairpin_configmap_data_is_identical_to_the_golden_copy(manifest: Path) -> None:
    """Compared as the object the cluster stores: a manifest's comments never reach it."""
    golden = yaml.safe_load((FIXTURES / "coredns-custom.yaml").read_text(encoding="utf-8"))
    assert yaml.safe_load(render.rendered_hairpin(manifest)) == golden


def test_headscale_split_dns_is_identical_to_the_golden_copy(manifest: Path) -> None:
    golden = json.loads((FIXTURES / "headscale-split.json").read_text(encoding="utf-8"))
    split = render.headscale_split(manifest)
    # Order matters too: config.yaml.j2 renders the map in insertion order.
    assert list(split.items()) == list(golden.items())


@pytest.mark.parametrize(
    "rendered",
    [render.rendered_corefile, render.rendered_pihole_forwarding, render.rendered_hairpin, render.headscale_split],
)
def test_every_consumer_follows_the_manifest(rendered, tmp_path: Path) -> None:
    """A zone in the manifest reaches every consumer: none of them reads a list of its own."""
    path = tmp_path / "edge.json"
    path.write_text(json.dumps({"staging_zones": [*FROZEN_ZONES, "staging.example-product.test"]}), encoding="utf-8")

    assert "staging.example-product.test" in str(rendered(path))


def test_the_golden_copies_name_every_staging_zone() -> None:
    """Guard against a golden copy that compares nothing: each fixture names imagesensortool's zone."""
    for name in ("Corefile", "pihole-forwarding.conf", "coredns-custom.yaml", "headscale-split.json"):
        assert "staging.imagesensortool.com" in (FIXTURES / name).read_text(encoding="utf-8"), name
