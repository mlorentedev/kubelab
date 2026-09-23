"""SSOT-017: `apps.services.security.authelia.oidc_clients` is the only declaration of an OIDC client.

The guard at the bottom compares what Authelia is actually configured with — the
committed K8s config files, read as Authelia reads them — against what the SSOT
resolves to. It needs no SOPS: `client_secret` is the one field it does not
compare, so it runs in CI, where the OIDC hash drift check is skipped.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.features import oidc_clients

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _values(clients: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "apps": {
            "services": {
                "security": {"authelia": {"oidc_clients": clients}},
                "observability": {"grafana": {"domain": "grafana.example.test"}},
            }
        },
    }


def _grafana(**overrides: Any) -> dict[str, Any]:
    client = {
        "client_id": "grafana",
        "client_name": "Grafana",
        "envs": ["staging", "prod"],
        "redirect": {"domain": "apps.services.observability.grafana.domain", "path": "/login/generic_oauth"},
        "scopes": ["openid", "profile", "email", "groups"],
        "token_endpoint_auth_method": "client_secret_basic",
        "authorization_policy": "one_factor",
        "consent_mode": "implicit",
    }
    client.update(overrides)
    return client


class TestResolve:
    def test_resolves_redirect_host_from_the_declared_domain(self) -> None:
        [client] = oidc_clients.resolve_clients(_values([_grafana()]), "prod")

        assert client["redirect_uris"] == ["https://grafana.example.test/login/generic_oauth"]
        assert client["public"] is False
        assert "envs" not in client and "redirect" not in client

    def test_a_client_is_absent_from_an_env_it_does_not_declare(self) -> None:
        assert oidc_clients.resolve_clients(_values([_grafana(envs=["prod"])]), "staging") == []

    @pytest.mark.parametrize("field", ["token_endpoint_auth_method", "authorization_policy"])
    def test_a_missing_required_field_fails_naming_the_client(self, field: str) -> None:
        client = _grafana()
        del client[field]

        with pytest.raises(oidc_clients.OidcClientError, match=rf"grafana.*{field}"):
            oidc_clients.resolve_clients(_values([client]), "prod")

    def test_a_domain_reference_that_resolves_to_nothing_fails(self) -> None:
        client = _grafana(redirect={"domain": "apps.services.observability.nope.domain", "path": "/cb"})

        with pytest.raises(oidc_clients.OidcClientError, match="grafana"):
            oidc_clients.resolve_clients(_values([client]), "prod")

    def test_an_unknown_env_fails(self) -> None:
        with pytest.raises(oidc_clients.OidcClientError, match="grafana"):
            oidc_clients.resolve_clients(_values([_grafana(envs=["prdo"])]), "prod")


class TestDigestKey:
    @pytest.mark.parametrize(
        ("client_id", "key"),
        [
            ("grafana", "apps.services.security.authelia.oidc_client_secret_grafana_hash"),
            ("vikunja-oidc", "apps.services.security.authelia.oidc_client_secret_vikunja_hash"),
            ("some-thing", "apps.services.security.authelia.oidc_client_secret_some_thing_hash"),
        ],
    )
    def test_convention(self, client_id: str, key: str) -> None:
        assert oidc_clients.digest_key(client_id) == key


def _committed_clients(env: str) -> list[dict[str, Any]]:
    """Clients as Authelia sees them: every file in the env's authelia-config, merged."""
    clients: list[dict[str, Any]] = []
    for path in oidc_clients.config_files(env):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        found = ((doc.get("identity_providers") or {}).get("oidc") or {}).get("clients")
        if found is not None:
            clients.extend(found)
    return clients


