"""The image pull Secret `apply-secrets` renders for a private product (IDP-053 D6, #2612).

A private product's image is pulled with a registry login, so the cluster needs a
`kubernetes.io/dockerconfigjson` Secret named from the registry host. The token
stays in SOPS; the Secret is a literal rendered from it at apply time. These tests
drive the real `apply_secrets` path, with kubectl as the only fake, and check what
kubectl is handed and what the operator's log shows.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from toolkit.features import k8s_secrets as ks
from toolkit.features import product_registry
from toolkit.features.k8s_secrets import (
    DOCKERCONFIGJSON,
    SecretMapping,
    _apply_single_secret,
    _render_secret_manifest,
    pull_secret_mappings,
    pull_secret_name,
)

TOKEN = "fake-pull-token-do-not-leak"  # noqa: S105 - a test value
HOST = "gitea.kubelab.live"
ENTRY = """\
  {name}:
    repository: personal/{name}
    forge: gitea
    receiver: generic
    image_registry: {host}/personal
    private: true
    pull_credential: {{username: reviewer, secret: {secret}}}
"""


def _registry(tmp_path: Path, *entries: str) -> product_registry.Registry:
    path = tmp_path / "products.yaml"
    path.write_text("products:\n  api:\n    forge: in-tree\n" + "".join(entries), encoding="utf-8")
    return product_registry.load_registry(path)


def _entry(name: str = "beta", host: str = HOST, secret: str = "ghcr.pull_token") -> str:
    return ENTRY.format(name=name, host=host, secret=secret)


def _applied_secret(stdin: str) -> dict:
    return yaml.safe_load(stdin)


class TestMappingFromTheRegistry:
    def test_a_private_entry_yields_one_pull_secret_named_from_its_host(self, tmp_path: Path) -> None:
        (mapping,) = pull_secret_mappings(_registry(tmp_path, _entry()))

        assert mapping.name == "pull-gitea-kubelab-live" == pull_secret_name(HOST)
        assert mapping.secret_type == DOCKERCONFIGJSON == "kubernetes.io/dockerconfigjson"
        assert mapping.namespace == "kubelab"

    def test_two_private_entries_on_one_host_share_one_secret(self, tmp_path: Path) -> None:
        mappings = pull_secret_mappings(_registry(tmp_path, _entry("beta"), _entry("gamma")))

        assert [m.name for m in mappings] == ["pull-gitea-kubelab-live"]

    def test_two_hosts_yield_two_secrets(self, tmp_path: Path) -> None:
        registry = _registry(tmp_path, _entry("beta"), _entry("gamma", host="ghcr.io", secret="ghcr.pull_token"))

        assert sorted(m.name for m in pull_secret_mappings(registry)) == ["pull-ghcr-io", "pull-gitea-kubelab-live"]

    def test_a_registry_with_no_private_entry_adds_no_secret(self, tmp_path: Path) -> None:
        assert pull_secret_mappings(_registry(tmp_path)) == []

    def test_the_committed_registry_adds_one_gitea_secret_and_only_staging_deploys_it(self) -> None:
        """IDP-053 S3b: imagesensortool is the one private entry; it declares no prod lane, so prod gets no Secret
        from a product (the pull Secret itself still applies in both envs where its token is catalogued)."""
        (mapping,) = pull_secret_mappings(product_registry.load_registry())

        assert mapping.name == pull_secret_name(HOST)
        prod = ks._definitions_for_env("prod", ks.SECRET_DEFINITIONS)
        assert [m.name for m in prod if m.name.startswith("pull-")] == []

    def test_the_token_is_read_from_the_variable_the_catalog_key_flattens_to(self, tmp_path: Path) -> None:
        (mapping,) = pull_secret_mappings(_registry(tmp_path, _entry(secret="ghcr.pull_token", host="ghcr.io")))

        assert list(mapping.keys.values()) == ["GHCR_PULL_TOKEN"]

    def test_the_mapping_applies_in_the_envs_its_token_is_catalogued_for(self, tmp_path: Path) -> None:
        (mapping,) = pull_secret_mappings(_registry(tmp_path, _entry(secret="ghcr.pull_token", host="ghcr.io")))

        assert mapping.envs == ("staging", "prod")

    def test_two_hosts_that_slug_alike_are_refused(self, tmp_path: Path) -> None:
        registry = _registry(
            tmp_path, _entry("beta", host="git.example.com"), _entry("gamma", host="git-example.com")
        )

        with pytest.raises(ValueError, match="pull-git-example-com"):
            pull_secret_mappings(registry)

    def test_an_uncatalogued_pull_secret_is_refused_naming_the_product_and_the_key(self, tmp_path: Path) -> None:
        registry = _registry(tmp_path, _entry("beta", secret="gitea.registry_pull"))

        with pytest.raises(product_registry.RegistryError, match=r"beta names pull_credential\.secret 'gitea\.registry_pull'"):
            pull_secret_mappings(registry)


class TestRenderSecretManifest:
    def test_the_type_defaults_to_opaque(self) -> None:
        assert yaml.safe_load(_render_secret_manifest("x", "kubelab", {"a": "b"}))["type"] == "Opaque"

    def test_the_type_is_the_one_asked_for(self) -> None:
        doc = yaml.safe_load(_render_secret_manifest("x", "kubelab", {"a": "b"}, DOCKERCONFIGJSON))

        assert doc["type"] == DOCKERCONFIGJSON


def _mapping(tmp_path: Path) -> SecretMapping:
    return pull_secret_mappings(_registry(tmp_path, _entry()))[0]


def _env(mapping: SecretMapping, value: str = TOKEN) -> dict[str, str]:
    return {env_var: value for env_var in mapping.keys.values()}


class TestApplyingThePullSecret:
    @pytest.fixture(autouse=True)
    def _kubectl(self, mocker, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ks, "_get_kubeconfig", lambda env: f"/kube/{env}")
        self.run = mocker.patch.object(
            ks.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="secret/x created", stderr="")
        )
        self.log = mocker.patch.object(ks, "logger")

    def _logged(self) -> str:
        return " ".join(str(c) for call in self.log.method_calls for c in (*call.args, *call.kwargs.values()))

    @pytest.mark.parametrize("dry_run", [False, True])
    def test_the_dockerconfigjson_decodes_to_the_auths_shape(self, tmp_path: Path, dry_run: bool) -> None:
        mapping = _mapping(tmp_path)

        assert _apply_single_secret(mapping, _env(mapping), {}, dry_run=dry_run, env="prod") is True

        doc = _applied_secret(self.run.call_args.kwargs["input"])
        assert (doc["type"], doc["metadata"]["name"]) == (DOCKERCONFIGJSON, "pull-gitea-kubelab-live")
        assert list(doc["data"]) == [".dockerconfigjson"]
        decoded = json.loads(base64.b64decode(doc["data"][".dockerconfigjson"]))
        auth = base64.b64encode(f"reviewer:{TOKEN}".encode()).decode()
        assert decoded == {"auths": {HOST: {"username": "reviewer", "password": TOKEN, "auth": auth}}}

    @pytest.mark.parametrize("dry_run", [False, True])
    def test_the_token_reaches_no_argv_and_no_log_line(self, tmp_path: Path, dry_run: bool) -> None:
        mapping = _mapping(tmp_path)

        _apply_single_secret(mapping, _env(mapping), {}, dry_run=dry_run, env="prod")

        argv = self.run.call_args.args[0]
        assert not any(TOKEN in part for part in argv)
        assert TOKEN not in self.run.call_args.kwargs["input"], "only base64 rides in the manifest"
        logged = self._logged()
        assert TOKEN not in logged
        assert base64.b64encode(TOKEN.encode()).decode() not in logged
        if dry_run:
            assert ".dockerconfigjson" in logged, "the preview names the key, never its value"

    @pytest.mark.parametrize("value", ["", None])
    def test_a_missing_token_is_refused_and_kubectl_never_runs(self, tmp_path: Path, value: str | None) -> None:
        mapping = _mapping(tmp_path)
        env = {} if value is None else _env(mapping, value)

        assert _apply_single_secret(mapping, env, {}, dry_run=False, env="prod") is False
        self.run.assert_not_called()

    def test_an_opaque_secret_is_rendered_as_before(self) -> None:
        mapping = SecretMapping(name="x", keys={"token": "TOKEN_ENV"})

        _apply_single_secret(mapping, {"TOKEN_ENV": "v"}, {}, dry_run=False)

        doc = _applied_secret(self.run.call_args.kwargs["input"])
        assert (doc["type"], list(doc["data"])) == ("Opaque", ["token"])


class TestApplySecretsDeliversIt:
    """The wiring: `apply_secrets` must reach the generated mapping, with the token from the vault."""

    def test_a_private_registry_entry_is_applied_with_the_vault_token(
        self, tmp_path: Path, mocker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        registry = _registry(tmp_path, _entry(secret="ghcr.pull_token", host="ghcr.io"))
        monkeypatch.setattr(ks, "load_registry", lambda: registry)
        monkeypatch.setattr(ks, "_get_kubeconfig", lambda env: f"/kube/{env}")
        monkeypatch.setattr(ks, "SECRET_DEFINITIONS", [])
        monkeypatch.setattr(ks, "RETIRED_SECRETS", ())
        monkeypatch.setattr(ks, "_build_dynamic_literals", lambda cm: {"grafana-admin": {"admin-user": "bg"}})
        cm = mocker.MagicMock()
        cm.get_env_vars.return_value = {"GHCR_PULL_TOKEN": TOKEN}
        cm.get_merged_config.return_value = {}
        monkeypatch.setattr(ks, "ConfigurationManager", lambda *a, **k: cm)
        run = mocker.patch.object(
            ks.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="secret/x unchanged", stderr="")
        )
        log = mocker.patch.object(ks, "logger")

        assert ks.apply_secrets("prod", Path("."), dry_run=False) is True, log.error.call_args_list

        doc = _applied_secret(run.call_args.kwargs["input"])
        decoded = json.loads(base64.b64decode(doc["data"][".dockerconfigjson"]))
        assert (doc["metadata"]["name"], list(decoded["auths"])) == ("pull-ghcr-io", ["ghcr.io"])
        assert decoded["auths"]["ghcr.io"]["password"] == TOKEN

    def test_an_uncatalogued_pull_secret_is_refused_before_kubectl_runs(
        self, tmp_path: Path, mocker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        registry = _registry(tmp_path, _entry(secret="gitea.registry_pull"))
        monkeypatch.setattr(ks, "load_registry", lambda: registry)
        cm = mocker.MagicMock()
        cm.get_env_vars.return_value = {"GITEA_REGISTRY_PULL": TOKEN}
        cm.get_merged_config.return_value = {}
        monkeypatch.setattr(ks, "ConfigurationManager", lambda *a, **k: cm)
        run = mocker.patch.object(ks.subprocess, "run")

        with pytest.raises(product_registry.RegistryError, match="gitea.registry_pull"):
            ks.apply_secrets("prod", Path("."), dry_run=False)

        run.assert_not_called()


class TestTheDeploymentCarriesThePullSecret:
    """IDP-053 AC3 (S2b): the Deployment names the Secret `apply-secrets` renders, and only for a private product.

    Rendered through the real generator context and the real template, so what is asserted is what
    `sync all` writes, not the shape of a context dict.
    """

    REGISTRY = """\
