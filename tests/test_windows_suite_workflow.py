"""The Windows suite workflow (#3409)."""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/windows-suite.yml"


def test_nothing_but_another_audit_cancels_an_audit_on_the_same_ref() -> None:
    """An audit, a plain dispatch and a push to master share a ref. Unless the key
    names both the event and the audit flag, either of the others cancels the
    audit, which then reports no results at all."""
    group = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["concurrency"]["group"]
    assert "github.event_name" in group
    assert "inputs.audit" in group
