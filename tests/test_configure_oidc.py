"""Tests for configure_oidc token-endpoint drift verification (OIDC-DRIFT-001).

The incident: `make configure-oidc ENV=prod` reported success (exit 0) while the
Gitea OIDC flow was actually broken — the SOPS plaintext no longer matched the
argon2 hash Authelia stored. configure_oidc now does a post-update token round-trip
and classifies the response: invalid_client => the secret<->hash drift is real.

classify_token_response is a pure function (no I/O), so the PASS/FAIL discrimination
is pinned here deterministically; the HTTP call is mocked in the integration tests.
"""

from __future__ import annotations

import httpx
import pytest

from toolkit.scripts import configure_oidc
from toolkit.scripts.configure_oidc import (
    VERIFY_FAIL,
    VERIFY_INCONCLUSIVE,
    VERIFY_PASS,
    classify_token_response,
    verify_token_endpoint,
)

_CFG = {"authelia_url": "https://auth.staging.kubelab.live", "oidc_client_secret": "s3cr3t"}


class TestClassifyTokenResponse:
    """invalid_client => FAIL (the drift); any other outcome => PASS."""

    def test_invalid_client_is_fail(self) -> None:
        assert classify_token_response(401, {"error": "invalid_client"}) == VERIFY_FAIL

    def test_access_token_is_pass(self) -> None:
        assert classify_token_response(200, {"access_token": "abc", "token_type": "bearer"}) == VERIFY_PASS

    def test_other_oauth_error_is_pass(self) -> None:
        # client auth already succeeded; we tripped on the (disabled) grant instead
        assert classify_token_response(400, {"error": "unauthorized_client"}) == VERIFY_PASS
        assert classify_token_response(400, {"error": "unsupported_grant_type"}) == VERIFY_PASS

    def test_invalid_client_wins_even_on_non_401_status(self) -> None:
        # the machine-readable error field is authoritative, not the HTTP status
        assert classify_token_response(400, {"error": "invalid_client"}) == VERIFY_FAIL


class TestVerifyTokenEndpoint:
    """Network/parse failures must be inconclusive, never a false drift."""

    def test_unreachable_endpoint_is_inconclusive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*_a: object, **_k: object) -> object:
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(configure_oidc.httpx, "post", boom)
        assert verify_token_endpoint(_CFG, "staging") == VERIFY_INCONCLUSIVE

    def test_invalid_client_maps_to_fail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_post(*_a: object, **_k: object) -> httpx.Response:
            return httpx.Response(401, json={"error": "invalid_client"})

        monkeypatch.setattr(configure_oidc.httpx, "post", fake_post)
        assert verify_token_endpoint(_CFG, "staging") == VERIFY_FAIL

    def test_client_auth_ok_maps_to_pass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_post(*_a: object, **_k: object) -> httpx.Response:
            return httpx.Response(400, json={"error": "unsupported_grant_type"})

        monkeypatch.setattr(configure_oidc.httpx, "post", fake_post)
        assert verify_token_endpoint(_CFG, "staging") == VERIFY_PASS

    def test_non_json_body_is_inconclusive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_post(*_a: object, **_k: object) -> httpx.Response:
            return httpx.Response(502, text="<html>bad gateway</html>")

        monkeypatch.setattr(configure_oidc.httpx, "post", fake_post)
        assert verify_token_endpoint(_CFG, "staging") == VERIFY_INCONCLUSIVE
