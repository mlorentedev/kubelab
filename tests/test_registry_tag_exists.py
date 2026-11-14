"""`registry.tag_exists`, tri-state on Docker Hub and on any other registry (IDP-053 D3, #3272).

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


HUB = "docker.io/mlorentedev"


def _hub_answers(monkeypatch: pytest.MonkeyPatch, status: int | Exception) -> MagicMock:
    """Make the Docker Hub tags API answer with one status (or raise), recording the call."""
    get = (
        MagicMock(side_effect=status)
        if isinstance(status, Exception)
        else MagicMock(return_value=httpx.Response(status))
    )
    monkeypatch.setattr(registry.httpx, "get", get)
    return get


class TestTagExistsOnDockerHubIsTriState:
    """Hub answers the same three ways as any other registry: present, absent, or unverified.

    Reading a 429/5xx as "absent" made ``promote`` refuse an existing tag with a message
    saying it does not exist (#3272).
    """

    def test_200_is_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _hub_answers(monkeypatch, 200)

        assert registry.tag_exists(HUB, "kubelab-web", "1.0.0") is True

    def test_404_is_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _hub_answers(monkeypatch, 404)

        assert registry.tag_exists(HUB, "kubelab-web", "1.0.0") is False

    @pytest.mark.parametrize("status", [401, 403, 429, 500, 502, 503])
    def test_any_other_answer_is_none_naming_the_registry_and_status(
        self, status: int, monkeypatch: pytest.MonkeyPatch, warnings: MagicMock
    ) -> None:
        _hub_answers(monkeypatch, status)

        assert registry.tag_exists(HUB, "kubelab-web", "1.0.0") is None

        (message,), _ = warnings.call_args
        assert "docker.io" in message
        assert "unverified" in message
        assert str(status) in message

    def test_an_unreachable_hub_is_none_naming_the_registry(
        self, monkeypatch: pytest.MonkeyPatch, warnings: MagicMock
    ) -> None:
        _hub_answers(monkeypatch, httpx.ConnectError("no route"))

        assert registry.tag_exists(HUB, "kubelab-web", "1.0.0") is None

        (message,), _ = warnings.call_args
        assert "docker.io" in message
        assert "unverified" in message
