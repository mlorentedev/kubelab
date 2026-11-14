"""Tests for promotion — the image-version promote primitive (ADR-046 D6)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from toolkit.features import platform_manifest, product_registry, promotion, registry

_VALUES = """\
# top-of-file comment must survive a round-trip edit
apps:
  platform:
    web:
      image_name: kubelab-web  # inline comment must survive too
      domain: staging.mlorente.dev
"""


def _write_values(root: Path, body: str = _VALUES) -> Path:
    values_dir = root / "infra" / "config" / "values"
    values_dir.mkdir(parents=True, exist_ok=True)
    path = values_dir / "staging.yaml"
    path.write_text(body, encoding="utf-8", newline="\n")
    return path


@pytest.fixture
def env_patched(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, MagicMock]:
    """Patch project_root, ConfigurationManager and the generator; return (root, generator mock)."""
    monkeypatch.setattr(promotion, "settings", MagicMock(project_root=tmp_path))

    cm = MagicMock()
    cm.return_value.get_env_vars.return_value = {
        "REGISTRY": "docker.io/mlorentedev",
        "APPS_PLATFORM_WEB_IMAGE_NAME": "kubelab-web",
    }
    monkeypatch.setattr(promotion, "ConfigurationManager", cm)

    generator = MagicMock()
    monkeypatch.setattr(promotion, "K8sGenerator", generator)
    return tmp_path, generator


def _mock_registry(monkeypatch: pytest.MonkeyPatch, status_code: int) -> None:
    # The tag-existence check now lives in the registry module (promotion reuses it).
    monkeypatch.setattr(registry.httpx, "get", MagicMock(return_value=MagicMock(status_code=status_code)))


class TestPromote:
    def test_sets_version_and_regenerates(self, env_patched, monkeypatch) -> None:
        root, generator = env_patched
        values = _write_values(root)
        _mock_registry(monkeypatch, 200)

        promotion.promote("staging", "web", "1.2.0")

        assert "version: 1.2.0" in values.read_text(encoding="utf-8")
        generator.return_value.generate.assert_called_once_with("staging")

    def test_preserves_comments(self, env_patched, monkeypatch) -> None:
        root, _ = env_patched
        values = _write_values(root)
        _mock_registry(monkeypatch, 200)

        promotion.promote("staging", "web", "1.2.0")

        text = values.read_text(encoding="utf-8")
        assert "# top-of-file comment must survive a round-trip edit" in text
        assert "# inline comment must survive too" in text

    def test_first_promotion_does_not_land_under_a_following_comment(self, env_patched, monkeypatch) -> None:
        """A brand-new pin goes inside its block, not below the next section's comment.

        ruamel attaches a comment that follows a block to the block's LAST key, so
        appending a key renders it *after* that comment. The round-trip then
        preserves the wrong position forever — which is how prod's web pin came to
        sit under `# Third-party services` (GITOPS-004). Only the FIRST promotion
        of an app can do this; later ones rewrite an existing key in place, which
        is why this went unnoticed across eleven releases.
        """
        root, _ = env_patched
        values = _write_values(
            root,
            "apps:\n"
            "  platform:\n"
            "    web:\n"
            "      image_name: kubelab-web\n"
            "      domain: staging.mlorente.dev\n"
            "\n"
            "  # Third-party services\n"
            "  services:\n"
            "    core: {}\n",
        )
        _mock_registry(monkeypatch, 200)

        promotion.promote("staging", "web", "1.2.0")

        lines = values.read_text(encoding="utf-8").splitlines()
        version_at = next(i for i, line in enumerate(lines) if line.strip() == "version: 1.2.0")
        comment_at = next(i for i, line in enumerate(lines) if "Third-party services" in line)

        assert version_at < comment_at, "the new pin rendered below the next section's comment:\n" + "\n".join(lines)
        # And it is inside the app block, not promoted a level out.
        assert lines[version_at].startswith("      "), lines[version_at]
        assert lines[comment_at + 1].strip() == "services:", (
            "the comment no longer sits with the section it describes:\n" + "\n".join(lines)
        )

    def test_rejects_missing_tag(self, env_patched, monkeypatch) -> None:
        root, generator = env_patched
        _write_values(root)
        _mock_registry(monkeypatch, 404)

        with pytest.raises(ValueError, match="not found"):
            promotion.promote("staging", "web", "9.9.9")
        generator.return_value.generate.assert_not_called()

    def test_rejects_non_platform_app(self, env_patched) -> None:
        # errors is now a valid target (DELIVERY-003); other edge services are not.
        with pytest.raises(ValueError, match="not a platform app"):
            promotion.promote("staging", "traefik", "1.1.1")

    def test_rejects_dev_env(self, env_patched) -> None:
        with pytest.raises(ValueError, match="staging|prod"):
            promotion.promote("dev", "web", "1.2.0")


FIXTURE_REGISTRY = Path(__file__).parent / "fixtures" / "product" / "registry.yaml"


class TestPromoteReadsTheRegistry:
    """#1815: the apps ``promote`` accepts are the registry's, not a literal tuple."""

    @pytest.fixture(autouse=True)
    def _fixture_registry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(product_registry, "registry_path", lambda: FIXTURE_REGISTRY)

    def test_promotes_a_registered_product_other_than_api_and_web(self, env_patched, monkeypatch) -> None:
        root, generator = env_patched
        values = _write_values(root)
        promotion.ConfigurationManager.return_value.get_env_vars.return_value["APPS_PLATFORM_THIRD_IMAGE_NAME"] = (
            "third"
        )
        _mock_registry(monkeypatch, 200)

        promotion.promote("staging", "third", "sha-abc1234")

        third = yaml.safe_load(values.read_text(encoding="utf-8"))["apps"]["platform"]["third"]
        assert third["version"] == "sha-abc1234"
        generator.return_value.generate.assert_called_once_with("staging")

    def test_refuses_an_unregistered_product_naming_the_registry(self, env_patched) -> None:
        root, generator = env_patched
        _write_values(root)

        with pytest.raises(ValueError, match=r"ghost.*fixtures/product/registry\.yaml"):
            promotion.promote("staging", "ghost", "sha-abc1234")
        generator.return_value.generate.assert_not_called()

    def test_resolve_image_sha_accepts_a_registered_product(self, env_patched) -> None:
        root, _ = env_patched
        _write_values(root, "apps:\n  platform:\n    third:\n      version: sha-abc1234\n")

        assert promotion.resolve_image_sha("staging", "third") == "sha-abc1234"

    def test_resolve_image_sha_refuses_an_unregistered_product(self, env_patched) -> None:
        with pytest.raises(ValueError, match=r"ghost.*fixtures/product/registry\.yaml"):
            promotion.resolve_image_sha("staging", "ghost")


