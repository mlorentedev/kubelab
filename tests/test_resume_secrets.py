"""RES-HOST-001 slice H: resume's secrets reach a Secret, never the ConfigMap.

The generated `resume` ConfigMap is built by `K8sGenerator._extract_app_env_vars`,
which keeps every `APPS_PLATFORM_RESUME_*` key and filters secrets only by a
word list on the key's NAME (`SECRET_PATTERNS`). It does not consult the catalog, so
the catalog-wide test below is the cross-check: the day someone catalogues a
leaf with none of those words, it fails instead of the value reaching the
ConfigMap in plaintext, readable by anyone who can `kubectl get cm`.

Every test builds a synthetic environment from catalog KEY PATHS; no value is
decrypted, so the tests measure the filter and the mapping, not a vault.
"""

from __future__ import annotations

import pytest

from toolkit.features.generator_k8s import K8sGenerator
from toolkit.features.k8s_secrets import SECRET_DEFINITIONS
from toolkit.features.secrets_manager import SECRET_CATALOG, SecretSpec

LLM_KEY = "apps.platform.resume.llm_api_key"
NOTIFY_BEARER = "apps.services.automation.notify.webhook_secret"
SENTINEL = "decrypted-value-must-not-appear"


def _flatten(key_path: str) -> str:
    """The env var name a catalog key path flattens to."""
    return key_path.upper().replace(".", "_")


def _configmap_for(component: str, env: dict[str, str]) -> dict[str, str]:
    return K8sGenerator()._extract_app_env_vars(env, component)


def _catalog_by_path() -> dict[str, SecretSpec]:
    return {spec.key_path: spec for spec in SECRET_CATALOG}


def _component_secrets() -> list[tuple[str, str]]:
    """(component, key_path) for every catalogued secret under `apps.platform.<component>`
    and every shared `infra.*` secret, paired with a component that would read it."""
    pairs: list[tuple[str, str]] = []
    for spec in SECRET_CATALOG:
        parts = spec.key_path.split(".")
        if parts[0] == "apps" and parts[1] == "platform" and len(parts) > 3:
            pairs.append((parts[2], spec.key_path))
        elif parts[0] == "infra":
            pairs.append(("resume", spec.key_path))
    return pairs


class TestConfigMapNeverCarriesACataloguedSecret:
    def test_the_guard_has_something_to_check(self) -> None:
        """An empty parametrize set collects zero tests and passes, so the guard could vanish silently.

        The resume key is the case slice H exists for; if it is missing, so is the guard.
        """
        pairs = _component_secrets()

        assert pairs, "no catalogued secret was paired with a component: the guard below checks nothing"
        assert ("resume", LLM_KEY) in pairs

    @pytest.mark.parametrize(("component", "key_path"), _component_secrets())
    def test_catalogued_secret_is_not_in_its_components_configmap(self, component: str, key_path: str) -> None:
        env = {_flatten(key_path): SENTINEL, f"APPS_PLATFORM_{component.upper()}_PORT": "8765"}

        result = _configmap_for(component, env)

        leaked = {k: v for k, v in result.items() if v == SENTINEL}
        assert leaked == {}, f"{key_path} reached the {component} ConfigMap as {sorted(leaked)}"
        assert result["PORT"] == "8765", "the probe must still pass an ordinary key through"


class TestResumeSecretsSecret:
    def test_llm_key_is_catalogued_for_staging_and_prod(self) -> None:
        spec = _catalog_by_path()[LLM_KEY]
        assert {"staging", "prod"} <= set(spec.envs)

    def test_resume_secrets_maps_the_llm_key_and_the_notify_bearer(self) -> None:
        [mapping] = [m for m in SECRET_DEFINITIONS if m.name == "resume-secrets"]

        assert mapping.optional_keys["RESUME_LLM_API_KEY"] == _flatten(LLM_KEY)
        assert mapping.keys["RESUME_NOTIFY_WEBHOOK_TOKEN"] == _flatten(NOTIFY_BEARER)

    def test_every_source_of_resume_secrets_is_catalogued(self) -> None:
        """A mapping to an uncatalogued key is a Secret `audit` can never report on."""
        [mapping] = [m for m in SECRET_DEFINITIONS if m.name == "resume-secrets"]
        catalogued = {_flatten(spec.key_path) for spec in SECRET_CATALOG}

        assert {*mapping.keys.values(), *mapping.optional_keys.values()} <= catalogued

    def test_resume_secrets_applies_in_every_environment_resume_runs(self) -> None:
        """Not prod-only: staging is where resume deploys first (RES-HOST-001)."""
        [mapping] = [m for m in SECRET_DEFINITIONS if m.name == "resume-secrets"]
        assert mapping.envs is None or "staging" in mapping.envs
