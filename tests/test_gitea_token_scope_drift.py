"""TOOL-056 (#1551) — a minted Gitea token's scopes are checked against the declared grant.

`tests/test_gitea_token_scopes.py` ties the DECLARATION in `common.yaml` to what
the Python callers require. This file covers the step after it: the token Gitea
actually minted. Gitea cannot edit a token's scopes after minting, and the mint
task is gated on the SOPS key being absent, so a token minted before a scope was
added keeps the old scopes while the declaration beside it reads correct. Both
prod tokens were in that state on 2026-09-01, and each surfaced only as a 403.

The comparison is pure and tested here without a forge; the CLI that feeds it a
live listing is tested against a scripted session at the bottom.
"""

from __future__ import annotations

from typing import Any

import pytest

from toolkit.features.gitea_tokens import ROTATABLE_TOKENS, ScopeVerdict, check_token_scopes

BOT_NAME = ROTATABLE_TOKENS["bot"].token_name


def _token(name: str, scopes: list[str], token_id: int = 1) -> dict[str, Any]:
    """The shape `GET /users/{u}/tokens` answers with (Gitea never returns the value)."""
    return {"id": token_id, "name": name, "scopes": scopes, "token_last_eight": "abcd1234"}


def test_a_token_minted_with_the_declared_grant_is_ok() -> None:
    result = check_token_scopes(
        "bot", "write:repository,write:user", [_token(BOT_NAME, ["write:repository", "write:user"])]
    )

    assert result.verdict is ScopeVerdict.OK
    assert not result.missing
    assert not result.undeclared


def test_a_scope_declared_after_the_mint_is_reported_missing() -> None:
    """The 2026-09-01 state: declaration widened, live token never re-minted."""
    result = check_token_scopes(
        "bot",
        "write:repository,write:user,write:organization",
        [_token(BOT_NAME, ["write:repository", "write:user"])],
    )

    assert result.verdict is ScopeVerdict.MISSING
    assert result.missing == frozenset({"write:organization"})


def test_a_minted_write_scope_covers_a_declared_read_scope() -> None:
    """Gitea normalises `read:x,write:x` to `write:x`; the write implies the read."""
    result = check_token_scopes("bot", "read:repository", [_token(BOT_NAME, ["write:repository"])])

    assert result.verdict is not ScopeVerdict.MISSING


def test_a_minted_scope_wider_than_the_declaration_is_drift() -> None:
    """Wider is drift for every token, not only the equality-pinned reviewer.

    A reconciler token that silently gained `write:repository` holds the delete
    capability #1076 refuses structurally; the declaration is the SSOT.
    """
    result = check_token_scopes(
        "admin",
        "read:admin,read:repository",
        [_token(ROTATABLE_TOKENS["admin"].token_name, ["read:admin", "write:repository"])],
    )

    assert result.verdict is ScopeVerdict.UNDECLARED
    assert result.undeclared == frozenset({"write:repository"})


def test_the_all_scope_covers_everything_and_is_never_declared() -> None:
    result = check_token_scopes("bot", "write:repository", [_token(BOT_NAME, ["all"])])

    assert not result.missing
    assert result.verdict is ScopeVerdict.UNDECLARED
    assert "all" in result.undeclared


def test_comparison_ignores_order_case_and_whitespace() -> None:
    result = check_token_scopes(
        "bot", " Write:User , write:repository", [_token(BOT_NAME, ["write:repository", "write:user"])]
    )

    assert result.verdict is ScopeVerdict.OK


def test_a_missing_and_an_undeclared_scope_together_report_missing_first() -> None:
    """Missing breaks calls today; undeclared is excess privilege. Both are listed."""
    result = check_token_scopes("bot", "write:organization", [_token(BOT_NAME, ["write:issue"])])

    assert result.verdict is ScopeVerdict.MISSING
    assert result.missing == frozenset({"write:organization"})
    assert result.undeclared == frozenset({"write:issue"})


def test_no_token_with_the_registered_name_is_absent_not_ok() -> None:
    """Absent is 'nothing to compare', which must never read as 'matches'."""
    result = check_token_scopes("bot", "write:repository", [_token("someone-else", ["write:repository"])])

    assert result.verdict is ScopeVerdict.ABSENT


