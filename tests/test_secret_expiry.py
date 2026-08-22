"""Provider-issued credentials must have a known expiry, asked not remembered.

`SECRET_CATALOG` recorded how to rotate every secret and nothing about when any
of them stops working. Rotation is a procedure someone follows on purpose;
expiry is a date that arrives whether or not anyone is looking.

Measured 2026-08-22: `aws.headscale_api_key` expires 2027-03-27, and nothing in
this repository knew -- it was not even IN the catalog, though aws1's cloud-init
reads it on every Spot replacement. An expired key fails silently: the
replacement cannot clear its stale Headscale node, registers as `aws1-<random>`,
and breaks the inventory and the kubeconfig months after anyone touched a key.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from toolkit.features.secret_expiry import (
    Expiry,
    ExpiryUnavailableError,
    headscale_apikeys,
    parse_headscale_apikeys,
)
from toolkit.features.secrets_manager import SECRET_CATALOG

# Real output, ANSI included, copied from the VPS. A hand-cleaned sample would
# test a format headscale does not emit.
REAL_OUTPUT = (
    "\x1b[96m\x1b[96mID\x1b[90m\x1b[90m | \x1b[0m\x1b[96m\x1b[0m\x1b[96mPrefix"
    "                    \x1b[90m\x1b[90m | \x1b[0m\x1b[96m\x1b[0m\x1b[96mExpiration"
    "         \x1b[90m\x1b[90m | \x1b[0m\x1b[96m\x1b[0m\x1b[96mCreated            \x1b[0m\n"
    "\x1b[96m\x1b[0m\x1b[0m1 \x1b[90m\x1b[90m | \x1b[0mhskey-api-j4_9sZt5zTPr-***\x1b[90m\x1b[90m | "
    "\x1b[0m\x1b[92m2027-03-27 04:33:43\x1b[0m\x1b[90m\x1b[90m | \x1b[0m2026-03-27 04:33:43\n"
    "2 \x1b[90m\x1b[90m | \x1b[0mhskey-api-zcJQKhYGg5SW-***\x1b[90m\x1b[90m | "
    "\x1b[0m\x1b[92m2029-05-17 02:55:43\x1b[0m\x1b[90m\x1b[90m | \x1b[0m2026-08-22 02:55:43\n"
)


class TestParsingWhatHeadscaleActuallyPrints:
    def test_both_keys_are_found(self) -> None:
        assert len(parse_headscale_apikeys(REAL_OUTPUT)) == 2

    def test_the_expiry_dates_are_read(self) -> None:
        keys = parse_headscale_apikeys(REAL_OUTPUT)
        assert {k.expires_at.date().isoformat() for k in keys} == {"2027-03-27", "2029-05-17"}

    def test_the_header_row_is_not_mistaken_for_a_key(self) -> None:
        """It contains the word 'Expiration' and no date; a looser pattern would
        yield a third 'key' with an unparseable lifetime."""
        assert all(k.prefix.startswith("hskey-api-") for k in parse_headscale_apikeys(REAL_OUTPUT))

    def test_only_the_truncated_prefix_is_captured(self) -> None:
        """headscale truncates the prefix itself. Nothing usable as a credential
        can reach a log, a CI transcript or a terminal through this path."""
        for key in parse_headscale_apikeys(REAL_OUTPUT):
            assert key.prefix.endswith("-***")

    def test_days_left_is_derived_not_stored(self) -> None:
        keys = parse_headscale_apikeys(REAL_OUTPUT)
        soonest = min(keys, key=lambda k: k.expires_at)
        expected = (soonest.expires_at - datetime.now(timezone.utc)).days
        assert soonest.days_left == expected


class TestAnUnaskableServiceIsNotAnEmptyOne:
    def test_ssh_failure_raises_rather_than_reporting_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A check that cannot run must never be mistaken for one that found
        nothing -- the same rule `argo check-drift` follows with exit code 2."""
        from unittest.mock import MagicMock

        import toolkit.features.secret_expiry as mod

        monkeypatch.setattr(
            mod.subprocess, "run", MagicMock(return_value=MagicMock(returncode=255, stdout="", stderr="timeout"))
        )
        with pytest.raises(ExpiryUnavailableError, match="could not ask headscale"):
            headscale_apikeys("deployer@host")

    def test_an_empty_key_list_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Every hub reads one at boot, so zero keys means the query failed."""
        from unittest.mock import MagicMock

        import toolkit.features.secret_expiry as mod

        monkeypatch.setattr(
            mod.subprocess, "run", MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
        )
        with pytest.raises(ExpiryUnavailableError, match="no API keys"):
            headscale_apikeys("deployer@host")


class TestTheCatalogKnowsWhichSecretsExpire:
    def test_the_headscale_credentials_are_provider_issued(self) -> None:
        """The three the hubs read at boot. Anything issued by a service that
        can be asked must say so, or `check-expiry` has nothing to check."""
        by_path = {s.key_path: s for s in SECRET_CATALOG}
        for path in ("aws.headscale_api_key", "aws.headscale_preauth_key", "gcp.headscale_api_key"):
            assert path in by_path, f"{path} is consumed at boot but not registered in SECRET_CATALOG"
            assert by_path[path].expiry is Expiry.PROVIDER

    def test_the_aws_hub_credentials_are_registered_at_all(self) -> None:
        """They existed in SOPS for months and in the catalog not at all, so
        `secrets-audit` never checked them. The registry that calls itself
        authoritative did not know the AWS hub had credentials."""
        assert any(s.key_path.startswith("aws.") for s in SECRET_CATALOG)

    def test_unclassified_is_the_default_not_never(self) -> None:
        """A new entry should surface as unassessed rather than be assumed
        immortal. `NEVER` has to be a decision someone made."""
        from dataclasses import fields

        default = next(f for f in fields(SECRET_CATALOG[0]) if f.name == "expiry").default
        assert default is Expiry.UNKNOWN

    def test_no_expiry_date_is_stored_in_the_catalog(self) -> None:
        """A recorded date is a second declaration that drifts the moment a key
        is re-minted -- and it drifts in the safe-looking direction, still
        saying "fine" about a key replaced with a shorter-lived one.

        `rotate_note` may MENTION a measured date as prose for a human; what
        must not exist is a field the code reads instead of asking.
        """
        from dataclasses import fields

        names = {f.name for f in fields(SECRET_CATALOG[0])}
        assert not (names & {"expires_at", "expiry_date", "valid_until", "last_rotated"}), (
            f"the catalog stores an expiry date: {names}. Ask the issuer instead."
        )


def test_a_key_inside_the_warning_window_is_detectable() -> None:
    """The property the command acts on, pinned independently of the command."""
    soon = datetime.now(timezone.utc) + timedelta(days=30)
    row = f"1 | hskey-api-x-*** | {soon:%Y-%m-%d %H:%M:%S} | 2026-01-01 00:00:00\n"
    (key,) = parse_headscale_apikeys(row)
    assert key.days_left < 90


class TestTheRuleIsEncodedNotRepeated:
    """38 catalog entries would otherwise carry `expiry=Expiry.NEVER` verbatim.

    That would be one fact declared 38 times, free to disagree with the `kind`
    sitting beside it. `resolve_expiry` states the rule instead: if this
    repository generates the value, nothing can revoke it on a schedule.
    """

    def test_a_generated_secret_cannot_expire(self) -> None:
        from toolkit.features.secret_expiry import resolve_expiry
        from toolkit.features.secrets_manager import SecretKind, SecretSpec

        spec = SecretSpec(key_path="x", description="", kind=SecretKind.RANDOM_TOKEN)
        assert resolve_expiry(spec) is Expiry.NEVER

    def test_an_unclassified_external_secret_stays_unknown(self) -> None:
        """The honest answer, and the one that shows up in a report. Defaulting
        it to NEVER would silently assume every third-party key is immortal."""
        from toolkit.features.secret_expiry import resolve_expiry
        from toolkit.features.secrets_manager import SecretKind, SecretSpec

        spec = SecretSpec(key_path="x", description="", kind=SecretKind.EXTERNAL)
        assert resolve_expiry(spec) is Expiry.UNKNOWN

    def test_an_explicit_classification_always_wins(self) -> None:
        from toolkit.features.secret_expiry import resolve_expiry
        from toolkit.features.secrets_manager import SecretKind, SecretSpec

        spec = SecretSpec(key_path="x", description="", kind=SecretKind.EXTERNAL, expiry=Expiry.PROVIDER)
        assert resolve_expiry(spec) is Expiry.PROVIDER

    def test_every_catalog_entry_is_now_classified(self) -> None:
        """The point of the exercise. An UNKNOWN here is a third-party credential
        nobody has decided about -- which is exactly how a PAT expiring in 23
        days went unnoticed."""
        from toolkit.features.secret_expiry import resolve_expiry

        unknown = [s.key_path for s in SECRET_CATALOG if resolve_expiry(s) is Expiry.UNKNOWN]
        assert not unknown, f"unclassified third-party credentials: {unknown}"


class TestEveryProviderSecretCanActuallyBeAsked:
    def test_each_PROVIDER_secret_has_a_checker_or_is_headscale(self) -> None:
        """ "We said this expires and we cannot find out when" is a finding, not a
        blank line. Headscale is the exception: its keys are enumerated from the
        server rather than looked up per catalog entry."""
        from toolkit.features.secret_expiry import PROVIDER_CHECKS, resolve_expiry

        provider = [s.key_path for s in SECRET_CATALOG if resolve_expiry(s) is Expiry.PROVIDER]
        unaskable = [p for p in provider if p not in PROVIDER_CHECKS and "headscale" not in p]
        assert not unaskable, f"declared PROVIDER with no way to ask the issuer: {unaskable}"


class TestExpiryIsPartOfTheAudit:
    """A control that reports only when someone remembers does not exist.

    `check-expiry` was its own command and nothing ran it — the same shape as
    the finding it was built to fix. `secrets audit` IS run, so the report is
    attached to that rather than left waiting to be invoked.
    """

    def test_audit_reports_expiry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import MagicMock

        from typer.testing import CliRunner

        import toolkit.cli.secrets as cli

        called = MagicMock()
        monkeypatch.setattr(cli, "_report_expiry", called)
        monkeypatch.setattr(cli, "_get_manager", MagicMock())
        result = CliRunner().invoke(cli.app, ["audit", "--env", "prod"])
        assert called.called, f"the audit did not check expiry:\n{result.stdout}"

    def test_an_unreachable_issuer_does_not_fail_the_audit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The audit's subject is which secrets are PRESENT. A network problem
        reaching GitHub must not turn that into a failure — it says so and moves
        on. A check that CAN fail loudly is the scheduled one, not this."""
        from unittest.mock import MagicMock

        from typer.testing import CliRunner

        import toolkit.cli.secrets as cli

        monkeypatch.setattr(cli, "_report_expiry", MagicMock(side_effect=RuntimeError("no network")))
        monkeypatch.setattr(cli, "_get_manager", MagicMock())
        result = CliRunner().invoke(cli.app, ["audit", "--env", "prod"])
        assert result.exit_code == 0, result.stdout
        assert "expiry not checked" in result.stdout


