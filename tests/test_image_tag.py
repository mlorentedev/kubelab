"""Tests for the build-once sha resolver (DELIVERY-002 / ADR-056).

The resolver reads the staging-validated immutable ``sha-<short>`` pinned in
``values/staging.yaml`` so release.yml can re-tag that exact digest as the prod
semver — never a rebuild. Pure file read: no registry, no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from toolkit.features import promotion

_VALUES_TEMPLATE = """\
apps:
  platform:
    api:
{api_version}
    web:
      version: sha-c8fa9a6
"""


def _write_values(root: Path, api_version: str) -> Path:
    values_dir = root / "infra" / "config" / "values"
    values_dir.mkdir(parents=True, exist_ok=True)
    path = values_dir / "staging.yaml"
    indented = f"      version: {api_version}" if api_version else "      domain: api.staging"
    path.write_text(_VALUES_TEMPLATE.format(api_version=indented))
    return path


@pytest.fixture
def root_patched(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(promotion, "settings", type("S", (), {"project_root": tmp_path}))
    return tmp_path


class TestResolveImageSha:
    def test_returns_pinned_sha(self, root_patched, monkeypatch) -> None:
        _write_values(root_patched, "sha-abc1234")
        # No registry mock: a network call here would raise — proving the resolver is offline.
        assert promotion.resolve_image_sha("staging", "api") == "sha-abc1234"

    def test_reads_per_app_pin(self, root_patched) -> None:
        _write_values(root_patched, "sha-abc1234")
        assert promotion.resolve_image_sha("staging", "web") == "sha-c8fa9a6"

    def test_errors_on_missing_pin(self, root_patched) -> None:
        _write_values(root_patched, "")  # api has no version key -> not validated
        with pytest.raises(ValueError, match="No staging-pinned|sha-<short>"):
            promotion.resolve_image_sha("staging", "api")

    def test_errors_on_dev_pin(self, root_patched) -> None:
        _write_values(root_patched, "dev")
        with pytest.raises(ValueError, match="not an immutable sha"):
            promotion.resolve_image_sha("staging", "api")

    def test_errors_on_semver_pin(self, root_patched) -> None:
        _write_values(root_patched, "1.2.0")
        with pytest.raises(ValueError, match="not an immutable sha"):
            promotion.resolve_image_sha("staging", "api")

    def test_errors_on_non_platform_app(self, root_patched) -> None:
        _write_values(root_patched, "sha-abc1234")
        with pytest.raises(ValueError, match="not a platform app"):
            promotion.resolve_image_sha("staging", "errors")
