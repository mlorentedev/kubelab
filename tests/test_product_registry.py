"""The product registry: which products kubelab admits (ADR-067 D2, IDP-042, #1815)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from toolkit.config import settings as settings_module
from toolkit.features import product_registry
from toolkit.features.product_registry import RegistryError, UnknownEventError

REPO = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "product" / "registry.yaml"
# What generator_k8s reads before it emits an app; any one absent and it skips it.
DEPLOY_FIELDS = ("image_name", "domain", "default_port")


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

    @pytest.mark.parametrize("env", ["common", "staging", "prod"])
    def test_every_platform_block_in_the_values_is_a_registered_product(self, env: str) -> None:
        """The generators emit only registered apps, so an unregistered block would vanish silently."""
        declared = _platform_blocks(env)
        assert declared, f"values/{env}.yaml declares no apps.platform block; the check would cover nothing"
        assert set(declared) <= set(product_registry.platform_apps())

    @pytest.mark.parametrize("env", ["staging", "prod"])
    def test_every_registered_product_deploys_in_each_cluster_env(self, env: str) -> None:
        """The other direction: the generators skip an app with no image, domain or port.

        A product admitted to the registry before its ``apps.platform.<app>`` block
        carries those three would be iterated and then dropped with a debug line,
        never deployed. A block alone is not enough: a first ``promote`` writes one
        holding only ``version``.
        """
        common, overlay = _platform_blocks("common"), _platform_blocks(env)
        missing = {}
        for app in product_registry.platform_apps():
            block = {**(common.get(app) or {}), **(overlay.get(app) or {})}
            if absent := [field for field in DEPLOY_FIELDS if not block.get(field)]:
                missing[app] = absent
        assert not missing, f"registered, but common.yaml + {env}.yaml lack what generator_k8s needs: {missing}"

    def test_the_registry_keeps_the_order_common_yaml_declares(self) -> None:
        """The generators iterate the registry, so its order is their output order.

        Before #1815 the list was the literal ``("api", "web")``, the order of
        ``apps.platform`` in ``common.yaml``. A product rendered only into the env
        files (Q2) may be absent from ``common.yaml``, so the order is compared on
        the products both name.
        """
        common = list(_platform_blocks("common"))
        assert [app for app in product_registry.platform_apps() if app in common] == common


class TestReadingBuildsNoSettings:
    """Reading a YAML file must not load the configuration it does not need.

    ``settings`` is lazy: its first attribute builds ``ConfigurationManager``, which
    checks for sops, exports every value into ``os.environ`` and, without sops,
    prints a warning on stdout. That warning corrupted ``app-for-event --json``
    in CI, where sops is not installed.
    """

    def test_no_registry_read_builds_the_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def refuse(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("the registry built the platform settings")

        monkeypatch.setattr(settings_module, "get_settings", refuse)
        product_registry.platform_apps()
        product_registry.event_route("web-release-published")
        product_registry.derived_image("web")


class TestAppForEvent:
    def test_maps_a_staging_event_to_its_app(self, fixture_registry: Path) -> None:
        assert product_registry.app_for_event("web-image-published") == "web"

    def test_maps_a_prod_event_to_its_app(self, fixture_registry: Path) -> None:
        assert product_registry.app_for_event("web-release-published") == "web"

    @pytest.mark.parametrize(
        ("event", "app", "lane"),
        [("web-image-published", "web", "staging"), ("web-release-published", "web", "prod")],
    )
    def test_the_route_names_the_lane_the_event_belongs_to(
        self, fixture_registry: Path, event: str, app: str, lane: str
    ) -> None:
        """One app owns both lanes' events, so the app alone cannot tell a workflow which lane fired."""
        assert product_registry.event_route(event) == product_registry.EventRoute(app=app, lane=lane)

    def test_exactly_one_product_dispatches_to_the_prod_lane(self) -> None:
        """``promote-prod.yml`` keeps ``|| 'web'`` in its concurrency group (Q4).

        The group is evaluated before any step can ask the registry, so the fallback
        names the one product whose release dispatches a prod promotion. A second
        such product would share web's group under a name that is no longer true.
        """
        prod = [app for app, product in product_registry.load_registry().products.items() if product.events.prod]
        assert prod == ["web"]

    def test_an_unmapped_event_is_refused_naming_the_registry(self, fixture_registry: Path) -> None:
        with pytest.raises(UnknownEventError, match=r"ghost-image-published.*registry\.yaml"):
            product_registry.app_for_event("ghost-image-published")

    def test_the_committed_web_entry_matches_what_web_sends(self) -> None:
        """The fixture proves the mapping; this pins the committed registry's one real remote product.

        Its event types and repository are a two-repo agreement: mlorentedev/web's CI
        dispatches these types to this repository. Rename one side and GitHub still
        answers 204, then drops the event, so nothing errors.
        """
        web = product_registry.load_registry().products["web"]
        assert (web.repository, web.forge, web.receiver) == ("mlorentedev/web", "github", "generic")
        assert (web.events.staging, web.events.prod) == ("web-image-published", "web-release-published")

    def test_every_staging_event_has_exactly_one_receiver(self) -> None:
        """A legacy product is received by the one workflow that lists its event; a generic one by none.

        The generic receiver lists no `types`, so it sees every event and skips a legacy
        product. A workflow that still lists a generic product's event would race it for
        `deploy/staging-<app>`, which is why the flip and the demotion share PR 7.
        """
        listening: dict[str, list[str]] = {}
        for path in sorted((REPO / ".github" / "workflows").glob("*.yml")):
            workflow = yaml.safe_load(path.read_text())
            dispatch = (workflow.get("on") or workflow.get(True) or {}).get("repository_dispatch") or {}
            for event in dispatch.get("types", []) if isinstance(dispatch, dict) else []:
                listening.setdefault(event, []).append(path.name)
        for name, entry in product_registry.load_registry().products.items():
            if entry.events is None or entry.events.staging is None:
                continue
            expected = 1 if entry.receiver == "legacy" else 0
            assert len(listening.get(entry.events.staging, [])) == expected, (name, listening)


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


def _platform_blocks(env: str) -> dict[str, dict]:
    values = yaml.safe_load((REPO / "infra" / "config" / "values" / f"{env}.yaml").read_text()) or {}
    return dict((values.get("apps") or {}).get("platform") or {})
