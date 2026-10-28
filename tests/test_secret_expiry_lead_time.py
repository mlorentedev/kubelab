"""Each credential is red inside its own lead time, not a fleet-wide 90 days (TOOL-126, #2744).

A 60-day token judged against a 90-day window is red from the day it is issued,
and a column that is always red is a column nobody reads.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from toolkit.cli import secrets as cli
from toolkit.features import secret_expiry
from toolkit.features.secret_expiry import DeclaredExpiry, Expiry, resolve_expiry
from toolkit.features.secrets_manager import SECRET_CATALOG, SecretKind, SecretSpec

_ROOT = Path(__file__).resolve().parents[1]
_OWN_LEAD = "apps.services.automation.dev_node.github_token"  # warn_days=14
_DEFAULT_LEAD = "apps.services.automation.github_runner.token"  # no warn_days


def _provider_reports(monkeypatch: pytest.MonkeyPatch, key: str, days_left: int) -> MagicMock:
    """Only `key` has a value, and its issuer answers `days_left` days from now."""
    monkeypatch.setattr(cli, "_provider_value_lookup", lambda: lambda k: "v" if k == key else None)
    expires = datetime.now(timezone.utc) + timedelta(days=days_left, hours=1)
    monkeypatch.setitem(secret_expiry.PROVIDER_CHECKS, key, lambda _value: expires)
    monkeypatch.setattr(cli, "_declared_expiry_lines", lambda warn_days: ([], []))
    log = MagicMock()
    monkeypatch.setattr(cli, "logger", log)
    return log


def _named(calls: list, key: str) -> bool:
    return any(key in str(c) for c in calls)


@pytest.mark.parametrize(("days_left", "red"), [(60, False), (10, True)])
def test_the_audit_judges_a_credential_by_its_own_lead_time(monkeypatch, days_left, red) -> None:
    log = _provider_reports(monkeypatch, _OWN_LEAD, days_left)
    cli._report_expiry(warn_days=90)
    assert _named(log.error.call_args_list, _OWN_LEAD) is red
    assert _named(log.info.call_args_list, _OWN_LEAD) is not red


def test_a_credential_without_one_keeps_the_default(monkeypatch) -> None:
    log = _provider_reports(monkeypatch, _DEFAULT_LEAD, 60)
    cli._report_expiry(warn_days=90)
    assert _named(log.error.call_args_list, _DEFAULT_LEAD)


@pytest.mark.parametrize(("days_left", "exit_code"), [(60, 0), (10, 1)])
def test_check_expiry_judges_a_credential_by_its_own_lead_time(monkeypatch, days_left, exit_code) -> None:
    _provider_reports(monkeypatch, _OWN_LEAD, days_left)
    monkeypatch.setattr(secret_expiry, "headscale_apikeys", lambda _target: [])
    result = CliRunner().invoke(cli.app, ["check-expiry", "--ssh", "nobody@nowhere"])
    assert result.exit_code == exit_code, result.output


@pytest.mark.parametrize(("days_left", "red"), [(30, False), (10, True)])
def test_a_declared_date_is_judged_by_the_same_lead_time(monkeypatch, days_left, red) -> None:
    item = DeclaredExpiry(_OWN_LEAD, "staging", date.today() + timedelta(days=days_left))
    monkeypatch.setattr(secret_expiry, "declared_expiries", lambda specs, config: [item])
    monkeypatch.setattr(cli, "logger", MagicMock())
    _missing, expiring = cli._declared_expiry_lines(warn_days=90)
    assert bool(expiring) is red


def test_a_lead_time_is_a_positive_number_of_days() -> None:
    with pytest.raises(ValueError, match="warn_days"):
        SecretSpec(key_path="x.token", description="d", kind=SecretKind.EXTERNAL, warn_days=0)


# A life stated in days: "60d expiry", "a 60-day life", "**Expiry:** 60 or 90 days".
_DAYS = re.compile(r"\b(\d{1,3})(?:d\b|-day\b| days?\b)")
_LIFE_WORDS = re.compile(r"expir|life|ttl", re.IGNORECASE)


def _stated_lives(spec: SecretSpec) -> list[int]:
    """Lives stated where the catalog entry points: its hint, its rotate note, and runbooks the note names."""
    lines = [spec.format_hint, spec.rotate_note]
    for runbook in re.findall(r"docs/runbooks/[\w.-]+\.md", spec.rotate_note):
        lines += (_ROOT / runbook).read_text().splitlines()
    return [int(n) for line in lines if _LIFE_WORDS.search(line) for n in _DAYS.findall(line)]


_REPORTED = [s for s in SECRET_CATALOG if resolve_expiry(s) in (Expiry.PROVIDER, Expiry.DECLARED)]


@pytest.mark.parametrize("spec", _REPORTED, ids=lambda s: s.key_path)
def test_a_short_lived_credential_declares_a_lead_time_inside_its_life(spec: SecretSpec) -> None:
    lives = [n for n in _stated_lives(spec) if n <= 90]
    if not lives:
        return
    assert spec.warn_days is not None and spec.warn_days < min(lives), (
        f"{spec.key_path} states a life of {min(lives)} days, so the default 90-day window "
        "is red for all of it: set warn_days below that life"
    )


def test_both_measured_credentials_state_their_life() -> None:
    """The two that were red on 2026-10-27; without a stated life the test above would skip them."""
    for key in (_OWN_LEAD, "cloudflare.r2_token_minter"):
        spec = next(s for s in SECRET_CATALOG if s.key_path == key)
        assert any(n <= 90 for n in _stated_lives(spec)), key