class TestPromoteUsesTheEntrysRegistry:
    """IDP-053 AC2: the tag is looked up where the entry says its image lives, else in the platform registry."""

    _REGISTRY = (
        "products:\n"
        "  beta:\n"
        "    repository: personal/beta\n"
        "    forge: gitea\n"
        "    receiver: generic\n"
        "    image_registry: gitea.kubelab.live/personal\n"
        "    private: true\n"
        "    pull_credential: {username: reviewer, secret: gitea.registry_pull}\n"
        "    events: {staging: beta-image-published}\n"
    )

    def _promote(self, env_patched, monkeypatch, tmp_path: Path, registry_body: str, app: str) -> MagicMock:
        root, _ = env_patched
        _write_values(root)
        path = tmp_path / "products.yaml"
        path.write_text(registry_body, encoding="utf-8", newline="\n")
        monkeypatch.setattr(product_registry, "registry_path", lambda: path)
        promotion.ConfigurationManager.return_value.get_env_vars.return_value[
            f"APPS_PLATFORM_{app.upper()}_IMAGE_NAME"
        ] = app
        exists = MagicMock(return_value=True)
        monkeypatch.setattr(promotion, "tag_exists", exists)
        promotion.promote("staging", app, "sha-0123456789ab")
        return exists

    def test_a_product_with_an_image_registry_is_checked_there(self, env_patched, monkeypatch, tmp_path) -> None:
        exists = self._promote(env_patched, monkeypatch, tmp_path, self._REGISTRY, "beta")

        exists.assert_called_once_with("gitea.kubelab.live/personal", "beta", "sha-0123456789ab")

    def test_a_product_without_one_is_checked_in_the_platform_registry(
        self, env_patched, monkeypatch, tmp_path
    ) -> None:
        body = self._REGISTRY.replace("    image_registry: gitea.kubelab.live/personal\n    private: true\n", "")
        body = body.replace("    pull_credential: {username: reviewer, secret: gitea.registry_pull}\n", "")

        exists = self._promote(env_patched, monkeypatch, tmp_path, body, "beta")

        exists.assert_called_once_with("docker.io/mlorentedev", "beta", "sha-0123456789ab")


