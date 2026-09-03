"""SEC-VIKUNJA-001 (#1568) AC3: the user audit classifies accounts correctly.

The impure half (`kubectl exec` into the postgres pod) lives in the CLI; everything
asserted here is pure, so the classification is checked without a cluster and stays
checkable with the homelab powered off.
"""

from __future__ import annotations

import pytest

from toolkit.features.vikunja_users import (
    LOCAL,
    USER_AUDIT_SQL,
    VikunjaUser,
    local_accounts,
    parse_user_rows,
)


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
