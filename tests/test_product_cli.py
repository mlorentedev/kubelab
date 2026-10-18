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
