"""``toolkit product validate`` (IDP-042 PR 1): offline, no SOPS key, no network."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from toolkit.features import product_registry
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


# --- the registry adapters (IDP-042 PR 5) -------------------------------------

FIXTURE_REGISTRY = Path(__file__).parent / "fixtures" / "product" / "registry.yaml"


@pytest.fixture
def fixture_registry(monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(product_registry, "registry_path", lambda: FIXTURE_REGISTRY)
    return FIXTURE_REGISTRY


def test_list_prints_the_registered_products_as_a_json_array(fixture_registry: Path) -> None:
    result = runner.invoke(app, ["product", "list", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == ["api", "web", "third"]


def test_list_prints_one_product_per_line(fixture_registry: Path) -> None:
    result = runner.invoke(app, ["product", "list"])

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == ["api", "web", "third"]


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ("web-image-published", {"ok": True, "event": "web-image-published", "app": "web", "lane": "staging"}),
        ("web-release-published", {"ok": True, "event": "web-release-published", "app": "web", "lane": "prod"}),
        ("third-image-published", {"ok": True, "event": "third-image-published", "app": "third", "lane": "staging"}),
    ],
)
def test_app_for_event_names_the_app_and_the_lane(fixture_registry: Path, event: str, expected: dict) -> None:
    """The lane is part of the answer: a prod workflow must not act on a staging event."""
    result = runner.invoke(app, ["product", "app-for-event", event, "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == expected


def test_app_for_event_prints_the_app_as_text(fixture_registry: Path) -> None:
    result = runner.invoke(app, ["product", "app-for-event", "web-release-published"])

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "web"


def test_an_unmapped_event_exits_one_with_error_why_fix(fixture_registry: Path) -> None:
    result = runner.invoke(app, ["product", "app-for-event", "ghost-image-published"])

    assert result.exit_code == 1
    lines = result.stderr.splitlines()
    assert [line.split(":", 1)[0] for line in lines] == ["ERROR", "WHY", "FIX"]
    assert "ghost-image-published" in lines[0] and str(FIXTURE_REGISTRY) in result.stderr


def test_an_unmapped_event_as_json(fixture_registry: Path) -> None:
    result = runner.invoke(app, ["product", "app-for-event", "ghost-image-published", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert set(payload) == {"ok", "error", "why", "fix"}


@pytest.mark.parametrize(
    ("product", "expected"),
    [
        ("third", {"forge": "github", "repository": "mlorentedev/third", "receiver": "generic"}),
        ("web", {"forge": "github", "repository": "mlorentedev/web", "receiver": "legacy"}),
        ("api", {"forge": "in-tree", "repository": None, "receiver": None}),
    ],
)
def test_show_names_where_a_product_comes_from(fixture_registry: Path, product: str, expected: dict) -> None:
    """The receiver's one source for the repository it fetches from and whether it acts (PR 6)."""
    result = runner.invoke(app, ["product", "show", product, "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"ok": True, "app": product, **expected}


def test_show_prints_the_entry_as_text(fixture_registry: Path) -> None:
    result = runner.invoke(app, ["product", "show", "third"])

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == ["forge: github", "repository: mlorentedev/third", "receiver: generic"]


def test_show_refuses_an_unregistered_product_with_error_why_fix(fixture_registry: Path) -> None:
    result = runner.invoke(app, ["product", "show", "ghost"])

    assert result.exit_code == 1
    lines = result.stderr.splitlines()
    assert [line.split(":", 1)[0] for line in lines] == ["ERROR", "WHY", "FIX"]
    assert "ghost" in lines[0] and str(FIXTURE_REGISTRY) in result.stderr


def test_show_refuses_an_unregistered_product_as_json(fixture_registry: Path) -> None:
    result = runner.invoke(app, ["product", "show", "ghost", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert set(payload) == {"ok", "error", "why", "fix"}


def _toolkit_without_sops(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the toolkit as a workflow step does on a hosted runner: no sops on PATH.

    ``CliRunner`` shares this process's already-built state, so only a fresh
    interpreter shows what the first read of the registry prints. PATH holds the
    interpreter's own directory and nothing else, which is CI's case on every host.
    """
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "toolkit.main", "product", *args],
        cwd=tmp_path,
        env={"PATH": str(Path(sys.executable).parent)},
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_app_for_event_json_is_the_only_stdout_without_sops(tmp_path: Path) -> None:
    """``promote-prod.yml`` pipes this into ``jq``. A ``[WARNING]`` line before the
    object read as a staging event there, and every release was skipped green."""
    result = _toolkit_without_sops(tmp_path, "app-for-event", "web-release-published", "--json")

    assert result.returncode == 0, result.stderr
    assert result.stdout.count("\n") == 1, result.stdout
    assert json.loads(result.stdout)["lane"] == "prod"


def test_product_list_prints_only_the_products_without_sops(tmp_path: Path) -> None:
    result = _toolkit_without_sops(tmp_path, "list")

    assert result.returncode == 0, result.stderr
    assert tuple(result.stdout.splitlines()) == product_registry.platform_apps()


def test_show_json_is_the_only_stdout_without_sops(tmp_path: Path) -> None:
    """The receiver pipes this into ``jq``, on a runner without sops."""
    result = _toolkit_without_sops(tmp_path, "show", "web", "--json")

    assert result.returncode == 0, result.stderr
    assert result.stdout.count("\n") == 1, result.stdout
    assert json.loads(result.stdout)["repository"] == "mlorentedev/web"
