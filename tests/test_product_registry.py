"""The product registry: which products kubelab admits (ADR-067 D2, IDP-042, #1815)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from toolkit.features import product_registry
from toolkit.features.product_registry import RegistryError, UnknownEventError

REPO = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "product" / "registry.yaml"


@pytest.fixture
def fixture_registry(monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(product_registry, "registry_path", lambda: FIXTURE)
    return FIXTURE


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "products.yaml"
    path.write_text(body)
    return path


class TestPlatformApps:
    def test_returns_the_products_in_registry_order(self, fixture_registry: Path) -> None:
        assert product_registry.platform_apps() == ("api", "web", "third")

    def test_the_real_registry_admits_exactly_api_then_web(self) -> None:
        """The generators iterate this list, so its order is their output order.

        Before #1815 the list was the literal ``("api", "web")``. Deriving it must
        not change a byte of the generated overlays, which holds only while the
        real registry yields the same names in the same order.
        """
        assert product_registry.platform_apps() == ("api", "web")


class TestAppForEvent:
    def test_maps_a_staging_event_to_its_app(self, fixture_registry: Path) -> None:
        assert product_registry.app_for_event("web-image-published") == "web"

    def test_maps_a_prod_event_to_its_app(self, fixture_registry: Path) -> None:
        assert product_registry.app_for_event("web-release-published") == "web"

    def test_an_unmapped_event_is_refused_naming_the_registry(self, fixture_registry: Path) -> None:
        with pytest.raises(UnknownEventError, match=r"ghost-image-published.*registry\.yaml"):
            product_registry.app_for_event("ghost-image-published")


class TestLoadRefuses:
    def test_an_event_type_claimed_by_two_apps(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            """\
products:
  web:
    repository: mlorentedev/web
    forge: github
    receiver: legacy
    events: {staging: shared-event}
  third:
    repository: mlorentedev/third
    forge: github
    receiver: generic
    events: {prod: shared-event}
""",
        )
        with pytest.raises(RegistryError, match=r"shared-event.*web.*third"):
            product_registry.load_registry(path)

    def test_an_unknown_field(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "products:\n  api:\n    forge: in-tree\n    image: docker.io/x/api\n")
        with pytest.raises(RegistryError, match="image"):
            product_registry.load_registry(path)

    def test_an_unknown_forge(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "products:\n  api:\n    forge: gitlab\n")
        with pytest.raises(RegistryError, match="forge"):
            product_registry.load_registry(path)

    @pytest.mark.parametrize(
        "extra",
        ["repository: mlorentedev/kubelab", "receiver: generic", "events: {staging: api-image-published}"],
    )
    def test_an_in_tree_entry_that_names_a_remote(self, tmp_path: Path, extra: str) -> None:
        """``in-tree`` means no remote repository and no dispatch (design point 3)."""
        path = _write(tmp_path, f"products:\n  api:\n    forge: in-tree\n    {extra}\n")
        with pytest.raises(RegistryError, match="in-tree"):
            product_registry.load_registry(path)

    @pytest.mark.parametrize("missing", ["repository", "receiver"])
    def test_a_remote_entry_without_its_repository_or_receiver(self, tmp_path: Path, missing: str) -> None:
        fields = {"repository": "mlorentedev/web", "forge": "github", "receiver": "legacy"}
        del fields[missing]
        body = "products:\n  web:\n" + "".join(f"    {k}: {v}\n" for k, v in fields.items())
        with pytest.raises(RegistryError, match=missing):
            product_registry.load_registry(_write(tmp_path, body))

    @pytest.mark.parametrize("name", ["Web", "my-app", "9lives", "web.app"])
    def test_an_app_name_the_generators_cannot_key_on(self, tmp_path: Path, name: str) -> None:
        """App names become ``APPS_PLATFORM_<NAME>_*`` keys, so only ``[a-z][a-z0-9]*``."""
        with pytest.raises(RegistryError, match="name"):
            product_registry.load_registry(_write(tmp_path, f"products:\n  {name}:\n    forge: in-tree\n"))

    def test_an_empty_registry(self, tmp_path: Path) -> None:
        with pytest.raises(RegistryError, match="no products"):
            product_registry.load_registry(_write(tmp_path, "products: {}\n"))

    def test_an_error_names_the_file(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "products:\n  api:\n    forge: gitlab\n")
        with pytest.raises(RegistryError, match=str(path)):
            product_registry.load_registry(path)

    def test_a_repeated_product_key(self, tmp_path: Path) -> None:
        """A second ``web:`` would silently replace the first under a plain safe_load."""
        body = "products:\n  web:\n    forge: in-tree\n  web:\n    forge: in-tree\n"
        with pytest.raises(RegistryError, match="duplicate key 'web'"):
            product_registry.load_registry(_write(tmp_path, body))


class TestDerivedImage:
    """Q7: the registry has no ``image`` field; the image is derived, with an override."""

    def test_the_platform_registry_already_carries_the_owner(self) -> None:
        # `<registry>/<owner>/<product>` reads as `<registry>/<product>` here,
        # because the platform's registry value already ends in the owner.
        assert product_registry.platform_registry() == "docker.io/mlorentedev"

    def test_a_product_without_an_override_is_registry_slash_app(self, fixture_registry: Path) -> None:
        assert product_registry.derived_image("third") == "docker.io/mlorentedev/third"

    def test_the_override_replaces_the_app_name(self, fixture_registry: Path) -> None:
        assert product_registry.derived_image("web") == "docker.io/mlorentedev/kubelab-web"

    def test_an_in_tree_product_has_no_derived_image(self, fixture_registry: Path) -> None:
        """api's image is hand-authored (kubelab-api); the rule would say `api`, so it refuses."""
        with pytest.raises(RegistryError, match="in-tree"):
            product_registry.derived_image("api")

    def test_an_unregistered_product_is_refused_naming_the_registry(self, fixture_registry: Path) -> None:
        with pytest.raises(RegistryError, match=r"ghost.*registry\.yaml"):
            product_registry.derived_image("ghost")

    def test_each_real_product_derives_the_image_its_values_deploy(self) -> None:
        """The override and ``apps.platform.<app>.image_name`` must name one image."""
        common = yaml.safe_load((REPO / "infra" / "config" / "values" / "common.yaml").read_text())
        checked = 0
        for app, product in product_registry.load_registry().products.items():
            if not product.contract_managed:
                continue
            deployed = f"{common['registry']}/{common['apps']['platform'][app]['image_name']}"
            assert product_registry.derived_image(app) == deployed, app
            checked += 1
        assert checked > 0
