"""Tests for registry — Docker Hub client + tag-prune policy (ADR-046).

The retention policy (`select_stale_tags`) is pure and gets the bulk of the
coverage; the client and orchestration are exercised with httpx mocked / a fake
client so no network is touched.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from toolkit.features import registry
from toolkit.features.registry import DockerHubClient, TagInfo, image_repositories, prune, select_stale_tags


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

    def test_never_prunes_protected_sha(self) -> None:
        # A sha pinned by a committed overlay must survive even outside the
        # retention window — pruning it would break a pending prod re-tag (ADR-056).
        tags = [_tag("sha-old0000", "2026-06-01T00:00:00Z"), _tag("sha-new1111", "2026-06-09T00:00:00Z")]
        stale = select_stale_tags(tags, retention=0, protected={"sha-old0000"})
        assert "sha-old0000" not in stale
        assert "sha-new1111" in stale


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
        monkeypatch.setattr("toolkit.config.settings.get_settings", lambda: None)  # a config that has none
        with pytest.raises(ValueError, match="DOCKERHUB_USERNAME"):
            DockerHubClient.from_env()

    def test_from_env_reads_the_workstation_config_when_ci_has_not_set_them(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Importing the toolkit injects nothing (TOOL-097), so `from_env` builds settings itself."""
        monkeypatch.delenv("DOCKERHUB_USERNAME", raising=False)
        monkeypatch.delenv("DOCKERHUB_TOKEN", raising=False)

        def inject() -> None:  # what get_settings() does with the SOPS values
            monkeypatch.setenv("DOCKERHUB_USERNAME", "ns")
            monkeypatch.setenv("DOCKERHUB_TOKEN", "t")

        monkeypatch.setattr("toolkit.config.settings.get_settings", inject)
        monkeypatch.setattr(DockerHubClient, "_login", staticmethod(lambda user, password: "jwt"))
        assert DockerHubClient.from_env().namespace == "ns"


class TestPrune:
    def _client(self, tags: list[TagInfo], delete_ok: bool = True) -> MagicMock:
        c = MagicMock()
        c.list_tags.return_value = tags
        c.delete_tag.return_value = delete_ok
        return c

    def test_dry_run_deletes_nothing(self) -> None:
        client = self._client([_tag("sha-a", "t1"), _tag("sha-b", "t2"), _tag("sha-c", "t3")])
        n = prune({"api": "kubelab-api"}, retention=1, dry_run=True, client=client)
        client.delete_tag.assert_not_called()
        assert n == 2  # two stale would be deleted

    def test_deletes_stale_keeps_newest_and_semver(self) -> None:
        tags = [_tag("sha-a", "t1"), _tag("sha-b", "t3"), _tag("sha-c", "t2"), _tag("1.0.0", "t9")]
        client = self._client(tags)
        n = prune({"api": "kubelab-api"}, retention=1, dry_run=False, client=client)
        deleted = {call.args[1] for call in client.delete_tag.call_args_list}
        assert n == 2
        assert deleted == {"sha-a", "sha-c"}  # sha-b (newest) and 1.0.0 (semver) kept

    def test_lists_the_repository_it_is_given(self) -> None:
        client = self._client([])
        prune({"api": "kubelab-api", "third": "third"}, retention=15, dry_run=False, client=client)
        repos = {call.args[0] for call in client.list_tags.call_args_list}
        assert repos == {"kubelab-api", "third"}


FIXTURE_REGISTRY = Path(__file__).parent / "fixtures" / "product" / "registry.yaml"


class TestImageRepositories:
    """Each app is pruned in the repository it is deployed from (#2511), never in ``<prefix>-<app>``."""

    def test_the_committed_set_is_the_three_kubelab_repositories(self) -> None:
        from toolkit.features.product_registry import platform_apps

        assert image_repositories([*platform_apps(), "errors"]) == {
            "api": "kubelab-api",
            "web": "kubelab-web",
            "errors": "kubelab-errors",
        }

    def test_a_product_with_no_image_name_override_is_pruned_in_its_derived_repository(self) -> None:
        assert image_repositories(["third"], registry=FIXTURE_REGISTRY) == {"third": "third"}

    def test_a_contract_managed_override_wins(self) -> None:
        assert image_repositories(["web"], registry=FIXTURE_REGISTRY) == {"web": "kubelab-web"}

    def test_an_in_tree_app_with_no_image_name_is_refused(self) -> None:
        with pytest.raises(ValueError, match="apps.platform.api.image_name"):
            image_repositories(["api"], common={"apps": {"platform": {}}})

    def test_errors_without_an_image_name_is_refused(self) -> None:
        with pytest.raises(ValueError, match="edge.errors.image_name"):
            image_repositories(["errors"], common={"edge": {}})

    def test_no_env_overrides_an_image_name(self) -> None:
        """Repositories are read from common.yaml alone, which holds only if no env moves one."""
        import yaml

        from toolkit.config.settings import PROJECT_ROOT

        for env in ("staging", "prod"):
            values = yaml.safe_load((PROJECT_ROOT / f"infra/config/values/{env}.yaml").read_text()) or {}
            platform = (values.get("apps") or {}).get("platform") or {}
            moved = [app for app, block in platform.items() if "image_name" in (block or {})]
            assert moved == [], f"values/{env}.yaml overrides image_name for {moved}"
            assert "image_name" not in ((values.get("edge") or {}).get("errors") or {})


class TestPruneCliDefault:
    """With no ``--apps``, the prune covers every registered product plus ``errors`` (IDP-042)."""

    def test_a_third_registered_product_is_pruned_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from typer.testing import CliRunner

        from toolkit.cli import registry as registry_cli
        from toolkit.features import product_registry
        from toolkit.main import app

        fixture = Path(__file__).parent / "fixtures" / "product" / "registry.yaml"
        monkeypatch.setattr(product_registry, "registry_path", lambda: fixture)
        monkeypatch.setattr(registry_cli.promotion, "read_pinned_version", lambda env, app_name: None)
        seen_repos: list[dict[str, str]] = []
        monkeypatch.setattr(
            registry_cli.registry, "prune", lambda repos, *args, **kwargs: seen_repos.append(repos) or 0
        )

        result = CliRunner().invoke(app, ["registry", "prune", "--dry-run"])

        assert result.exit_code == 0, result.output
        assert seen_repos == [
            {"api": "kubelab-api", "web": "kubelab-web", "third": "third", "errors": "kubelab-errors"}
        ]

    @pytest.mark.parametrize("given", ["", " , "])
    def test_an_explicitly_empty_apps_prunes_nothing(self, monkeypatch: pytest.MonkeyPatch, given: str) -> None:
        """Omitted means every product; empty means none, as it did before the default moved.

        A caller interpolating an empty variable (``--apps "$APPS"``) must not widen
        into a prune of every registered product.
        """
        from typer.testing import CliRunner

        from toolkit.cli import registry as registry_cli
        from toolkit.main import app

        monkeypatch.setattr(registry_cli.promotion, "read_pinned_version", lambda env, app_name: None)
        seen: list[dict[str, str]] = []
        monkeypatch.setattr(registry_cli.registry, "prune", lambda repos, *args, **kwargs: seen.append(repos) or 0)

        result = CliRunner().invoke(app, ["registry", "prune", "--apps", given, "--dry-run"])

        assert result.exit_code == 0, result.output
        assert seen == [{}]
