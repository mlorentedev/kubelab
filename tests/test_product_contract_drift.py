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
from toolkit.features.product_guards import validate_registered
from toolkit.features.product_registry import load_registry
from toolkit.features.product_render import (
    CONTRACT_KEYS,
    SNAPSHOT_DIR,
    VALUES_DIR,
    drift,
    snapshot_exempt,
    snapshot_gaps,
    write,
)
from toolkit.main import app

WEB = SNAPSHOT_DIR / "web.yaml"
ENVS = ("staging", "prod")

#: Pinned here, not read from CONTRACT_KEYS: a mapping that lost an entry would
#: otherwise compare one key fewer and still report "all compared".
OWNED_KEYS = {"default_port", "health_path", "domain", "enable_auth", "auth_level", "image_name"}


@pytest.mark.parametrize("env", ENVS)
def test_the_web_snapshot_matches_the_values(env: str, capsys: pytest.CaptureFixture[str]) -> None:
    differences, compared = drift(validate_contract(WEB), "web", env)
    print(f"compared {compared} contract-owned keys for web/{env}")

    assert not differences, f"web/{env}: {differences}"
    assert set(CONTRACT_KEYS) == OWNED_KEYS
    assert compared == len(OWNED_KEYS)
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

    result = CliRunner().invoke(app, ["product", "render", "--contract", str(contract), "--env", "prod", "--app", "web"])

    assert result.exit_code == 1
    assert "ERROR:" in result.output
    assert "oidc" in result.output


def test_render_takes_check_or_write_not_both() -> None:
    assert _render("--env", "prod", "--check", "--write").exit_code == 2


FIXTURE_REGISTRY = Path(__file__).parent / "fixtures" / "product" / "registry.yaml"


def test_every_contract_managed_entry_has_a_snapshot_and_every_snapshot_an_entry() -> None:
    assert snapshot_gaps() == ([], [])


def test_every_committed_snapshot_passes_the_registry_guards() -> None:
    """A registry edit (image override, an entry turned in-tree) that no snapshot follows is drift too."""
    for snapshot in sorted(SNAPSHOT_DIR.glob("*.yaml")):
        validate_registered(snapshot, snapshot.stem)


def test_a_contract_managed_entry_without_a_snapshot_is_drift(tmp_path: Path) -> None:
    """Fixture registry: `api` in-tree, `web` and `third` on GitHub; only web has a snapshot."""
    shutil.copy(WEB, tmp_path / "web.yaml")

    missing, orphaned = snapshot_gaps(FIXTURE_REGISTRY, tmp_path)

    assert missing == ["third"]
    assert orphaned == []


def test_a_snapshot_without_a_contract_managed_entry_is_drift(tmp_path: Path) -> None:
    for name in ("web", "third", "ghost", "api"):
        shutil.copy(WEB, tmp_path / f"{name}.yaml")

    assert snapshot_gaps(FIXTURE_REGISTRY, tmp_path) == ([], ["api", "ghost"])


def test_the_exempt_set_is_exactly_the_in_tree_entries() -> None:
    products = load_registry(FIXTURE_REGISTRY).products
    in_tree = {name for name, product in products.items() if product.forge == "in-tree"}

    assert snapshot_exempt(FIXTURE_REGISTRY) == in_tree == {"api"}


def test_write_refuses_an_app_with_no_values_block(values_copy: Path) -> None:
    """--check reports six drifts here; --write must refuse with ERROR / WHY / FIX, not raise KeyError."""
    path = values_copy / "prod.yaml"
    data = yaml.safe_load(path.read_text())
    del data["apps"]["platform"]["web"]
    path.write_text(yaml.safe_dump(data))

    assert drift(validate_contract(WEB), "web", "prod", values_dir=values_copy)[1] == len(OWNED_KEYS)
    with pytest.raises(ContractError) as excinfo:
        write(validate_contract(WEB), "web", "prod", values_dir=values_copy)
    assert [line.split(":", 1)[0] for line in str(excinfo.value).splitlines()] == ["ERROR", "WHY", "FIX"]
    assert "apps.platform.web" in excinfo.value.error


def test_render_needs_app_for_a_contract_outside_the_snapshots(tmp_path: Path) -> None:
    """A product repository's file is kubelab.yaml; its stem names no app."""
    contract = tmp_path / "kubelab.yaml"
    shutil.copy(WEB, contract)

    def invoke(*args: str) -> Result:
        return CliRunner().invoke(app, ["product", "render", "--contract", str(contract), "--env", "prod", *args])

    assert invoke("--check").exit_code == 2
    assert invoke("--check", "--app", "web").exit_code == 0


def test_every_auth_level_in_the_values_is_one_the_contract_can_render() -> None:
    """`forwardauth` renders as one_factor; a stronger policy in the values would be lowered by --write."""
    renderable = set(product_render._AUTH_LEVEL.values())
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("auth_level"), str):
                found.add(node["auth_level"])
            for child in node.values():
                walk(child)

    for env_file in VALUES_DIR.glob("*.yaml"):
        walk((yaml.safe_load(env_file.read_text()) or {}).get("apps"))

    assert {"bypass", "one_factor"} <= found
    assert found <= renderable, f"auth levels the contract cannot express: {found - renderable}"


def test_the_committed_registry_exempts_exactly_its_in_tree_entries() -> None:
    products = load_registry().products

    assert snapshot_exempt() == {name for name, product in products.items() if product.forge == "in-tree"}
