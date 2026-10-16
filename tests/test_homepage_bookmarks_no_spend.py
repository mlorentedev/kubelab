"""#1847 (TOOL-083): no homepage bookmark label carries a hand-typed spend.

The Ops bookmarks read `Hetzner (~9€/mo)`, `GCP Hub (~$6/mo)` and `AWS (~$4/mo)`.
On 2026-09-25 the list prices were 15.59 USD, about 9.51 USD and 0.00 USD, in two
currencies between them. A figure typed into a label has no date and no source,
so it drifts silently; the billing console the bookmark opens is the measurement.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

BOOKMARKS = Path(__file__).resolve().parents[1] / "infra/k8s/base/services/homepage-config/bookmarks.yaml"
SPEND = re.compile(r"[€$£]|\b(?:USD|EUR)\b|/\s*mo(?:nth)?\b|\b(?:monthly|per\s+month)\b", re.I)


def _labels() -> list[str]:
    groups = yaml.safe_load(BOOKMARKS.read_text(encoding="utf-8"))
    return [label for group in groups for entries in group.values() for entry in entries for label in entry]


def test_no_bookmark_label_carries_a_spend() -> None:
    labels = _labels()
    assert len(labels) > 10, "too few labels parsed for this check to mean anything"
    assert not [label for label in labels if SPEND.search(label)]


@pytest.mark.parametrize(
    "label",
    [
        "Hetzner (~9€/mo)",
        "GCP Hub (~$6/mo)",
        "VPS (9 USD)",
        "R2 (9/month)",
        "Box (9 / mo)",
        "S3 (9 monthly)",
        "B2 (9 per month)",
    ],
)
def test_the_pattern_catches_each_spelling_of_a_spend(label: str) -> None:
    assert SPEND.search(label), label


@pytest.mark.parametrize("label", ["Grafana", "Monitoring", "Argo CD", "Uptime Kuma"])
def test_the_pattern_leaves_a_plain_label_alone(label: str) -> None:
    assert not SPEND.search(label), label
