"""The product registry: which products kubelab admits (ADR-067 D2, IDP-042, #1815)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from toolkit.config import settings as settings_module
from toolkit.features import product_registry
from toolkit.features.product_guards import apps_declaring
from toolkit.features.product_registry import RegistryError, UnknownEventError
from toolkit.features.secrets_manager import SECRET_CATALOG

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
    path.write_text(body, encoding="utf-8")
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
        holding only ``version``. Only the envs the entry declares a lane for are
        held to it: a product with no ``events.prod`` does not run in prod (IDP-053 D5).
        """
        assert apps_declaring(env), f"no registered product declares a {env} lane: nothing was checked"
        missing = _undeployable(env, _platform_blocks("common"), _platform_blocks(env))
        assert not missing, f"registered, but common.yaml + {env}.yaml lack what generator_k8s needs: {missing}"

    def test_a_product_with_no_prod_lane_is_not_held_to_a_prod_block(self, fixture_registry: Path) -> None:
        """Fixture registry: `third` declares only `events.staging`; its staging block alone is enough."""
        staging = {"third": {"image_name": "third", "domain": "staging.third.dev", "default_port": 8080}}

        assert set(_undeployable("staging", {}, {}, fixture_registry)) == {"api", "web", "third"}
        assert set(_undeployable("staging", {}, staging, fixture_registry)) == {"api", "web"}
        assert set(_undeployable("prod", {}, {}, fixture_registry)) == {"api", "web"}

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
        # GitHub runs both extensions; a `.yaml` listener missed here is the race itself.
        workflows = REPO / ".github" / "workflows"
        for path in sorted([*workflows.glob("*.yml"), *workflows.glob("*.yaml")]):
            workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
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


_ENTRY = """\
  {name}:
    repository: personal/{name}
    forge: gitea
    receiver: generic
    image_registry: {registry}
    private: true
    pull_credential: {{username: {username}, secret: {secret}}}
"""


def _entry(
    name: str = "beta",
    registry: str = "gitea.kubelab.live/personal",
    username: str = "reviewer",
    secret: str = "gitea.registry_pull",
) -> str:
    return _ENTRY.format(name=name, registry=registry, username=username, secret=secret)


def _private(**fields: str) -> str:
    return "products:\n" + _entry(**fields)


class TestRegistryFields:
    """IDP-053 D4/D6: the entry, not the values, names the registry a product's image lives in."""

    def test_image_registry_private_and_the_credential_parse(self, tmp_path: Path) -> None:
        entry = product_registry.load_registry(_write(tmp_path, _private())).products["beta"]
        assert entry.image_registry == "gitea.kubelab.live/personal"
        assert entry.private is True
        assert entry.pull_credential is not None
        assert (entry.pull_credential.username, entry.pull_credential.secret) == ("reviewer", "gitea.registry_pull")

    def test_the_new_fields_default_to_the_platform_registry_and_public(self) -> None:
        entry = product_registry.load_registry().products["web"]
        assert (entry.image_registry, entry.private, entry.pull_credential) == (None, False, None)

    def test_the_committed_registry_is_unchanged_by_the_new_fields(self) -> None:
        """No committed entry names a registry yet; a new entry is a separate slice."""
        assert [n for n, p in product_registry.load_registry().products.items() if p.image_registry] == []

    @pytest.mark.parametrize(
        "image_registry",
        ["https://gitea.kubelab.live/personal", "gitea.kubelab.live/personal/", "Gitea.Kubelab.Live", "/personal", ""],
    )
    def test_an_image_registry_that_is_not_a_host_with_an_owner_path_is_refused(
        self, tmp_path: Path, image_registry: str
    ) -> None:
        body = _private().replace("gitea.kubelab.live/personal", f"'{image_registry}'")
        with pytest.raises(RegistryError, match="image_registry"):
            product_registry.load_registry(_write(tmp_path, body))

    def test_an_unknown_credential_field_is_refused(self, tmp_path: Path) -> None:
        body = _private().replace("secret:", "password: hunter2, secret:")
        with pytest.raises(RegistryError, match="password"):
            product_registry.load_registry(_write(tmp_path, body))

    @pytest.mark.parametrize(
        "line",
        ["image_registry: gitea.kubelab.live/personal", "private: true", "pull_credential: {username: u, secret: k.s}"],
    )
    def test_an_in_tree_entry_names_none_of_the_image_source_fields(self, tmp_path: Path, line: str) -> None:
        path = _write(tmp_path, f"products:\n  api:\n    forge: in-tree\n    {line}\n")
        with pytest.raises(RegistryError, match="in-tree"):
            product_registry.load_registry(path)


