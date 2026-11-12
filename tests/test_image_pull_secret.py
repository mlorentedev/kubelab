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

    def test_the_committed_registry_adds_no_secret_so_the_applied_set_is_unchanged(self) -> None:
        assert pull_secret_mappings(product_registry.load_registry()) == []
        assert not [m for m in ks._definitions_for_env("prod", ks.SECRET_DEFINITIONS) if m.name.startswith("pull-")]

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
