"""Tests for registry — Docker Hub client + tag-prune policy (ADR-046).

The retention policy (`select_stale_tags`) is pure and gets the bulk of the
coverage; the client and orchestration are exercised with httpx mocked / a fake
client so no network is touched.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from toolkit.features import registry
from toolkit.features.registry import DockerHubClient, TagInfo, prune, select_stale_tags


def _tag(name: str, ts: str = "2026-01-01T00:00:00Z") -> TagInfo:
    return TagInfo(name=name, last_updated=ts)


class TestSelectStaleTags:
    """Keep newest N sha-*, delete the rest + all -rc.*; never touch semver/mutable."""

    def test_keeps_newest_n_sha_deletes_older(self) -> None:
        tags = [
            _tag("sha-aaaaaaa", "2026-06-01T00:00:00Z"),
            _tag("sha-bbbbbbb", "2026-06-03T00:00:00Z"),
            _tag("sha-ccccccc", "2026-06-02T00:00:00Z"),
        ]
        # newest two (bbb, ccc) retained; oldest (aaa) is stale.
        assert select_stale_tags(tags, retention=2) == ["sha-aaaaaaa"]

    def test_deletes_all_rc(self) -> None:
        tags = [_tag("1.2.0-rc.1"), _tag("1.2.0-rc.2"), _tag("1.2.0")]
        assert set(select_stale_tags(tags, retention=10)) == {"1.2.0-rc.1", "1.2.0-rc.2"}

    def test_never_touches_semver_or_mutable(self) -> None:
        tags = [_tag("1.1.0"), _tag("latest"), _tag("dev")]
        assert select_stale_tags(tags, retention=0) == []

    def test_retention_zero_deletes_all_sha(self) -> None:
        assert set(select_stale_tags([_tag("sha-a"), _tag("sha-b")], retention=0)) == {"sha-a", "sha-b"}

    def test_fewer_than_retention_keeps_all(self) -> None:
        assert select_stale_tags([_tag("sha-a"), _tag("sha-b")], retention=15) == []

    def test_negative_retention_rejected(self) -> None:
        with pytest.raises(ValueError, match="retention"):
            select_stale_tags([], retention=-1)


class TestDockerHubClient:
    def test_list_tags_paginates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pages = [
            MagicMock(
                status_code=200,
                **{"json.return_value": {"results": [{"name": "sha-a", "last_updated": "t1"}], "next": "url2"}},
            ),
            MagicMock(
                status_code=200,
                **{"json.return_value": {"results": [{"name": "sha-b", "last_updated": "t2"}], "next": None}},
            ),
        ]
        get = MagicMock(side_effect=pages)
        monkeypatch.setattr(registry.httpx, "get", get)

        tags = DockerHubClient(namespace="ns", token="t").list_tags("kubelab-api")

        assert [t.name for t in tags] == ["sha-a", "sha-b"]
        assert get.call_count == 2

    def test_list_tags_missing_repo_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(registry.httpx, "get", MagicMock(return_value=MagicMock(status_code=404)))
        assert DockerHubClient(namespace="ns").list_tags("nope") == []

    def test_delete_tag_treats_204_and_404_as_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for code in (204, 404):
            monkeypatch.setattr(registry.httpx, "delete", MagicMock(return_value=MagicMock(status_code=code)))
            assert DockerHubClient(namespace="ns", token="t").delete_tag("repo", "sha-x") is True

    def test_delete_tag_failure_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(registry.httpx, "delete", MagicMock(return_value=MagicMock(status_code=401)))
        assert DockerHubClient(namespace="ns", token="t").delete_tag("repo", "sha-x") is False

    def test_from_env_requires_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DOCKERHUB_USERNAME", raising=False)
        monkeypatch.delenv("DOCKERHUB_TOKEN", raising=False)
        with pytest.raises(ValueError, match="DOCKERHUB_USERNAME"):
            DockerHubClient.from_env()


class TestPrune:
    def _client(self, tags: list[TagInfo], delete_ok: bool = True) -> MagicMock:
        c = MagicMock()
        c.list_tags.return_value = tags
        c.delete_tag.return_value = delete_ok
        return c

    def test_dry_run_deletes_nothing(self) -> None:
        client = self._client([_tag("sha-a", "t1"), _tag("sha-b", "t2"), _tag("sha-c", "t3")])
        n = prune(["api"], "kubelab", retention=1, dry_run=True, client=client)
        client.delete_tag.assert_not_called()
        assert n == 2  # two stale would be deleted

    def test_deletes_stale_keeps_newest_and_semver(self) -> None:
        tags = [_tag("sha-a", "t1"), _tag("sha-b", "t3"), _tag("sha-c", "t2"), _tag("1.0.0", "t9")]
        client = self._client(tags)
        n = prune(["api"], "kubelab", retention=1, dry_run=False, client=client)
        deleted = {call.args[1] for call in client.delete_tag.call_args_list}
        assert n == 2
        assert deleted == {"sha-a", "sha-c"}  # sha-b (newest) and 1.0.0 (semver) kept

    def test_repo_name_uses_prefix(self) -> None:
        client = self._client([])
        prune(["api", "web"], "kubelab", retention=15, dry_run=False, client=client)
        repos = {call.args[0] for call in client.list_tags.call_args_list}
        assert repos == {"kubelab-api", "kubelab-web"}