class TestPrivateEntryRefusals:
    """A private image is unpullable without a registry to pull from and a credential to pull with (D6)."""

    @pytest.mark.parametrize("missing", ["image_registry", "pull_credential"])
    def test_a_private_entry_without_its_registry_or_credential_is_refused(self, tmp_path: Path, missing: str) -> None:
        body = "".join(line for line in _private().splitlines(keepends=True) if not line.strip().startswith(missing))
        with pytest.raises(RegistryError) as refused:
            product_registry.load_registry(_write(tmp_path, body))
        message = str(refused.value)
        assert missing in message
        assert all(part in message for part in ("ERROR:", "WHY:", "FIX:"))

    def test_a_credential_on_a_public_entry_is_refused(self, tmp_path: Path) -> None:
        body = _private().replace("private: true", "private: false")
        with pytest.raises(RegistryError, match="pull_credential.*private"):
            product_registry.load_registry(_write(tmp_path, body))

    def test_two_private_entries_on_one_host_naming_different_credentials_are_refused(self, tmp_path: Path) -> None:
        body = _private() + _entry("gamma", registry="gitea.kubelab.live/me", secret="gitea.other_pull")
        with pytest.raises(RegistryError) as refused:
            product_registry.load_registry(_write(tmp_path, body))
        message = str(refused.value)
        assert all(part in message for part in ("gitea.kubelab.live", "beta", "gamma", "ERROR:", "WHY:", "FIX:"))

    def test_the_credential_is_compared_by_username_and_secret_not_the_secret_alone(self, tmp_path: Path) -> None:
        body = _private() + _entry("gamma", username="other")
        with pytest.raises(RegistryError, match="gitea.kubelab.live"):
            product_registry.load_registry(_write(tmp_path, body))

    def test_two_private_entries_on_one_host_naming_one_credential_are_admitted(self, tmp_path: Path) -> None:
        body = _private() + _entry("gamma", registry="gitea.kubelab.live/me")
        assert set(product_registry.load_registry(_write(tmp_path, body)).products) == {"beta", "gamma"}

    def test_private_entries_on_different_hosts_may_name_different_credentials(self, tmp_path: Path) -> None:
        body = _private() + _entry("gamma", registry="ghcr.io/mlorentedev", secret="ghcr.pull_token")
        assert set(product_registry.load_registry(_write(tmp_path, body)).products) == {"beta", "gamma"}

    def test_a_public_entry_on_a_private_host_does_not_count_as_a_second_credential(self, tmp_path: Path) -> None:
        public = _entry("open", secret="gitea.other_pull").replace("private: true", "private: false")
        public = public.replace("    pull_credential: {username: reviewer, secret: gitea.other_pull}\n", "")
        registry = product_registry.load_registry(_write(tmp_path, _private() + public))
        assert set(registry.products) == {"beta", "open"}

    @pytest.mark.parametrize("host", ["docker.io", "index.docker.io", "registry-1.docker.io"])
    def test_a_private_entry_on_docker_hub_is_refused_naming_the_product(self, tmp_path: Path, host: str) -> None:
        body = _private(registry=f"{host}/acme", secret="ghcr.pull_token")
        with pytest.raises(RegistryError) as refused:
            product_registry.load_registry(_write(tmp_path, body))
        message = str(refused.value)
        assert all(part in message for part in ("beta", "Docker Hub", "ERROR:", "WHY:", "FIX:", "GHCR"))

    def test_a_public_entry_on_docker_hub_is_admitted(self, tmp_path: Path) -> None:
        public = _private(registry="docker.io/acme").replace("private: true", "private: false")
        public = public.replace("    pull_credential: {username: reviewer, secret: gitea.registry_pull}\n", "")
        assert not product_registry.load_registry(_write(tmp_path, public)).products["beta"].private

    def test_a_host_that_only_ends_in_docker_io_is_not_docker_hub(self, tmp_path: Path) -> None:
        assert product_registry.load_registry(_write(tmp_path, _private(registry="notdocker.io/acme")))


