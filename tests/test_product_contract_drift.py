"""The committed contract snapshots and the values they render to never drift apart (IDP-042 AC3).

Under Q2 a contract renders into ``apps.platform.<app>`` in ``values/<env>.yaml``.
A key the contract owns that someone edits by hand, or a snapshot edited so it
no longer validates, must fail here rather than at the next deploy. No SOPS and
no network: the values files and the snapshot are plain YAML in the tree.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from click.testing import Result
from typer.testing import CliRunner

from toolkit.features import product_render
from toolkit.features.product_contract import ContractError, validate_contract
from toolkit.features.product_render import CONTRACT_KEYS, SNAPSHOT_DIR, VALUES_DIR, drift, write
from toolkit.main import app

WEB = SNAPSHOT_DIR / "web.yaml"
ENVS = ("staging", "prod")


@pytest.mark.parametrize("env", ENVS)
def test_the_web_snapshot_matches_the_values(env: str, capsys: pytest.CaptureFixture[str]) -> None:
    differences, compared = drift(validate_contract(WEB), "web", env)
    print(f"compared {compared} contract-owned keys for web/{env}")

    assert not differences, f"web/{env}: {differences}"
    assert compared == len(CONTRACT_KEYS)
    assert f"compared {len(CONTRACT_KEYS)} contract-owned keys" in capsys.readouterr().out


def test_an_empty_mapping_is_refused_not_reported_clean() -> None:
    """A comparison of nothing would pass every time; it must fail instead."""
    with pytest.raises(ValueError, match="no contract-owned keys"):
        drift(validate_contract(WEB), "web", "staging", mapping={})


@pytest.fixture
def values_copy(tmp_path: Path) -> Path:
    shutil.copytree(VALUES_DIR, tmp_path / "values")
    return tmp_path / "values"


def _edit_web(values_dir: Path, env: str, key: str, value: object) -> None:
    path = values_dir / f"{env}.yaml"
    data = yaml.safe_load(path.read_text())
    data["apps"]["platform"]["web"][key] = value
    path.write_text(yaml.safe_dump(data))


def test_a_derived_key_edited_by_hand_is_drift(values_copy: Path) -> None:
    _edit_web(values_copy, "prod", "default_port", 9090)

    differences, _ = drift(validate_contract(WEB), "web", "prod", values_dir=values_copy)

    assert differences == {"default_port": (8080, 9090)}


def test_a_snapshot_that_no_longer_validates_is_refused(tmp_path: Path) -> None:
    broken = tmp_path / "web.yaml"
    broken.write_text(WEB.read_text().replace("port: 8080", "port: '8080'"))

    with pytest.raises(ContractError):
        validate_contract(broken)


def test_write_restores_the_contract_keys_and_never_touches_version(values_copy: Path) -> None:
    _edit_web(values_copy, "prod", "default_port", 9090)
    before = yaml.safe_load((values_copy / "prod.yaml").read_text())["apps"]["platform"]["web"]["version"]

    changed = write(validate_contract(WEB), "web", "prod", values_dir=values_copy)

    assert changed == ["default_port"]
    after = yaml.safe_load((values_copy / "prod.yaml").read_text())["apps"]["platform"]["web"]
    assert after["default_port"] == 8080
    assert after["version"] == before
    assert drift(validate_contract(WEB), "web", "prod", values_dir=values_copy)[0] == {}


def test_write_on_a_clean_tree_changes_nothing(values_copy: Path) -> None:
    original = (values_copy / "staging.yaml").read_text()

    assert write(validate_contract(WEB), "web", "staging", values_dir=values_copy) == []
    assert (values_copy / "staging.yaml").read_text() == original


def test_write_inserts_a_missing_key_before_version_and_changes_nothing_else(values_copy: Path) -> None:
    """A key right only in common.yaml is corrected in the env file, beside its siblings."""
    _edit_web(values_copy, "common", "health_path", "/elsewhere")
    original = (values_copy / "prod.yaml").read_text().splitlines()

    assert write(validate_contract(WEB), "web", "prod", values_dir=values_copy) == ["health_path"]

    updated = (values_copy / "prod.yaml").read_text().splitlines()
    added = [line for line in updated if line not in original]
    assert [line.strip() for line in added] == ["health_path: /"]
    assert len(updated) == len(original) + 1
    position = updated.index(added[0])
    assert updated[position + 1].strip().startswith("version:")


def _render(*args: str) -> Result:
    return CliRunner().invoke(app, ["product", "render", "--contract", str(WEB), *args])


@pytest.mark.parametrize("env", ENVS)
def test_render_check_passes_on_the_committed_tree(env: str) -> None:
    result = _render("--env", env, "--check")

    assert result.exit_code == 0, result.output
    assert f"compared {len(CONTRACT_KEYS)} contract-owned keys for web/{env}" in result.output


def test_render_check_exits_one_and_names_the_drifted_keys(values_copy: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _edit_web(values_copy, "prod", "default_port", 9090)
    monkeypatch.setattr(product_render, "VALUES_DIR", values_copy)

    result = _render("--env", "prod", "--check")

    assert result.exit_code == 1
    assert "default_port" in result.output


def test_render_refuses_oidc(tmp_path: Path) -> None:
    contract = tmp_path / "web.yaml"
    contract.write_text(WEB.read_text().replace("auth: public", "auth: oidc"))

    result = CliRunner().invoke(app, ["product", "render", "--contract", str(contract), "--env", "prod"])

    assert result.exit_code == 1
    assert "ERROR:" in result.output
    assert "oidc" in result.output


def test_render_takes_check_or_write_not_both() -> None:
    assert _render("--env", "prod", "--check", "--write").exit_code == 2