class TestTheSshTargetComesFromTheSSOT:
    """It defaulted to `deployer@162.55.57.175` — both halves hardcoded, both of
    them SSOT values, in a repository whose own rule reads "Never hardcode
    IPs/CIDRs in K8s manifests, tests, or toolkit code".

    Raised by review on #1247. Not cosmetic: the VPS's public IP has changed
    before, and a stale literal here means the check silently asks the wrong
    host — or nothing at all — while still reporting on the credentials it did
    manage to reach.
    """

    def test_no_ip_literal_survives_in_the_command(self) -> None:
        """Over the AST, so the comment explaining the removal cannot fail it."""
        import ast
        import inspect
        import re
        import textwrap

        import toolkit.cli.secrets as cli

        tree = ast.parse(textwrap.dedent(inspect.getsource(cli.check_expiry)))
        literals = [
            n.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant)
            and isinstance(n.value, str)
            and re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", n.value)
        ]
        assert not literals, f"an IP literal is back in check-expiry: {literals}"

    def test_the_default_is_none_so_it_can_be_derived(self) -> None:
        """A literal default would make the derivation unreachable — which mypy
        reported when the signature and the body disagreed."""
        import inspect

        import toolkit.cli.secrets as cli

        assert inspect.signature(cli.check_expiry).parameters["ssh_target"].default is None

    def test_it_derives_the_public_ip_not_the_tailscale_one(self) -> None:
        """Headscale IS the VPN. A check that reaches it over the VPN cannot
        report on a VPN that is down."""
        import inspect

        import toolkit.cli.secrets as cli

        src = inspect.getsource(cli.check_expiry)
        assert "public_ip" in src and "tailscale_ip" not in src
