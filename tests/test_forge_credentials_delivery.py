"""CONSOLE-004: the forge credentials reach the API, and only the public ones reach a ConfigMap.

The API reads four values (`apps/api/src/pkg/config/env.go`). Two are credentials and arrive through
`api-secrets`: the Gitea issue-reader token and the GitHub App's private key. Two are public
identifiers (the App ID and the installation ID) and arrive through the generated ConfigMap under
their shared infra names (ADR-036). The mapping is derived from the catalog, so a renamed
`key_path` breaks this test instead of leaving a Secret key that nothing fills.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from toolkit.features.k8s_secrets import SECRET_DEFINITIONS
from toolkit.features.secrets_manager import SECRET_CATALOG

REPO_ROOT = Path(__file__).resolve().parent.parent
GO_CONFIG = REPO_ROOT / "apps" / "api" / "src" / "pkg" / "config" / "env.go"

TOKEN_KEY = "apps.services.core.gitea.issue_reader_token"
PEM_KEY = "apps.services.core.github_app.private_key"

API_SECRETS = next(m for m in SECRET_DEFINITIONS if m.name == "api-secrets")


def _flattened(key_path: str) -> str:
    """Mirror `ConfigurationManager._flatten_dict`: dotted path -> UPPER_SNAKE."""
    return key_path.upper().replace(".", "_")


def _catalog(key_path: str):
    spec = next((s for s in SECRET_CATALOG if s.key_path == key_path), None)
    assert spec is not None, f"{key_path} must be registered in SECRET_CATALOG"
    return spec


def _configmap_data(env: str) -> dict[str, str]:
    """Every key of every ConfigMap the generator wrote for `env`."""
    path = REPO_ROOT / "infra" / "k8s" / "overlays" / env / "generated" / "configmaps.yaml"
    data: dict[str, str] = {}
    for doc in yaml.safe_load_all(path.read_text()):
        if doc and doc.get("kind") == "ConfigMap":
            data.update(doc.get("data") or {})
    return data


class TestSecretsReachTheApi:
    def test_the_token_and_the_key_are_mapped_from_their_catalog_entries(self) -> None:
        assert API_SECRETS.optional_keys["FORGE_GITEA_TOKEN"] == _flattened(TOKEN_KEY)
        assert API_SECRETS.optional_keys["FORGE_GITHUB_PRIVATE_KEY"] == _flattened(PEM_KEY)

    def test_both_are_catalogued_with_the_api_as_a_consumer(self) -> None:
        for key_path in (TOKEN_KEY, PEM_KEY):
            assert "api" in _catalog(key_path).services

    def test_they_are_optional_because_the_api_starts_without_them(self) -> None:
        # Staging holds no Gitea token. A required key would fail `apply-secrets ENV=staging`
        # for a workload that is meant to run there; `TestPopulateConfigForge` (Go) pins that the
        # API starts and reports the source unreachable instead.
        assert "FORGE_GITEA_TOKEN" not in API_SECRETS.keys
        assert "FORGE_GITHUB_PRIVATE_KEY" not in API_SECRETS.keys

    def test_the_go_side_reads_exactly_these_names(self) -> None:
        source = GO_CONFIG.read_text()
        for name in (
            "FORGE_GITEA_TOKEN",
            "FORGE_GITHUB_PRIVATE_KEY",
            "INFRA_FORGE_GITHUB_APP_ID",
            "INFRA_FORGE_GITHUB_INSTALLATION_ID",
        ):
            assert f'os.Getenv("{name}")' in source, f"env.go no longer reads {name}"


class TestOnlyPublicValuesReachAConfigMap:
    def test_the_ids_are_in_every_configmap_and_match_the_ssot(self) -> None:
        github = yaml.safe_load((REPO_ROOT / "infra/config/values/common.yaml").read_text())["infra"]["forge"][
            "github"
        ]
        for env in ("staging", "prod"):
            data = _configmap_data(env)
            assert data["INFRA_FORGE_GITHUB_APP_ID"] == str(github["app_id"])
            assert data["INFRA_FORGE_GITHUB_INSTALLATION_ID"] == str(github["installation_id"])

    def test_no_credential_lands_in_a_configmap(self) -> None:
        for env in ("staging", "prod"):
            names = set(_configmap_data(env))
            for forbidden in (
                "FORGE_GITEA_TOKEN",
                "FORGE_GITHUB_PRIVATE_KEY",
                _flattened(TOKEN_KEY),
                _flattened(PEM_KEY),
            ):
                assert forbidden not in names, f"{forbidden} must come from api-secrets, never a ConfigMap ({env})"

    def test_no_configmap_key_looks_like_the_private_key_or_the_token(self) -> None:
        # A different name for the same value would pass the list above.
        for env in ("staging", "prod"):
            for name in _configmap_data(env):
                if "FORGE" in name or "GITHUB_APP" in name:
                    assert not any(part in name for part in ("PRIVATE", "TOKEN", "SECRET")), name
