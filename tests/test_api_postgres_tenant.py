"""DATA-007: the API connects to Postgres as its own tenant, never as the server's owner."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import typer
import yaml

from toolkit.cli import infra
from toolkit.features.k8s_secrets import SECRET_DEFINITIONS
from toolkit.features.postgres_provisioner import TENANT_PASSWORD_PATHS
from toolkit.features.secrets_manager import SECRET_CATALOG

REPO_ROOT = Path(__file__).resolve().parent.parent
API_SECRETS = next(m for m in SECRET_DEFINITIONS if m.name == "api-secrets")


def _api_configmap(env: str) -> dict[str, str]:
    path = REPO_ROOT / "infra" / "k8s" / "overlays" / env / "generated" / "configmaps.yaml"
    docs = yaml.safe_load_all(path.read_text(encoding="utf-8"))
    return next(d["data"] for d in docs if d and d["metadata"]["name"] == "api-config")


def test_every_tenant_password_is_catalogued_per_env() -> None:
    catalog = {spec.key_path: spec for spec in SECRET_CATALOG}
    for tenant, key_path in TENANT_PASSWORD_PATHS.items():
        assert key_path in catalog, f"{tenant}: {key_path} is not in SECRET_CATALOG"
        assert set(catalog[key_path].envs) == {"staging", "prod"}


def test_api_secret_carries_the_tenant_password_and_not_the_owners() -> None:
    assert API_SECRETS.optional_keys["POSTGRES_TENANT_PASSWORD"] == "APPS_PLATFORM_API_DB_PASSWORD"
    assert "INFRA_POSTGRES_PASSWORD" not in {*API_SECRETS.keys.values(), *API_SECRETS.optional_keys.values()}


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_api_configmap_names_the_tenant_and_holds_no_password(env: str) -> None:
    data = _api_configmap(env)
    assert data["POSTGRES_TENANT"] == "api"
    assert not any("PASSWORD" in key for key in data)


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_postgres_admits_the_api(env: str) -> None:
    path = REPO_ROOT / "infra" / "k8s" / "base" / "governance" / "networkpolicies.yaml"
    policy = next(
        d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d["metadata"]["name"] == "postgres-ingress"
    )
    sources = [peer["podSelector"]["matchLabels"]["app.kubernetes.io/name"] for peer in policy["spec"]["ingress"][0]["from"]]
    assert "api" in sources


def _mock(mocker, returncode: int = 0):
    mocker.patch.object(infra, "_get_kubeconfig", return_value="/kubeconfig")
    cfg = mocker.Mock()
    cfg.get_secret_by_path.return_value = "fixture"
    mocker.patch("toolkit.features.configuration.ConfigurationManager", return_value=cfg)
    run = mocker.patch("subprocess.run", return_value=SimpleNamespace(returncode=returncode, stderr=""))
    return cfg, run


def test_without_a_tenant_every_declared_tenant_is_provisioned(mocker) -> None:
    cfg, run = _mock(mocker)
    infra.k8s_provision_postgres_tenant(env="staging", tenant=None, dry_run=False)
    assert run.call_count == len(TENANT_PASSWORD_PATHS)
    read = {call.args[0] for call in cfg.get_secret_by_path.call_args_list}
    assert read == set(TENANT_PASSWORD_PATHS.values())


def test_an_undeclared_tenant_is_refused(mocker) -> None:
    _, run = _mock(mocker)
    with pytest.raises(typer.Exit) as exc:
        infra.k8s_provision_postgres_tenant(env="staging", tenant="nobody", dry_run=False)
    assert exc.value.exit_code == 1
    run.assert_not_called()


def test_a_missing_password_stops_the_provisioning(mocker) -> None:
    cfg, run = _mock(mocker)
    cfg.get_secret_by_path.return_value = ""
    with pytest.raises(typer.Exit):
        infra.k8s_provision_postgres_tenant(env="staging", tenant="api", dry_run=False)
    run.assert_not_called()
