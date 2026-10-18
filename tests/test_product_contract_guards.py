"""Tests for the contract guards (IDP-042 PR 4, AC6): a contract cannot widen the registry.

The schema (PR 1) answers "is this a well-formed contract". These answer "may
this product claim what it claims": the image the platform derives for it, the
secrets the operator already catalogued, and hostnames no other route owns.
Every refusal is a ``ContractError`` with ERROR / WHY / FIX.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.features.product_contract import _SECRET_NAME, Contract, ContractError, validate_contract
from toolkit.features.product_guards import (
    check_against_platform,
    refuse_oidc_at_render,
    validate_against_platform,
    validate_registered,
)
from toolkit.features.secrets_manager import SECRET_CATALOG

FIXTURE = Path(__file__).parent / "fixtures" / "product" / "web.kubelab.yaml"
WEB_IMAGE = "docker.io/mlorentedev/kubelab-web"


def _web_image(app: str) -> str:
    # A stub deriver keeps these guard tests independent of the registry file;
    # the real-registry tests below cover derived_image itself.
    return {"web": WEB_IMAGE, "third": "docker.io/mlorentedev/third"}[app]


def _contract(**changes: Any) -> Contract:
    data: dict[str, Any] = yaml.safe_load(FIXTURE.read_text())
    data.update(changes)
    return Contract.model_validate(data)


def _refused(contract: Contract, app: str = "web") -> ContractError:
    with pytest.raises(ContractError) as excinfo:
        check_against_platform(contract, app, image_for=_web_image)
    return excinfo.value


def _assert_explained(err: ContractError) -> None:
    lines = str(err).splitlines()
    assert [line.split(":", 1)[0] for line in lines] == ["ERROR", "WHY", "FIX"]
    assert all(line.split(":", 1)[1].strip() for line in lines)


def test_an_image_other_than_the_derived_one_is_refused() -> None:
    """Q7: a contract cannot point at another product's image."""
    err = _refused(_contract(image="docker.io/mlorentedev/api"))

    _assert_explained(err)
    assert "image" in err.error
    assert WEB_IMAGE in err.fix


def test_a_secret_absent_from_the_catalog_is_refused() -> None:
    """Q6: the catalog is operator-owned; a contract cannot add to it."""
    err = _refused(_contract(secrets=["apps.platform.web.not_in_the_catalog"]))

    _assert_explained(err)
    assert "apps.platform.web.not_in_the_catalog" in err.error
    assert "SECRET_CATALOG" in err.why


def test_a_catalogued_secret_is_accepted() -> None:
    key = SECRET_CATALOG[0].key_path

    check_against_platform(_contract(secrets=[key]), "web", image_for=_web_image)


def test_a_hostname_another_route_owns_is_refused() -> None:
    err = _refused(_contract(hostnames={"staging": "staging.mlorente.dev", "prod": "grafana.kubelab.live"}))

    _assert_explained(err)
    assert "grafana.kubelab.live" in err.error
    assert "apps.services.observability.grafana.domain" in err.why


def test_a_hostname_owned_in_the_other_environment_is_refused() -> None:
    """Checked against both environments: a staging host may not be another product's prod host."""
    contract = _contract(
        image="docker.io/mlorentedev/third",
        hostnames={"staging": "mlorente.dev", "prod": "third.kubelab.live"},
    )

    err = _refused(contract, app="third")

    _assert_explained(err)
    assert "mlorente.dev" in err.error
    assert "apps.platform.web" in err.why


def test_a_product_may_keep_the_hostnames_it_already_declares() -> None:
    """web's own `apps.platform.web.domain` is not another route."""
    check_against_platform(_contract(), "web", image_for=_web_image)


@pytest.mark.parametrize("key", ["repository", "repo", "source", "remote"])
def test_a_contract_naming_the_registrys_own_repository_is_refused(tmp_path: Path, key: str) -> None:
    """Refused even when the value is right: the contract is not where the repository comes from."""
    data = yaml.safe_load(FIXTURE.read_text())
    data[key] = "mlorentedev/web"
    path = tmp_path / "kubelab.yaml"
    path.write_text(yaml.safe_dump(data))

    with pytest.raises(ContractError) as excinfo:
        validate_against_platform(path, "web", image_for=_web_image)

    _assert_explained(excinfo.value)
    assert key in excinfo.value.error
    assert "registry" in excinfo.value.why


def test_oidc_is_refused_at_render() -> None:
    """Design point 5: no OIDC client can be rendered from a contract yet, and a deploy without one is worse."""
    with pytest.raises(ContractError) as excinfo:
        refuse_oidc_at_render(_contract(auth="oidc"), "web")

    _assert_explained(excinfo.value)
    assert "oidc" in excinfo.value.error


@pytest.mark.parametrize("auth", ["public", "forwardauth"])
def test_other_auth_levels_render(auth: str) -> None:
    refuse_oidc_at_render(_contract(auth=auth), "web")


def test_webs_real_contract_passes_every_guard() -> None:
    contract = validate_against_platform(FIXTURE, "web", image_for=_web_image)

    refuse_oidc_at_render(contract, "web")
    assert contract == validate_contract(FIXTURE)


def test_every_catalog_key_fits_the_contract_secret_pattern() -> None:
    """A real catalog key must never fail the schema before the catalog check sees it.

    SECRET_CATALOG already carries the per-node entries (`access_key_path(node)`
    and siblings, via `_backup_node_specs`), so iterating it covers them.
    """
    pattern = re.compile(_SECRET_NAME)
    misfits = [s.key_path for s in SECRET_CATALOG if not pattern.fullmatch(s.key_path) or len(s.key_path) > 200]

    assert not misfits


REGISTRY = Path(__file__).resolve().parents[1] / "infra" / "config" / "products.yaml"


def test_webs_real_contract_passes_against_the_real_registry() -> None:
    """No stub: the committed registry, its derived image and the real catalog."""
    assert validate_registered(FIXTURE, "web", REGISTRY) == validate_contract(FIXTURE)


def test_the_registry_override_is_what_web_must_declare(tmp_path: Path) -> None:
    """Q7: without the override the rule yields .../web; the contract must carry the override's name."""
    path = tmp_path / "kubelab.yaml"
    path.write_text(FIXTURE.read_text().replace("kubelab-web", "web"))

    with pytest.raises(ContractError) as excinfo:
        validate_registered(path, "web", REGISTRY)

    _assert_explained(excinfo.value)
    assert WEB_IMAGE in excinfo.value.fix


@pytest.mark.parametrize(("app", "says"), [("api", "in-tree"), ("ghost", "not a registered product")])
def test_only_a_contract_managed_registry_entry_has_a_contract(app: str, says: str) -> None:
    with pytest.raises(ContractError) as excinfo:
        validate_registered(FIXTURE, app, REGISTRY)

    _assert_explained(excinfo.value)
    assert says in excinfo.value.error
