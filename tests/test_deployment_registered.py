"""`toolkit deployment registered`: whether the product registry carries an app.

staging-deploy.yml asks it before promoting. An app the registry does not carry yet has
nothing to promote into, so CI stops green with a notice; the answer comes from
infra/config/products.yaml and from nothing else, so registering the app is the whole switch.
A registry that cannot be read must fail rather than answer "false", or a broken file would
turn every deploy lane into a silent no-op.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from toolkit.cli import deployment
from toolkit.features import product_registry

_REGISTRY = """\
products:
  api:
    forge: in-tree
"""


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "products.yaml"
    path.write_text(_REGISTRY, encoding="utf-8")
    monkeypatch.setattr(product_registry, "registry_path", lambda: path)
    return path


def _ask(app: str):
    return CliRunner().invoke(deployment.app, ["registered", "--app", app])


def test_a_registered_app_is_true(registry: Path) -> None:
    result = _ask("api")
    assert result.exit_code == 0
    assert result.stdout.strip() == "true"


def test_an_app_the_registry_does_not_carry_is_false_and_not_a_failure(registry: Path) -> None:
    result = _ask("console")
    assert result.exit_code == 0
    assert result.stdout.strip() == "false"


def test_registering_the_app_is_the_whole_switch(registry: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same command, same checkout: only the registry file changes, and the answer follows it."""
    assert _ask("console").stdout.strip() == "false"
    other = registry.parent / "registered.yaml"
    other.write_text(_REGISTRY + "  console:\n    forge: in-tree\n", encoding="utf-8")
    monkeypatch.setattr(product_registry, "registry_path", lambda: other)
    assert _ask("console").stdout.strip() == "true"


def test_a_registry_that_cannot_be_read_fails_instead_of_answering_false(
    registry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry.write_text("products: [not, a, mapping]\n", encoding="utf-8")
    result = _ask("api")
    assert result.exit_code == 1
    assert "false" not in result.stdout
