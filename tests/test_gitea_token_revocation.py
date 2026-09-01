"""TOOL-035 (#1076) — revoking a Gitea token is idempotent, and needs a password.

Two properties, both structural rather than incidental.

**Idempotence by 404.** Gitea answers 404 when a token name matches nothing, and
that is indistinguishable from the desired end state. `revoke_token` reports it
as "already converged" instead of raising, so a rotation run twice is a rotation
rather than a script that fails the second time.

**Basic Auth, because Gitea refuses tokens here.** `DELETE /users/{u}/tokens/{id}`
sits behind `reqBasicOrRevProxyAuth()` in `routers/api/v1/api.go`, which rejects a
bearer token before the handler runs. Read from the source on 1.25.x rather than
inferred from a 403 -- a 403 from a missing scope and one from a rejected auth
scheme look identical, which is the trap AUTH-004 AC5 recorded once.

The consequence is that the admin password is load-bearing for token rotation,
which is why the Ansible role reconciles it against SOPS rather than assuming the
two still match. The tests for that live with the role; these cover the client.
"""

from __future__ import annotations

from typing import Any

import pytest

from toolkit.features.gitea_client import GiteaBasicAuthClient, GiteaError


class FakeResponse:
    def __init__(self, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else []
        self.ok = 200 <= status_code < 300
        self.content = b"x" if payload is not None else b""
        self.text = str(payload)

    def json(self) -> Any:
        return self._payload


class FakeSession:
    """Records requests and replays a scripted status per (method, path)."""

    def __init__(self, script: dict[tuple[str, str], FakeResponse]) -> None:
        self.script = script
        self.calls: list[tuple[str, str]] = []
        self.auth: tuple[str, str] | None = None
        self.headers_seen: list[dict[str, str]] = []
        self.auth_seen: list[tuple[str, str] | None] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        path = url.split("/api/v1", 1)[-1]
        self.calls.append((method, path))
        self.headers_seen.append(kwargs.get("headers", {}))
        self.auth_seen.append(kwargs.get("auth"))
        for (m, p), resp in self.script.items():
            if m == method and path.startswith(p):
                return resp
        return FakeResponse(404, None)


def _client(script: dict[tuple[str, str], FakeResponse]) -> GiteaBasicAuthClient:
    client = GiteaBasicAuthClient("https://gitea.example", "manu", "pw")
    client.session = FakeSession(script)  # type: ignore[assignment]
    return client


def test_revoking_an_existing_token_reports_a_change() -> None:
    client = _client({("DELETE", "/users/hefesto/tokens/"): FakeResponse(204)})

    assert client.revoke_token("hefesto", "kubelab-provisioning") is True


def test_revoking_an_absent_token_is_not_an_error() -> None:
    """404 is the desired end state, not a failure.

    Without this, the second run of a rotation raises on a forge that is already
    in the state the rotation was asking for.
    """
    client = _client({("DELETE", "/users/hefesto/tokens/"): FakeResponse(404, None)})

    assert client.revoke_token("hefesto", "kubelab-provisioning") is False


def test_a_second_revoke_converges_rather_than_failing() -> None:
    """The idempotence claim end to end: same call, twice, no exception."""
    responses = iter([FakeResponse(204), FakeResponse(404, None)])

    class Sequenced(FakeSession):
        def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
            self.calls.append((method, url.split("/api/v1", 1)[-1]))
            return next(responses)

    client = GiteaBasicAuthClient("https://gitea.example", "manu", "pw")
    client.session = Sequenced({})  # type: ignore[assignment]

    assert client.revoke_token("hefesto", "kubelab-provisioning") is True
    assert client.revoke_token("hefesto", "kubelab-provisioning") is False


def test_other_failures_still_raise() -> None:
    """The control. A 404-tolerant delete that swallowed everything would hide a
    401 from a drifted admin password -- the exact failure this design is built
    around, reported as success."""
    client = _client({("DELETE", "/users/hefesto/tokens/"): FakeResponse(401, "unauthorized")})

    with pytest.raises(GiteaError) as exc:
        client.revoke_token("hefesto", "kubelab-provisioning")

    assert exc.value.status_code == 401


def test_multiple_matches_are_not_guessed() -> None:
    """Gitea answers 422 on an ambiguous name; that propagates.

    Two tokens sharing a name is the state `bot_token`'s rotate_note warns about
    -- "the account would hold two live credentials and nothing records which
    consumer holds which". Picking one is worse than stopping.
    """
    client = _client({("DELETE", "/users/hefesto/tokens/"): FakeResponse(422, "multiple matches")})

    with pytest.raises(GiteaError) as exc:
        client.revoke_token("hefesto", "kubelab-provisioning")

    assert exc.value.status_code == 422


def test_no_authorization_header_is_sent() -> None:
    """The endpoint rejects bearer tokens, so sending one would be a silent 403.

    Asserted on the header rather than trusted to the class hierarchy: the parent
    builds an `Authorization: token ...` header, and inheriting it here would
    produce a refusal that looks like a permissions problem.
    """
    client = _client({("DELETE", "/users/hefesto/tokens/"): FakeResponse(204)})

    client.revoke_token("hefesto", "kubelab-provisioning")

    assert all("Authorization" not in h for h in client.session.headers_seen)  # type: ignore[attr-defined]


def test_credentials_travel_with_the_request_not_the_session() -> None:
    """Bound per call, so swapping the session cannot silently drop auth.

    Written after the first version of this suite caught exactly that: the
    credential lived on `session.auth`, the test replaced the session with a
    double, and every request went out unauthenticated. In production the same
    shape (a retry wrapper, a pooled client) yields a 401 that is
    indistinguishable from the drifted admin password this design is built to
    detect -- so the failure would be diagnosed in the wrong place entirely.
    """
    client = _client({("DELETE", "/users/hefesto/tokens/"): FakeResponse(204)})

    client.revoke_token("hefesto", "kubelab-provisioning")

    assert client.session.auth_seen == [("manu", "pw")]  # type: ignore[attr-defined]
