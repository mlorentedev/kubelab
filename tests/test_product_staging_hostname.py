"""A product's staging hostname is a declaration, not a free choice (IDP-053 D8, AC13).

The contract model cannot read ``common.yaml``, so the check runs at render time, where the
values directory is known. A staging hostname is accepted only if it is exactly a zone in
``networking.staging_zones`` (other than the platform wildcard zone) or one label under
``staging.kubelab.live``; a product that also declares prod must name ``staging.`` + its prod
hostname. Names here are fixtures, not any real product's.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.features import product_render
from toolkit.features.product_contract import Contract, ContractError
from toolkit.features.product_guards import check_staging_hostname, staging_zones

ZONE_LINE = '"staging.example-product.test"'
ZONES = ["staging.kubelab.live", "staging.mlorente.dev", "staging.example-product.test"]
WEB = Path(__file__).parent / "fixtures" / "product" / "web.kubelab.yaml"


def _contract(staging: str, prod: str | None = None) -> Contract:
    data: dict[str, Any] = yaml.safe_load(WEB.read_text(encoding="utf-8"))
    data["hostnames"] = {"staging": staging} | ({"prod": prod} if prod else {})
    return Contract.model_validate(data)


def _refused(staging: str, prod: str | None = None, zones: list[str] = ZONES) -> ContractError:
    with pytest.raises(ContractError) as excinfo:
        check_staging_hostname(_contract(staging, prod), zones)
    err = excinfo.value
    assert [line.split(":", 1)[0] for line in str(err).splitlines()] == ["ERROR", "WHY", "FIX"]
    assert "D8" in err.why
    return err


def test_web_already_conforms() -> None:
    check_staging_hostname(_contract("staging.mlorente.dev", "mlorente.dev"), ZONES)


def test_a_staging_only_zone_in_the_list_passes() -> None:
    check_staging_hostname(_contract("staging.example-product.test"), ZONES)


def test_a_label_under_the_wildcard_zone_passes() -> None:
    check_staging_hostname(_contract("shop.staging.kubelab.live"), ZONES)


def test_a_zone_missing_from_the_list_is_refused_naming_the_line_to_add() -> None:
    err = _refused("staging.example-product.test", zones=["staging.kubelab.live", "staging.mlorente.dev"])

    assert ZONE_LINE in err.fix
    assert "networking.staging_zones" in err.fix


def test_a_name_that_is_not_staging_dot_a_domain_is_refused() -> None:
    err = _refused("beta.example-product.test")

    assert "beta.example-product.test" in err.error
    assert ZONE_LINE not in err.fix


@pytest.mark.parametrize("host", ["a.b.staging.kubelab.live", "staging.kubelab.live"])
def test_only_one_label_under_the_wildcard_zone_passes(host: str) -> None:
    """The wildcard zone is a parent, not a hostname, and two labels are not under the wildcard cert."""
    _refused(host)


def test_a_subdomain_of_a_listed_zone_is_refused() -> None:
    _refused("shop.staging.example-product.test")


def test_staging_must_be_staging_dot_prod_even_when_both_zones_are_listed() -> None:
    err = _refused("staging.example-product.test", "x.dev", ZONES + ["staging.x.dev"])

    assert "staging.x.dev" in err.fix


def test_the_prod_relation_is_equality_not_a_suffix_match() -> None:
    """`staging.example-product.test` ends with `product.test`, and is still not `staging.product.test`."""
    _refused("staging.example-product.test", "product.test")


def test_the_prod_relation_binds_a_wildcard_label_too() -> None:
    _refused("shop.staging.kubelab.live", "shop.example-product.test")


def _values(tmp_path: Path, zones: list[str]) -> Path:
    (tmp_path / "common.yaml").write_text(
        yaml.safe_dump({"networking": {"staging_zones": zones}}), encoding="utf-8", newline="\n"
    )
    return tmp_path


def test_the_zones_come_from_common_yaml(tmp_path: Path) -> None:
    assert staging_zones(_values(tmp_path, ZONES)) == ZONES


def test_the_committed_zones_include_web_and_the_wildcard() -> None:
    assert {"staging.kubelab.live", "staging.mlorente.dev"} <= set(staging_zones())


def test_rendering_refuses_a_hostname_the_zones_do_not_grant(tmp_path: Path) -> None:
    contract = _contract("staging.example-product.test")

    with pytest.raises(ContractError):
        product_render.rendered(contract, "web", "staging", values_dir=_values(tmp_path, ZONES[:2]))
    assert product_render.rendered(contract, "web", "staging", values_dir=_values(tmp_path, ZONES))["domain"] == (
        "staging.example-product.test"
    )


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_the_refusal_comes_before_any_env_is_rendered(env: str, tmp_path: Path) -> None:
    """The prod render of a contract whose staging name breaks D8 is refused too: it is one contract."""
    contract = _contract("beta.example-product.test", "example-product.test")

    with pytest.raises(ContractError, match="hostnames.staging"):
        product_render.rendered(contract, "web", env, values_dir=_values(tmp_path, ZONES))