def _prod_residue(registry_path: Path, prod_values: Path, prod_snapshots: Path) -> list[str]:
    """What a product without a prod lane leaves in prod: a values block (with or without a pin) or a snapshot."""
    prod = yaml.safe_load(prod_values.read_text(encoding="utf-8")) or {}
    blocks = ((prod.get("apps") or {}).get("platform")) or {}
    found = []
    for app in product_registry.load_registry(registry_path).products:
        if promotion.has_prod_lane(app, registry_path):
            continue
        if app in blocks:
            found.append(f"{app}: apps.platform.{app} in {prod_values.name}")
        if (prod_snapshots / f"{app}.yaml").exists():
            found.append(f"{app}: {prod_snapshots.name}/{app}.yaml")
    return found


class TestProdLane:
    """IDP-053 D5: ``events.prod`` is the declaration of a prod lane; without it prod is closed."""

    @pytest.fixture(autouse=True)
    def _fixture_registry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(product_registry, "registry_path", lambda: FIXTURE_REGISTRY)

    def test_promote_to_prod_is_refused_for_a_product_with_no_events_prod(self, env_patched, monkeypatch) -> None:
        root, generator = env_patched
        exists = MagicMock(return_value=True)
        monkeypatch.setattr(promotion, "tag_exists", exists)

        with pytest.raises(ValueError, match=r"(?s)ERROR:.*third.*events\.prod.*WHY:.*FIX:"):
            promotion.promote("prod", "third", "1.0.0")

        exists.assert_not_called()
        generator.return_value.generate.assert_not_called()

    def test_the_same_product_still_promotes_to_staging(self, env_patched, monkeypatch) -> None:
        root, generator = env_patched
        _write_values(root)
        promotion.ConfigurationManager.return_value.get_env_vars.return_value["APPS_PLATFORM_THIRD_IMAGE_NAME"] = (
            "third"
        )
        monkeypatch.setattr(promotion, "tag_exists", MagicMock(return_value=True))

        promotion.promote("staging", "third", "sha-abc1234")

        generator.return_value.generate.assert_called_once_with("staging")

    def test_a_product_that_declares_events_prod_and_an_in_tree_one_have_a_lane(self) -> None:
        assert promotion.has_prod_lane("web")
        assert promotion.has_prod_lane("api")  # in-tree: released, never dispatched, so it declares no events
        assert not promotion.has_prod_lane("third")

    def test_the_committed_prod_state_holds_nothing_for_a_product_without_a_lane(self) -> None:
        root = Path(__file__).resolve().parents[1]
        residue = _prod_residue(
            root / "infra" / "config" / "products.yaml",
            root / "infra" / "config" / "values" / "prod.yaml",
            root / "infra" / "config" / "products" / "contracts" / "prod",
        )
        assert residue == []

    @pytest.mark.parametrize("block", ["third: {domain: third.example.test}", "third: {version: 1.0.0}"])
    def test_a_prod_values_block_for_it_is_found_pinned_or_not(self, tmp_path: Path, block: str) -> None:
        """Unpinned it would deploy ``:latest``; pinned it would run without a lane: both are findings."""
        values = tmp_path / "prod.yaml"
        values.write_text(f"apps:\n  platform:\n    {block}\n", encoding="utf-8", newline="\n")

        assert _prod_residue(FIXTURE_REGISTRY, values, tmp_path / "snapshots") == [
            "third: apps.platform.third in prod.yaml"
        ]

    def test_a_prod_snapshot_for_it_is_found(self, tmp_path: Path) -> None:
        values = tmp_path / "prod.yaml"
        values.write_text("apps:\n  platform:\n    web: {version: 1.0.0}\n", encoding="utf-8", newline="\n")
        snapshots = tmp_path / "snapshots"
        snapshots.mkdir()
        (snapshots / "third.yaml").write_text("{}", encoding="utf-8", newline="\n")

        assert _prod_residue(FIXTURE_REGISTRY, values, snapshots) == ["third: snapshots/third.yaml"]


