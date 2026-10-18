"""``toolkit product validate`` (IDP-042 PR 1): offline, no SOPS key, no network."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from toolkit.main import app

FIXTURE = Path(__file__).parent / "fixtures" / "product" / "web.kubelab.yaml"
runner = CliRunner()


def _invalid(tmp_path: Path) -> Path:
    path = tmp_path / "kubelab.yaml"
    path.write_text(FIXTURE.read_text().replace("port: 8080", "port: 0"))
    return path


def test_a_valid_contract_exits_zero() -> None:
    result = runner.invoke(app, ["product", "validate", "--contract", str(FIXTURE)])

    assert result.exit_code == 0, result.output


def test_a_valid_contract_as_json() -> None:
    result = runner.invoke(app, ["product", "validate", "--contract", str(FIXTURE), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["contract"] == str(FIXTURE)
    assert payload["schema_version"] == 1


def test_an_invalid_contract_exits_one_with_error_why_fix(tmp_path: Path) -> None:
    path = _invalid(tmp_path)

    result = runner.invoke(app, ["product", "validate", "--contract", str(path)])

    assert result.exit_code == 1
    lines = result.stderr.splitlines()
    assert [line.split(":", 1)[0] for line in lines] == ["ERROR", "WHY", "FIX"]
    assert str(path) in lines[0] and "port" in lines[0]


def test_an_invalid_contract_as_json(tmp_path: Path) -> None:
    path = _invalid(tmp_path)

    result = runner.invoke(app, ["product", "validate", "--contract", str(path), "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert set(payload) == {"ok", "error", "why", "fix"}
    assert "port" in payload["error"]


REGISTRY = Path(__file__).resolve().parents[1] / "infra" / "config" / "products.yaml"


def test_validate_against_the_registry_exits_zero_for_web() -> None:
    result = runner.invoke(
        app, ["product", "validate", "--contract", str(FIXTURE), "--registry", str(REGISTRY), "--app", "web"]
    )

    assert result.exit_code == 0, result.output


def test_validate_against_the_registry_refuses_an_in_tree_product() -> None:
    result = runner.invoke(
        app, ["product", "validate", "--contract", str(FIXTURE), "--registry", str(REGISTRY), "--app", "api", "--json"]
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["ok"] is False


def test_registry_without_app_is_a_usage_error() -> None:
    result = runner.invoke(app, ["product", "validate", "--contract", str(FIXTURE), "--registry", str(REGISTRY)])

    assert result.exit_code == 2
