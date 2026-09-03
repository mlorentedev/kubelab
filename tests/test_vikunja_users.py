"""SEC-VIKUNJA-001 (#1568) AC3: the user audit classifies accounts correctly.

The impure half (`kubectl exec` into the postgres pod) lives in the CLI; everything
asserted here is pure, so the classification is checked without a cluster and stays
checkable with the homelab powered off.
"""

from __future__ import annotations

import pathlib

import pytest

from toolkit.features.vikunja_users import (
    EXEC_TIMEOUT,
    LOCAL,
    USER_AUDIT_SQL,
    VikunjaUser,
    local_accounts,
    parse_user_rows,
)

MAKEFILE = pathlib.Path(__file__).resolve().parents[1] / "Makefile"


def test_an_empty_issuer_is_reported_as_a_local_account() -> None:
    """Vikunja leaves `issuer` empty for password signups.

    Rendering that as `local` rather than as `''` is what stops a password account
    from reading as a parse failure in the printed table.
    """
    users = parse_user_rows("1|manu|manu@example.com|\n")

    assert users == [VikunjaUser(user_id="1", username="manu", email="manu@example.com", issuer=LOCAL)]
    assert users[0].is_local is True


def test_an_oidc_account_keeps_its_issuer_and_is_not_local() -> None:
    """An account created through Authelia was gated by the identity provider.

    It is not what an open `/register` endpoint produces, so it must not be counted
    among the accounts this audit asks the operator to vouch for.
    """
    users = parse_user_rows("2|operator|ops@example.com|https://auth.kubelab.live\n")

    assert users[0].issuer == "https://auth.kubelab.live"
    assert users[0].is_local is False
    assert local_accounts(users) == []


def test_local_and_oidc_accounts_are_separated() -> None:
    users = parse_user_rows(
        "1|manu|manu@example.com|\n2|operator|ops@example.com|https://auth.kubelab.live\n3|stranger|x@y.z|\n"
    )

    assert [user.username for user in local_accounts(users)] == ["manu", "stranger"]


def test_blank_lines_are_ignored() -> None:
    """`psql -tA` emits a trailing newline; an empty row is not an account."""
    assert parse_user_rows("\n1|manu|manu@example.com|\n\n") == [
        VikunjaUser(user_id="1", username="manu", email="manu@example.com", issuer=LOCAL)
    ]


def test_a_malformed_row_raises_instead_of_being_skipped() -> None:
    """A dropped row is an unaudited account — exactly what the audit exists to find.

    An email containing the separator would otherwise vanish silently, and the audit
    would under-report by one while looking entirely healthy.
    """
    with pytest.raises(ValueError, match="Refusing to skip"):
        parse_user_rows("1|manu|weird|email@example.com|\n")


def test_the_audit_query_only_reads() -> None:
    """A constant that ever becomes a write is the difference between an audit and an
    incident. Asserted here so a future edit has to argue with a test."""
    lowered = USER_AUDIT_SQL.lower()

    assert lowered.startswith("select ")
    forbidden = ("insert", "update ", "delete", "drop", "alter", "truncate", "grant")
    assert not [word for word in forbidden if word in lowered], f"the audit query is not read-only: {USER_AUDIT_SQL!r}"


def test_the_exec_call_is_bounded() -> None:
    """An unbounded `kubectl exec` hangs rather than fails.

    `exec` opens a stream and waits indefinitely on an unreachable API server, and
    half this fleet is on-demand — so an unreachable cluster is an ordinary state.
    A hang is worse than an error here because it produces no verdict at all.
    """
    assert isinstance(EXEC_TIMEOUT, int) and EXEC_TIMEOUT > 0, (
        f"EXEC_TIMEOUT={EXEC_TIMEOUT!r} does not bound anything"
    )


def test_the_make_target_validates_the_env_value_not_its_presence() -> None:
    """`test -n "$(ENV)"` can never fail, and shipped twice before (#1118/#1122).

    `ENV ?= dev` is global regardless of where it appears in the Makefile, so a
    presence check always passes and a bare `make vikunja-audit-users` would audit
    `dev` — an environment with no Vikunja. The audit would then report an EMPTY
    ACCOUNT LIST rather than an error, which is precisely the inversion the command
    exists to prevent: "I could not look" rendered as "nobody is there".

    Asserted against the recipe text because the failure is not that the guard is
    absent — it is that a weaker guard looks entirely reasonable in review.
    """
    text = MAKEFILE.read_text()
    recipe = text[text.index("vikunja-audit-users: ##") :]
    recipe = recipe[: recipe.index("\n.PHONY")]

    assert 'test -n "$(ENV)"' not in recipe, (
        "the guard is back to checking that ENV is non-empty; `ENV ?= dev` makes "
        "that unfailable, so `make vikunja-audit-users` would audit dev (#1118)"
    )
    assert "$(origin ENV)" not in recipe, (
        "the guard is testing where ENV came from rather than what it is; both "
        "`ENV=` and `ENV=dev` pass that test (#1122)"
    )
    assert "$(filter $(ENV),$(VIKUNJA_ENVS))" in recipe, (
        "the guard no longer validates ENV against the VIKUNJA_ENVS allow-list — "
        "an allow-list the recipe does not consult guards nothing"
    )
    assert "$(words $(ENV))" in recipe, (
        'ENV="staging prod" passes `filter` alone and is then spliced unquoted '
        "into the toolkit's argv"
    )
