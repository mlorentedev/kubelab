"""`registry.tag_exists` on a registry that is not Docker Hub (IDP-053 D3).

Tri-state, with a real transport: an anonymous OCI ``HEAD /v2/<name>/manifests/<tag>``
answers ``True`` (200) or ``False`` (404); a private registry (401/403), any other
answer or an unreachable host answers ``None`` with a warning naming the registry,
so ``promote`` keeps proceeding on a registry it cannot read. The HTTP call is
injected: no test here reaches a network.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from toolkit.features import registry

GITEA = "gitea.kubelab.live/personal"


class _Http:
    """A stand-in for ``httpx.head`` that records the call and answers with one status."""

    def __init__(self, status: int | Exception) -> None:
        self.status = status
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append((url, kwargs))
        if isinstance(self.status, Exception):
            raise self.status
        return httpx.Response(self.status)


@pytest.fixture
def warnings(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    warn = MagicMock()
    monkeypatch.setattr(registry.logger, "warning", warn)
    return warn


class TestTagExistsOnAnotherRegistry:
    def test_the_manifest_is_read_from_the_registrys_own_v2_endpoint(self) -> None:
        http = _Http(200)

        registry.tag_exists(GITEA, "beta", "sha-0123456789ab", http=http)

        ((url, kwargs),) = http.calls
        assert url == "https://gitea.kubelab.live/v2/personal/beta/manifests/sha-0123456789ab"
        assert "application/vnd.oci.image.manifest.v1+json" in kwargs["headers"]["Accept"]
        assert "Authorization" not in kwargs["headers"]

    def test_200_is_true(self) -> None:
        assert registry.tag_exists(GITEA, "x", "sha-0123456", http=_Http(200)) is True

    def test_404_is_false(self) -> None:
        assert registry.tag_exists(GITEA, "x", "sha-0123456", http=_Http(404)) is False

    @pytest.mark.parametrize("status", [401, 403, 500, 502])
    def test_a_registry_that_will_not_say_is_none_naming_it(self, status: int, warnings: MagicMock) -> None:
        assert registry.tag_exists(GITEA, "x", "sha-0123456", http=_Http(status)) is None

        (message,), _ = warnings.call_args
        assert "gitea.kubelab.live" in message
        assert "unverified" in message
        assert str(status) in message

    def test_an_unreachable_host_is_none_naming_it(self, warnings: MagicMock) -> None:
        http = _Http(httpx.ConnectError("no route"))

        assert registry.tag_exists(GITEA, "x", "sha-0123456", http=http) is None

        (message,), _ = warnings.call_args
        assert "gitea.kubelab.live" in message
        assert "unverified" in message

    def test_a_registry_with_no_owner_path_has_no_empty_segment(self) -> None:
        http = _Http(200)

        registry.tag_exists("ghcr.io", "x", "1.0.0", http=http)

        assert http.calls[0][0] == "https://ghcr.io/v2/x/manifests/1.0.0"


class TestDockerHubKeepsItsOwnRoute:
    def test_docker_hub_is_not_read_through_v2(self, monkeypatch: pytest.MonkeyPatch) -> None:
        get = MagicMock(return_value=httpx.Response(200))
        http = _Http(500)
        monkeypatch.setattr(registry.httpx, "get", get)

        assert registry.tag_exists("docker.io/mlorentedev", "kubelab-web", "1.0.0", http=http) is True

        assert http.calls == []
        assert "hub.docker.com" in get.call_args.args[0]
