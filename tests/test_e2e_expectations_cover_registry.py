"""Every registered product is probed by the e2e suite (#2572).

The e2e probes read a product's domain and `health_path` from the merged config,
which the generic receiver renders from the product's contract, so those are
already derived. What is not derived is the entry in `tests/e2e/expectations.py`:
the content, security-header and auth suites parametrize over its keys, so a
product admitted to `infra/config/products.yaml` without an entry is silently
left out of all three.

The entry stays hand-written on purpose. What it asserts (`content_type`,
`body_contains`, an API's JSON keys) is something the contract has no field
for, so it cannot be derived. These tests make a missing entry fail offline, and
hold the one property both sides do declare, whether the product sits behind
Authelia, to agree.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

from tests.e2e.expectations import EXPECTATIONS, ServiceExpectation
from toolkit.features.product_guards import ENVIRONMENTS, apps_declaring
from toolkit.features.product_registry import platform_apps
from toolkit.features.product_render import SNAPSHOT_DIR

FIXTURE_REGISTRY = pathlib.Path(__file__).parent / "fixtures" / "product" / "registry.yaml"


def _deployed(registry: pathlib.Path | None = None) -> tuple[str, ...]:
    """The products that run in at least one env: the ones the e2e suite must probe, in registry order."""
    return tuple(
        app for app in platform_apps(registry) if any(app in apps_declaring(env, registry) for env in ENVIRONMENTS)
    )


def _missing(apps: tuple[str, ...], expectations: dict[str, ServiceExpectation]) -> list[str]:
    return [app for app in apps if app not in expectations]


def test_a_staging_only_product_needs_one_expectation_and_a_product_with_no_lane_none(tmp_path: pathlib.Path) -> None:
    """`EXPECTATIONS` has no env dimension, so a staging-only product has one entry (the suite skips it where
    the merged config does not carry it) and there is no prod entry to require. A remote entry that declares
    no lane at all is deployed nowhere and is not probed."""
    registry = tmp_path / "products.yaml"
    registry.write_text(
        FIXTURE_REGISTRY.read_text(encoding="utf-8")
        + "  idle:\n    repository: mlorentedev/idle\n    forge: github\n    receiver: generic\n",
        encoding="utf-8",
        newline="\n",
    )

    assert _deployed(FIXTURE_REGISTRY) == ("api", "web", "third")
    assert _deployed(registry) == ("api", "web", "third")
    assert _missing(_deployed(registry), {"api": ServiceExpectation(), "web": ServiceExpectation()}) == ["third"]


def test_every_registered_product_has_an_e2e_expectation() -> None:
    assert platform_apps(), "the product registry names no product: nothing was checked"
    assert _deployed(), "no registered product declares a lane: nothing was checked"
    assert _missing(_deployed(), EXPECTATIONS) == [], (
        "ERROR: a product in infra/config/products.yaml has no entry in tests/e2e/expectations.py\n"
        "WHY: the content, security-header and auth e2e suites parametrize over that dict, "
        "so the product is never probed\n"
        "FIX: add a ServiceExpectation for it, keyed by its registry name"
    )


def test_there_is_a_contract_snapshot_to_compare() -> None:
    """The parametrized check below runs once per snapshot, so with none it would pass by checking nothing."""
    assert sorted(SNAPSHOT_DIR.glob("*.yaml")), f"no contract snapshot under {SNAPSHOT_DIR}"


@pytest.mark.parametrize("snapshot", sorted(SNAPSHOT_DIR.glob("*.yaml")), ids=lambda path: path.stem)
def test_the_expectation_agrees_with_the_contract_on_authentication(snapshot: pathlib.Path) -> None:
    auth = yaml.safe_load(snapshot.read_text(encoding="utf-8"))["auth"]
    if auth == "oidc":
        pytest.skip("an OIDC contract is refused at render (#2573), so no such product is deployed")

    expectation = EXPECTATIONS.get(snapshot.stem)
    assert expectation is not None, f"{snapshot.stem} has a contract snapshot but no entry in tests/e2e/expectations.py"
    assert expectation.auth_protected == (auth == "forwardauth"), (
        f"{snapshot.stem}: the contract says auth: {auth}, "
        f"tests/e2e/expectations.py says auth_protected={expectation.auth_protected}"
    )


def test_an_unreachable_target_skips_only_the_tests_under_tests_e2e(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The skip once matched "e2e" anywhere in the path, so it also skipped this file, and every
    test of a checkout whose directory name contains it, silently."""
    from tests.e2e import conftest as e2e_conftest

    class _Item:
        def __init__(self, path: pathlib.Path) -> None:
            self.path = path
            self.markers: list[pytest.MarkDecorator] = []

        def add_marker(self, marker: pytest.MarkDecorator) -> None:
            self.markers.append(marker)

    class _Config:
        def getoption(self, name: str, default: str = "") -> str:
            return "staging"

    monkeypatch.setattr(e2e_conftest, "_CONNECTIVITY_DOMAINS", {"staging": "probe.invalid"})
    monkeypatch.setattr(e2e_conftest, "_can_resolve", lambda host: False)
    inside = _Item(e2e_conftest._E2E_DIR / "test_health.py")
    outside = _Item(tmp_path / "wt-e2e-ticket" / "tests" / "test_e2e_named.py")

    e2e_conftest.pytest_collection_modifyitems(_Config(), [inside, outside])  # type: ignore[arg-type]

    assert len(inside.markers) == 1
    assert outside.markers == []
