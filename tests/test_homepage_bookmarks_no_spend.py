"""#1847 (TOOL-083): no homepage bookmark label carries a hand-typed spend.

The Ops bookmarks read `Hetzner (~9€/mo)`, `GCP Hub (~$6/mo)` and `AWS (~$4/mo)`.
On 2026-09-25 the list prices were 15.59 USD, about 9.51 USD and 0.00 USD, in two
currencies between them. A figure typed into a label has no date and no source,
so it drifts silently; the billing console the bookmark opens is the measurement.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

BOOKMARKS = Path(__file__).resolve().parents[1] / "infra/k8s/base/services/homepage-config/bookmarks.yaml"
SPEND = re.compile(r"[€$£]|\b(?:USD|EUR)\b|/\s*mo\b", re.I)


def _labels() -> list[str]:
    groups = yaml.safe_load(BOOKMARKS.read_text(encoding="utf-8"))
    return [label for group in groups for entries in group.values() for entry in entries for label in entry]


def test_no_bookmark_label_carries_a_spend() -> None:
    labels = _labels()
    assert len(labels) > 10, "too few labels parsed for this check to mean anything"
    assert not [label for label in labels if SPEND.search(label)]
