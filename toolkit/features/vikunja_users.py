"""Read-only audit of who holds a Vikunja account.

SEC-VIKUNJA-001 (#1568) AC3. Closing public self-registration does not evict whoever
signed up while it was open, and `tasks.kubelab.live` has had an open `/register`
endpoint on a public Cloudflare record since the platform shipped (#1484,
2026-08-27). "It should be empty" is a belief; this produces the count.

Why the database rather than the API: Vikunja's `GET /api/v1/users` is a *search* --
it answers with users matching a query and has no enumerate-all mode. An audit built
on it would report "no results" for a search term that simply did not match, which is
the failure this file exists to avoid. The `users` table is the only authoritative
answer to "who exists".

The split between this module and its CLI caller is deliberate: everything here is
pure, so the classification is unit-tested without a cluster, and the caller owns the
one impure step (`kubectl exec` into the postgres pod, the same path
`provision-postgres-tenant` already uses).
"""

from __future__ import annotations

from dataclasses import dataclass

#: Unaligned, tuples-only, pipe-separated -- `psql -tAF'|'`. Chosen so the parser is a
#: split rather than a table-format reader.
FIELD_SEPARATOR = "|"

#: Four columns that are load-bearing in Vikunja's own auth code: `issuer` is what
#: `getOrCreateUser` keys on to decide whether an account came from OIDC. Deliberately
#: minimal -- every extra column is one more chance of a schema mismatch turning an
#: audit into an error, and none of them would change the verdict.
USER_AUDIT_SQL = "SELECT id, username, email, issuer FROM users ORDER BY id;"

#: Vikunja leaves `issuer` empty for password accounts. Rendered as this rather than
#: as an empty string so a local account is never mistaken for a parse failure.
LOCAL = "local"


@dataclass(frozen=True)
class VikunjaUser:
    """One row of the `users` table."""

    user_id: str
    username: str
    email: str
    issuer: str

    @property
    def is_local(self) -> bool:
        """True when this account was created by password signup, not by OIDC.

        These are the accounts that an open `/register` endpoint could have produced.
        An OIDC account required a successful Authelia login, so it is already gated
        by the identity provider.
        """
        return self.issuer == LOCAL


def parse_user_rows(raw: str) -> list[VikunjaUser]:
    """Parse `psql -tAF'|'` output into users.

    Raises `ValueError` on a row that does not have exactly four fields rather than
    skipping it. A silently dropped row is a user who does not appear in the audit,
    which is precisely the account an audit exists to surface -- and an email
    containing the separator would otherwise vanish without a trace.
    """
    users: list[VikunjaUser] = []
    for line in raw.splitlines():
        row = line.strip()
        if not row:
            continue
        fields = row.split(FIELD_SEPARATOR)
        if len(fields) != 4:
            raise ValueError(
                f"expected 4 fields separated by {FIELD_SEPARATOR!r}, got {len(fields)}: {row!r}. "
                "Refusing to skip the row -- a dropped row is an unaudited account."
            )
        user_id, username, email, issuer = (field.strip() for field in fields)
        users.append(
            VikunjaUser(
                user_id=user_id,
                username=username,
                email=email,
                issuer=issuer or LOCAL,
            )
        )
    return users


def local_accounts(users: list[VikunjaUser]) -> list[VikunjaUser]:
    """The subset an open registration endpoint could have created."""
    return [user for user in users if user.is_local]
