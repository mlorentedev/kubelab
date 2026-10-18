"""Tests for the product contract (IDP-042 PR 1, ADR-067 D2).

``kubelab.yaml`` is written by whoever can push to a product repository, so it
is attacker-shaped data: every refusal below must name the field it refused,
and nothing may reach the caller as a traceback instead of a ``ContractError``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.features.product_contract import ContractError, validate_contract

FIXTURE = Path(__file__).parent / "fixtures" / "product" / "web.kubelab.yaml"


def _web() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(FIXTURE.read_text())
    return data


def _write(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "kubelab.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def _refusal(tmp_path: Path, data: dict[str, Any]) -> ContractError:
    with pytest.raises(ContractError) as excinfo:
        validate_contract(_write(tmp_path, data))
    return excinfo.value


def test_web_contract_validates() -> None:
    contract = validate_contract(FIXTURE)

    assert contract.schema_version == 1
    assert contract.image == "docker.io/mlorentedev/kubelab-web"
    assert contract.port == 8080
    assert contract.health_path == "/"
    assert contract.hostnames.staging == "staging.mlorente.dev"
    assert contract.hostnames.prod == "mlorente.dev"
    assert contract.auth == "public"
    assert contract.secrets == []


def _set(field: str, value: Any) -> dict[str, Any]:
    data = _web()
    data[field] = value
    return data


def _drop(field: str) -> dict[str, Any]:
    data = _web()
    del data[field]
    return data


def _host(env: str, value: Any) -> dict[str, Any]:
    data = _web()
    data["hostnames"][env] = value
    return data


def _drop_host(env: str) -> dict[str, Any]:
    data = _web()
    del data["hostnames"][env]
    return data


REFUSED = [
    pytest.param(_set("replicas", 2), "replicas", id="unknown-top-level-key"),
    pytest.param(_set("port", 0), "port", id="port-zero"),
    pytest.param(_set("port", 70000), "port", id="port-above-range"),
    # YAML hands "8080" over as a string and true as a bool; neither may be coerced.
    pytest.param(_set("port", "8080"), "port", id="port-as-string"),
    pytest.param(_host("staging", "https://staging.mlorente.dev"), "hostnames.staging", id="hostname-with-scheme"),
    pytest.param(_host("prod", "Mlorente.dev"), "hostnames.prod", id="hostname-uppercase"),
    pytest.param(_host("staging", "localhost"), "hostnames.staging", id="hostname-single-label"),
    pytest.param(_host("dev", "mlorente.test"), "hostnames.dev", id="hostname-unknown-env"),
    pytest.param(_drop_host("prod"), "hostnames.prod", id="hostname-prod-absent"),
    pytest.param(_set("health_path", "healthz"), "health_path", id="health-path-without-slash"),
    pytest.param(_set("auth", "admin"), "auth", id="auth-admin"),
    pytest.param(_drop("schema_version"), "schema_version", id="schema-version-absent"),
    pytest.param(_set("schema_version", 2), "schema_version", id="schema-version-2"),
    pytest.param(_set("schema_version", True), "schema_version", id="schema-version-bool"),
    pytest.param(_set("secrets", ["apps.platform.web token"]), "secrets", id="secret-name-with-space"),
    pytest.param(_set("image", "docker.io/mlorentedev/kubelab-web:1.15.1"), "image", id="image-with-tag"),
    pytest.param(_set("image", "docker.io/mlorentedev/kubelab-web@sha256:00"), "image", id="image-with-digest"),
]


@pytest.mark.parametrize(("data", "field"), REFUSED)
def test_invalid_contract_is_refused_naming_the_field(tmp_path: Path, data: dict[str, Any], field: str) -> None:
    err = _refusal(tmp_path, data)

    assert field in err.error


@pytest.mark.parametrize("key", ["repository", "repo", "source", "remote"])
def test_a_contract_cannot_name_a_repository(tmp_path: Path, key: str) -> None:
    """Where a contract is fetched from, and where the PR goes, is the registry's call (AC6)."""
    err = _refusal(tmp_path, _set(key, "mlorentedev/web"))

    assert key in err.error
    assert "registry" in err.why


def test_a_missing_file_is_a_contract_error(tmp_path: Path) -> None:
    with pytest.raises(ContractError) as excinfo:
        validate_contract(tmp_path / "kubelab.yaml")

    assert "kubelab.yaml" in excinfo.value.error


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("- schema_version: 1\n", id="root-is-a-list"),
        pytest.param("schema_version: [1\n", id="unparsable"),
        pytest.param("", id="empty"),
    ],
)
def test_a_malformed_document_is_a_contract_error(tmp_path: Path, body: str) -> None:
    path = tmp_path / "kubelab.yaml"
    path.write_text(body)

    with pytest.raises(ContractError) as excinfo:
        validate_contract(path)

    assert str(path) in excinfo.value.error


def test_a_duplicate_key_is_refused(tmp_path: Path) -> None:
    """``yaml.safe_load`` keeps the last of two equal keys; a reviewer reading the first would be misled."""
    path = tmp_path / "kubelab.yaml"
    path.write_text(FIXTURE.read_text() + "port: 9090\n")

    with pytest.raises(ContractError) as excinfo:
        validate_contract(path)

    assert "port" in excinfo.value.error
    assert "duplicate" in excinfo.value.error.lower()