class TestPullSecretsAreCatalogued:
    """The registry names a token by its catalog key; a key the catalog lacks is a typo (#3284).

    The check cannot sit in ``load_registry``: the suite reads the registry against fake keys, and
    ``product_verify`` validates old revisions. So the catalog is a parameter, and a test applies it
    to the committed file.
    """

    def _registry(self, tmp_path: Path, body: str) -> product_registry.Registry:
        return product_registry.load_registry(_write(tmp_path, body))

    def test_an_uncatalogued_secret_is_refused_naming_the_product_and_the_key(self, tmp_path: Path) -> None:
        registry = self._registry(tmp_path, _private(secret="ghcr.pul_token"))
        with pytest.raises(RegistryError) as refused:
            product_registry.check_pull_secrets_catalogued(registry, {"ghcr.pull_token"})
        message = str(refused.value)
        assert all(part in message for part in ("beta", "ghcr.pul_token", "ERROR:", "WHY:", "FIX:"))

    def test_a_catalogued_secret_is_admitted(self, tmp_path: Path) -> None:
        registry = self._registry(tmp_path, _private(secret="ghcr.pull_token"))
        product_registry.check_pull_secrets_catalogued(registry, {"ghcr.pull_token"})

    def test_an_entry_without_a_credential_is_skipped(self) -> None:
        product_registry.check_pull_secrets_catalogued(product_registry.load_registry(), set())

    def test_every_committed_pull_secret_is_in_the_secrets_catalog(self) -> None:
        catalogued = {spec.key_path for spec in SECRET_CATALOG}
        product_registry.check_pull_secrets_catalogued(product_registry.load_registry(), catalogued)


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

    def test_an_image_registry_replaces_the_platform_registry(self, tmp_path: Path) -> None:
        path = _write(tmp_path, _private())
        assert product_registry.derived_image("beta", path) == "gitea.kubelab.live/personal/beta"

    def test_the_image_name_override_applies_under_the_entry_registry(self, tmp_path: Path) -> None:
        path = _write(tmp_path, _private() + "    image_name: beta-app\n")
        assert product_registry.derived_image("beta", path) == "gitea.kubelab.live/personal/beta-app"

    def test_a_product_without_image_registry_keeps_the_platform_default(self, fixture_registry: Path) -> None:
        assert product_registry.derived_image("web") == f"{product_registry.platform_registry()}/kubelab-web"

    def test_image_registry_is_not_a_contract_key(self) -> None:
        """D4: the registry entry owns the host; a values key would be a second copy of the fact."""
        from toolkit.features.product_render import CONTRACT_KEYS

        assert "image_registry" not in CONTRACT_KEYS

    def test_each_real_product_derives_the_image_its_values_deploy(self) -> None:
        """The override and ``apps.platform.<app>.image_name`` must name one image."""
        common = yaml.safe_load((REPO / "infra" / "config" / "values" / "common.yaml").read_text(encoding="utf-8"))
        checked = 0
        for app, product in product_registry.load_registry().products.items():
            if not product.contract_managed:
                continue
            deployed = f"{common['registry']}/{common['apps']['platform'][app]['image_name']}"
            assert product_registry.derived_image(app) == deployed, app
            checked += 1
        assert checked > 0


def _undeployable(
    env: str, common: dict[str, dict], overlay: dict[str, dict], registry: Path | None = None
) -> dict[str, list[str]]:
    """``{app: fields it lacks}`` for each product declaring a lane in ``env``."""
    missing = {}
    for app in apps_declaring(env, registry):
        block = {**(common.get(app) or {}), **(overlay.get(app) or {})}
        if absent := [field for field in DEPLOY_FIELDS if not block.get(field)]:
            missing[app] = absent
    return missing


def _platform_blocks(env: str) -> dict[str, dict]:
    values = yaml.safe_load((REPO / "infra" / "config" / "values" / f"{env}.yaml").read_text(encoding="utf-8")) or {}
    return dict((values.get("apps") or {}).get("platform") or {})
