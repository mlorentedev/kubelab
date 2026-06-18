"""Tests for promotion — the image-version promote primitive (ADR-046 D6)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from toolkit.features import promotion, registry

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
    path.write_text(body)
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

        assert "version: 1.2.0" in values.read_text()
        generator.return_value.generate.assert_called_once_with("staging")

    def test_preserves_comments(self, env_patched, monkeypatch) -> None:
        root, _ = env_patched
        values = _write_values(root)
        _mock_registry(monkeypatch, 200)

        promotion.promote("staging", "web", "1.2.0")

        text = values.read_text()
        assert "# top-of-file comment must survive a round-trip edit" in text
        assert "# inline comment must survive too" in text

    def test_rejects_missing_tag(self, env_patched, monkeypatch) -> None:
        root, generator = env_patched
        _write_values(root)
        _mock_registry(monkeypatch, 404)

        with pytest.raises(ValueError, match="not found"):
            promotion.promote("staging", "web", "9.9.9")
        generator.return_value.generate.assert_not_called()

    def test_rejects_non_platform_app(self, env_patched) -> None:
        with pytest.raises(ValueError, match="not a platform app"):
            promotion.promote("staging", "errors", "1.1.1")

    def test_rejects_dev_env(self, env_patched) -> None:
        with pytest.raises(ValueError, match="staging|prod"):
            promotion.promote("dev", "web", "1.2.0")