def _without_secret(clients: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    stripped = {}
    for client in copy.deepcopy(clients):
        client.pop("client_secret", None)
        stripped[client["client_id"]] = client
    return stripped


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_oidc_clients_match_ssot(env: str) -> None:
    """AC1: the committed config registers exactly the SSOT's clients for `env`, field for field."""
    expected = _without_secret(oidc_clients.resolve_clients(oidc_clients.load_values(env), env))
    actual = _without_secret(_committed_clients(env))

    assert sorted(actual) == sorted(expected), f"{env}: registered client set differs from the SSOT"
    for client_id, fields in expected.items():
        assert actual[client_id] == fields, f"{env}: {client_id} differs from the SSOT"


class TestSoleWriter:
    """AC3: the generator is the only writer, and `--check` sees a stale digest."""

    def _merged(self, env: str, digest: str) -> dict[str, Any]:
        values = oidc_clients.load_values(env)
        auth = values["apps"]["services"]["security"]["authelia"]
        for client in oidc_clients.resolve_clients(values, env):
            auth[oidc_clients.digest_key(client["client_id"]).rsplit(".", 1)[1]] = f"$pbkdf2-fake-{digest}"
        return values

    def test_oidc_check_detects_stale_digest(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from toolkit.cli.sync import _run_with_check
        from toolkit.features import configuration

        monkeypatch.setitem(oidc_clients._CONFIG_DIRS, "prod", tmp_path)
        digest = {"value": "a"}
        monkeypatch.setattr(
            configuration.ConfigurationManager,
            "get_merged_config",
            lambda self: self_merged(self.env),
        )

        def self_merged(env: str) -> dict[str, Any]:
            return self._merged(env, digest["value"])

        assert oidc_clients.sync_env("prod", project_root=PROJECT_ROOT) == 0
        target = oidc_clients.clients_file("prod")
        assert _run_with_check([target], lambda: oidc_clients.sync_env("prod"), "oidc") is True

        digest["value"] = "b"  # the stored digest rotated; the file was not regenerated
        assert _run_with_check([target], lambda: oidc_clients.sync_env("prod"), "oidc") is False

    def test_a_missing_digest_fails_instead_of_skipping(self) -> None:
        values = oidc_clients.load_values("prod")
        with pytest.raises(oidc_clients.OidcClientError, match="no stored digest"):
            oidc_clients.build_clients_file("prod", values)

    def test_check_snapshots_exactly_the_files_the_generator_writes(self) -> None:
        from toolkit.cli.sync import _get_oidc_output_files

        assert set(_get_oidc_output_files()) == {oidc_clients.clients_file(e) for e in ("staging", "prod")}


def _kustomize(root: Path, env: str) -> list[dict[str, Any]]:
    """Render an overlay, or skip loudly: a skip means CANNOT CHECK, never OK."""
    import shutil
    import subprocess

    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not on PATH: the rendered Authelia config was NOT checked")
    out = subprocess.run(
        ["kubectl", "kustomize", str(root / "infra/k8s/overlays" / env)], capture_output=True, text=True, check=True
    ).stdout
    return [doc for doc in yaml.safe_load_all(out) if doc]


def _authelia(docs: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    [cm] = [d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"].startswith("authelia-config")]
    [dep] = [d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "authelia"]
    return cm, dep


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_authelia_config_split(env: str) -> None:
    """AC2: read from the EMITTED objects, never from the patches (lesson-404)."""
    cm, dep = _authelia(_kustomize(PROJECT_ROOT, env))
    main = yaml.safe_load(cm["data"]["configuration.yml"])
    clients = yaml.safe_load(cm["data"][oidc_clients.CLIENTS_FILE_NAME])

    assert "clients" not in main["identity_providers"]["oidc"], "clients must live only in the generated file"
    assert clients["identity_providers"]["oidc"]["clients"], "the generated client file is empty"

    container = dep["spec"]["template"]["spec"]["containers"][0]
    [config_env] = [e["value"] for e in container["env"] if e["name"] == "X_AUTHELIA_CONFIG"]
    mounted = {m["mountPath"] for m in container["volumeMounts"] if m["name"] == "config"}
    assert config_env.split(",") == ["/config/configuration.yml", f"/config/{oidc_clients.CLIENTS_FILE_NAME}"]
    assert set(config_env.split(",")) <= mounted, "Authelia is told to load a file that is not mounted"


def test_authelia_config_hash_changes_on_a_client_only_change(tmp_path: Path) -> None:
    """A client-file change must roll the pod: Authelia does not reload configuration (lesson-404)."""
    import shutil

    shutil.copytree(PROJECT_ROOT / "infra/k8s", tmp_path / "infra/k8s")
    before, _ = _authelia(_kustomize(tmp_path, "prod"))
    clients_path = tmp_path / "infra/k8s/overlays/prod/authelia-config" / oidc_clients.CLIENTS_FILE_NAME
    clients_path.write_text(clients_path.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
    after, _ = _authelia(_kustomize(tmp_path, "prod"))

    assert before["metadata"]["name"] != after["metadata"]["name"]