products:
  web:
    repository: mlorentedev/web
    forge: github
    receiver: generic
    image_name: kubelab-web
    events: {staging: web-image-published, prod: web-release-published}
  beta:
    repository: personal/beta
    forge: gitea
    receiver: generic
    image_registry: gitea.kubelab.live/personal
    private: true
    pull_credential: {username: reviewer, secret: ghcr.pull_token}
    events: {staging: beta-image-published}
  gamma:
    repository: personal/gamma
    forge: gitea
    receiver: generic
    image_registry: gitea.kubelab.live/personal
    events: {staging: gamma-image-published}
"""

    @staticmethod
    def _values(*apps: str) -> dict[str, str]:
        values = {"REGISTRY": "docker.io/mlorentedev"}
        for app in apps:
            prefix = f"APPS_PLATFORM_{app.upper()}"
            values |= {
                f"{prefix}_IMAGE_NAME": app,
                f"{prefix}_DOMAIN": f"{app}.staging.example.test",
                f"{prefix}_DEFAULT_PORT": "8080",
                f"{prefix}_VERSION": "sha-0123456789ab",
            }
        return values

    def _deployments(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, dict]:
        from unittest.mock import MagicMock

        from toolkit.core.templating import create_renderer
        from toolkit.features import generator_k8s
        from toolkit.features.generator_k8s import K8sGenerator

        path = tmp_path / "products.yaml"
        path.write_text(self.REGISTRY, encoding="utf-8")
        monkeypatch.setattr(product_registry, "registry_path", lambda: path)
        manager = MagicMock()
        manager.return_value.get_env_vars.return_value = self._values("web", "beta", "gamma")
        monkeypatch.setattr(generator_k8s, "ConfigurationManager", manager)
        monkeypatch.setattr(K8sGenerator, "_build_migrations", lambda self, env_vars: {})
        generator = K8sGenerator()
        out = tmp_path / "deployments.yaml"
        assert create_renderer(generator.project_root / "infra/k8s/templates").render_template(
            "deployments.yaml.j2", out, generator._build_context("staging")
        )
        return {d["metadata"]["name"]: d for d in yaml.safe_load_all(out.read_text(encoding="utf-8")) if d}

    def test_a_private_product_pulls_with_the_secret_apply_secrets_renders(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        beta = self._deployments(tmp_path, monkeypatch)["beta"]

        assert beta["spec"]["template"]["spec"]["imagePullSecrets"] == [{"name": pull_secret_name(HOST)}]
        assert pull_secret_name(HOST) == "pull-gitea-kubelab-live"

    def test_the_name_is_the_one_the_secret_mapping_creates(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Deployment and Secret derive the name separately; a drift between them is a pod that never starts."""
        deployments = self._deployments(tmp_path, monkeypatch)
        (mapping,) = pull_secret_mappings(product_registry.load_registry(tmp_path / "products.yaml"))

        assert deployments["beta"]["spec"]["template"]["spec"]["imagePullSecrets"] == [{"name": mapping.name}]

    @pytest.mark.parametrize("app", ["web", "gamma"], ids=["platform-registry", "non-private-forge-registry"])
    def test_a_product_that_is_not_private_gets_no_pull_secret(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, app: str
    ) -> None:
        """A registry host alone does not make an image private: only the entry's `private` does."""
        assert "imagePullSecrets" not in self._deployments(tmp_path, monkeypatch)[app]["spec"]["template"]["spec"]

    @pytest.mark.parametrize("env", ["staging", "prod"])
    def test_every_committed_deployment_is_byte_identical(self, env: str, tmp_path: Path) -> None:
        """The committed files are what the template renders, and only imagesensortool pulls with a Secret.

        Compared with the file committed before this change, not with a second render of the new
        template: `make validate-sync` would pass on a template that changed both.
        """
        from toolkit.core.templating import create_renderer
        from toolkit.features.generator_k8s import K8sGenerator

        generator = K8sGenerator()
        out = tmp_path / "deployments.yaml"
        assert create_renderer(generator.project_root / "infra/k8s/templates").render_template(
            "deployments.yaml.j2", out, generator._build_context(env)
        )
        committed = generator.project_root / f"infra/k8s/overlays/{env}/generated/deployments.yaml"

        assert out.read_bytes() == committed.read_bytes()
        pulls = [
            d["metadata"]["name"]
            for d in yaml.safe_load_all(committed.read_text(encoding="utf-8"))
            if d and d["spec"]["template"]["spec"].get("imagePullSecrets")
        ]
        assert pulls == (["imagesensortool"] if env == "staging" else [])