_COMMON = """\
# common values
registry: docker.io/mlorentedev
edge:
  errors:
    image_name: kubelab-errors
    version: "1.1.1"  # SSOT for the errors image tag
"""


# common.yaml mixes indented and flush block sequences and carries lines longer
# than ruamel's default width. No ruamel dump config reproduces both, so a
# round-trip rewrote ~250 lines of the real file on every promotion (#2430).
_COMMON_MIXED = """\
# common values
registry: docker.io/mlorentedev
ci:
  required_contexts:
    - Validate
    - Tests
edge:
  errors:
    image_name: kubelab-errors
    version: "1.1.1"  # SSOT for the errors image tag
    coverage:
      exceptions:
        - route: headscale
          reason: "Tailscale control protocol (Noise); a branded page is not a valid response"
networking:
  zones:
  - staging.kubelab.live
"""


class TestPromoteErrors:
    """errors rides the single-SSOT sync lane, not the per-env overlay (DELIVERY-003)."""

    @pytest.fixture(autouse=True)
    def _platform_manifest(self, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
        # Never let a test reach the real generator: its default paths are the repo's own files.
        self.manifest_sync = MagicMock(return_value=0)
        monkeypatch.setattr(platform_manifest, "sync", self.manifest_sync)
        return self.manifest_sync

    def _write_common(self, root: Path, body: str = _COMMON) -> Path:
        d = root / "infra" / "config" / "values"
        d.mkdir(parents=True, exist_ok=True)
        path = d / "common.yaml"
        path.write_text(body, encoding="utf-8", newline="\n")
        return path

    def test_changes_only_the_version_line(self, env_patched, monkeypatch) -> None:
        root, _ = env_patched
        common = self._write_common(root, _COMMON_MIXED)
        monkeypatch.setattr(promotion, "tag_exists", MagicMock(return_value=True))
        monkeypatch.setattr(promotion.sync_k8s_images, "sync", MagicMock(return_value=0))

        promotion.promote("prod", "errors", "1.2.0")

        expected = _COMMON_MIXED.replace('version: "1.1.1"', 'version: "1.2.0"')
        assert common.read_text(encoding="utf-8") == expected

    def test_regenerates_platform_manifest(self, env_patched, monkeypatch) -> None:
        # platform.json records common.yaml's blob hash, so any edit to it is drift
        # until the manifest is regenerated in the same change.
        root, _ = env_patched
        common = self._write_common(root)
        monkeypatch.setattr(promotion, "tag_exists", MagicMock(return_value=True))
        monkeypatch.setattr(promotion.sync_k8s_images, "sync", MagicMock(return_value=0))

        promotion.promote("prod", "errors", "1.2.0")

        self.manifest_sync.assert_called_once_with(
            output_path=root / "infra" / "config" / "platform.json", config_path=common
        )

    def test_writes_exactly_the_files_it_declares(self, env_patched, monkeypatch) -> None:
        # release.yml stages ERRORS_PROMOTION_FILES; a file promote writes outside
        # that list reaches the runner's tree and never the PR (#2552).
        # Observed on disk, not from the mocks' arguments, so a direct write in
        # _promote_errors counts too (#2568 review).
        root, _ = env_patched
        self._write_common(root)
        monkeypatch.setattr(promotion, "tag_exists", MagicMock(return_value=True))

        def _writes(path: Path) -> int:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synced\n", encoding="utf-8", newline="\n")
            return 0

        monkeypatch.setattr(promotion.sync_k8s_images, "sync", lambda _common, out: _writes(out))
        self.manifest_sync.side_effect = lambda output_path, config_path: _writes(output_path)

        def _tree() -> dict[str, bytes]:
            return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}

        before = _tree()
        promotion.promote("prod", "errors", "1.2.0")
        after = _tree()

        changed = {p for p in after if before.get(p) != after[p]}
        assert changed == set(promotion.ERRORS_PROMOTION_FILES)

    def test_refuses_a_missing_version_key(self, env_patched, monkeypatch) -> None:
        root, _ = env_patched
        body = _COMMON.replace('    version: "1.1.1"  # SSOT for the errors image tag\n', "")
        common = self._write_common(root, body)
        monkeypatch.setattr(promotion, "tag_exists", MagicMock(return_value=True))

        with pytest.raises(ValueError, match="edge.errors.version"):
            promotion.promote("prod", "errors", "1.2.0")
        assert common.read_text(encoding="utf-8") == body

    @pytest.mark.parametrize("value", ['""', ""])
    def test_refuses_an_empty_version(self, env_patched, monkeypatch, value: str) -> None:
        root, _ = env_patched
        body = _COMMON.replace('"1.1.1"', value)
        common = self._write_common(root, body)
        monkeypatch.setattr(promotion, "tag_exists", MagicMock(return_value=True))

        with pytest.raises(ValueError, match="missing or empty"):
            promotion.promote("prod", "errors", "1.2.0")
        assert common.read_text(encoding="utf-8") == body

    def test_a_retry_at_the_same_version_still_resyncs(self, env_patched, monkeypatch) -> None:
        # A run whose sync failed already wrote the SSOT; the retry must repair the derived files.
        root, _ = env_patched
        common = self._write_common(root)
        monkeypatch.setattr(promotion, "tag_exists", MagicMock(return_value=True))
        k8s_sync = MagicMock(return_value=0)
        monkeypatch.setattr(promotion.sync_k8s_images, "sync", k8s_sync)

        promotion.promote("prod", "errors", "1.1.1")

        assert common.read_text(encoding="utf-8") == _COMMON
        k8s_sync.assert_called_once()
        self.manifest_sync.assert_called_once()

    @pytest.mark.parametrize("failing", ["kustomization", "manifest"])
    def test_a_failed_sync_fails_the_promotion(self, env_patched, monkeypatch, failing: str) -> None:
        root, _ = env_patched
        self._write_common(root)
        monkeypatch.setattr(promotion, "tag_exists", MagicMock(return_value=True))
        monkeypatch.setattr(
            promotion.sync_k8s_images, "sync", MagicMock(return_value=1 if failing == "kustomization" else 0)
        )
        self.manifest_sync.return_value = 1 if failing == "manifest" else 0

        with pytest.raises(RuntimeError, match="errors set to 1.2.0"):
            promotion.promote("prod", "errors", "1.2.0")

    def test_writes_edge_version_and_syncs(self, env_patched, monkeypatch) -> None:
        root, generator = env_patched
        common = self._write_common(root)
        monkeypatch.setattr(promotion, "tag_exists", MagicMock(return_value=True))
        sync_mock = MagicMock(return_value=0)
        monkeypatch.setattr(promotion.sync_k8s_images, "sync", sync_mock)

        promotion.promote("prod", "errors", "1.2.0")

        text = common.read_text(encoding="utf-8")
        assert 'version: "1.2.0"' in text
        assert "# SSOT for the errors image tag" in text  # comment survives round-trip
        sync_mock.assert_called_once()
        # errors must NOT touch the per-env overlay generator (that is api/web's lane).
        generator.return_value.generate.assert_not_called()

    def test_rejects_missing_tag(self, env_patched, monkeypatch) -> None:
        root, _ = env_patched
        self._write_common(root)
        monkeypatch.setattr(promotion, "tag_exists", MagicMock(return_value=False))
        sync_mock = MagicMock()
        monkeypatch.setattr(promotion.sync_k8s_images, "sync", sync_mock)

        with pytest.raises(ValueError, match="not found"):
            promotion.promote("prod", "errors", "9.9.9")
        sync_mock.assert_not_called()

    def test_errors_ignores_env(self, env_patched, monkeypatch) -> None:
        # Single SSOT in common.yaml: errors promotion is env-agnostic, so even
        # env="dev" (no K8s overlay) is valid — unlike platform apps.
        root, _ = env_patched
        common = self._write_common(root)
        monkeypatch.setattr(promotion, "tag_exists", MagicMock(return_value=True))
        monkeypatch.setattr(promotion.sync_k8s_images, "sync", MagicMock(return_value=0))

        promotion.promote("dev", "errors", "2.0.0")
        assert 'version: "2.0.0"' in common.read_text(encoding="utf-8")