def test_two_tokens_sharing_the_name_are_reported_not_guessed() -> None:
    """The state `revoke_token` answers 422 to: two live credentials, one name."""
    tokens = [_token(BOT_NAME, ["write:repository"], 1), _token(BOT_NAME, ["write:repository"], 2)]

    result = check_token_scopes("bot", "write:repository", tokens)

    assert result.verdict is ScopeVerdict.DUPLICATE


def test_an_unknown_label_is_refused() -> None:
    with pytest.raises(KeyError):
        check_token_scopes("nope", "write:repository", [])


# --- the CLI path: superadmin basic auth, listing only -------------------------------------------


class FakeResponse:
    def __init__(self, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else []
        self.ok = 200 <= status_code < 300
        self.content = b"x" if payload is not None else b""
        self.text = str(payload)
        self.headers: dict[str, str] = {}

    def json(self) -> Any:
        return self._payload


class FakeSession:
    """Replays a scripted response per (method, path prefix) and records every call."""

    def __init__(self, script: dict[tuple[str, str], FakeResponse]) -> None:
        self.script = script
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        path = url.split("/api/v1", 1)[-1].split("?", 1)[0]
        self.calls.append((method, path))
        for (m, p), resp in self.script.items():
            if m == method and path == p:
                return resp
        return FakeResponse(404, None)


IDENTITIES = {"machine": "hefesto", "superadmin": "manu", "reviewer": "argos"}
DECLARED = {
    "bot": "write:repository,write:user,write:organization",
    "admin": "read:admin,write:organization,read:repository,read:user",
    "reviewer": "write:issue,read:repository",
}


def _listing(username: str, scopes: str, label: str) -> tuple[tuple[str, str], FakeResponse]:
    return ("GET", f"/users/{username}/tokens"), FakeResponse(
        200, [_token(ROTATABLE_TOKENS[label].token_name, scopes.split(","))]
    )


def _all_converged() -> dict[tuple[str, str], FakeResponse]:
    return dict(
        [
            _listing("hefesto", DECLARED["bot"], "bot"),
            _listing("manu", DECLARED["admin"], "admin"),
            _listing("argos", DECLARED["reviewer"], "reviewer"),
        ]
    )


def _run(script: dict[tuple[str, str], FakeResponse]) -> tuple[int, FakeSession]:
    from toolkit.cli.services import check_gitea_token_scopes
    from toolkit.features.gitea_client import GiteaBasicAuthClient

    client = GiteaBasicAuthClient("https://gitea.example", "manu", "pw")
    session = FakeSession(script)
    client.session = session  # type: ignore[assignment]
    return check_gitea_token_scopes(client, IDENTITIES, DECLARED, env="prod"), session


def test_every_token_converged_exits_zero() -> None:
    code, _ = _run(_all_converged())

    assert code == 0


def test_drift_exits_nonzero_and_never_writes() -> None:
    """Report-only is a guard, not a comment: no rotation, no delete, on any path."""
    script = _all_converged()
    script.update(dict([_listing("hefesto", "write:repository,write:user", "bot")]))

    code, session = _run(script)

    assert code != 0
    assert all(method == "GET" for method, _ in session.calls), session.calls


def test_a_refused_listing_is_unchecked_not_ok() -> None:
    """lesson-408: 'I could not look' must never read as 'I looked and it matches'."""
    script = _all_converged()
    script[("GET", "/users/argos/tokens")] = FakeResponse(403, {"message": "forbidden"})

    code, _ = _run(script)

    assert code != 0


def test_a_token_with_no_declared_grant_is_unchecked_not_ok() -> None:
    declared = {k: v for k, v in DECLARED.items() if k != "reviewer"}
    from toolkit.cli.services import check_gitea_token_scopes
    from toolkit.features.gitea_client import GiteaBasicAuthClient

    client = GiteaBasicAuthClient("https://gitea.example", "manu", "pw")
    client.session = FakeSession(_all_converged())  # type: ignore[assignment]

    assert check_gitea_token_scopes(client, IDENTITIES, declared, env="prod") != 0
