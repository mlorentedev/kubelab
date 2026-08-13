"""Tests for `K8sGenerator._extract_app_env_vars` ConfigMap env selection.

Guards ADR-051 D4: a shared `infra.postgres.image` pin must not leak into every
component's ConfigMap. Deploy-concern keys (image refs / version pins) are never
runtime env, so they are excluded for both the prefix-stripped (APPS_PLATFORM_*)
and the unstripped shared (INFRA_*) forms.
"""

from __future__ import annotations

from toolkit.features.generator_k8s import K8sGenerator


class TestDeployConcernGuard:
    """`*_IMAGE` / `*_VERSION` keys never reach a ConfigMap."""

    def test_infra_image_excluded_but_connection_attrs_kept(self) -> None:
        env = {
            "INFRA_POSTGRES_HOST": "postgres",
            "INFRA_POSTGRES_PORT": "5432",
            "INFRA_POSTGRES_DATABASE": "kubelab",
            "INFRA_POSTGRES_USERNAME": "kubelab",
            "INFRA_POSTGRES_IMAGE": "postgres:16-alpine",
        }
        result = K8sGenerator()._extract_app_env_vars(env, "api")

        # Deploy concern dropped …
        assert "INFRA_POSTGRES_IMAGE" not in result
        # … runtime connection attrs kept (username/database/host survive the
        # SECRET_PATTERNS filter — none are PASS/PASSWORD/SECRET/TOKEN/KEY/etc).
        assert result["INFRA_POSTGRES_HOST"] == "postgres"
        assert result["INFRA_POSTGRES_PORT"] == "5432"
        assert result["INFRA_POSTGRES_DATABASE"] == "kubelab"
        assert result["INFRA_POSTGRES_USERNAME"] == "kubelab"

    def test_infra_version_excluded(self) -> None:
        env = {"INFRA_FOO_VERSION": "1.2.3", "INFRA_FOO_HOST": "foo"}
        result = K8sGenerator()._extract_app_env_vars(env, "api")
        assert "INFRA_FOO_VERSION" not in result
        assert result["INFRA_FOO_HOST"] == "foo"

    def test_guard_is_noop_on_current_infra_smtp_set(self) -> None:
        """Regression: today's INFRA_SMTP_* keys must pass through unchanged."""
        env = {
            "INFRA_SMTP_FROM": "mlorentedev",
            "INFRA_SMTP_HOST": "smtp.gmail.com",
            "INFRA_SMTP_PORT": "587",
            "INFRA_SMTP_SECURE": "true",
            "INFRA_SMTP_USER": "mlorentedev@gmail.com",
        }
        result = K8sGenerator()._extract_app_env_vars(env, "api")
        assert result == env


class TestPlacementClassificationGuard:
    """ADR028-004 placement keys never reach a ConfigMap.

    `state_promotion` and `location` are read by a static gate
    (`tests/test_stateful_service_classification.py`), never by a running pod.
    Seven of the eight classified services live under `apps.services.*`, which
    this method never picks up. The eighth is `postgres` at `infra.postgres`
    (ADR-051) — so without the guard its two keys would be emitted as
    `INFRA_POSTGRES_*` into EVERY component's ConfigMap, changing every
    configMapGenerator hash and rolling every pod on the next deploy.
    """

    def test_infra_postgres_placement_keys_excluded(self) -> None:
        env = {
            "INFRA_POSTGRES_HOST": "postgres",
            "INFRA_POSTGRES_STATE_PROMOTION": "dual",
            "INFRA_POSTGRES_LOCATION": "always-on",
        }
        result = K8sGenerator()._extract_app_env_vars(env, "api")

        assert "INFRA_POSTGRES_STATE_PROMOTION" not in result
        assert "INFRA_POSTGRES_LOCATION" not in result
        assert result["INFRA_POSTGRES_HOST"] == "postgres"

    def test_prefix_stripped_placement_keys_excluded(self) -> None:
        """The APPS_PLATFORM_* form is guarded too, for any future consumer."""
        env = {
            "APPS_PLATFORM_API_STATE_PROMOTION": "dual",
            "APPS_PLATFORM_API_LOCATION": "always-on",
            # Not HEALTH_PATH: that is already in _METADATA_SUFFIXES, so it would
            # be dropped by the older guard and prove nothing about this one.
            "APPS_PLATFORM_API_LOG_LEVEL": "info",
        }
        result = K8sGenerator()._extract_app_env_vars(env, "api")

        assert "STATE_PROMOTION" not in result
        assert "LOCATION" not in result
        assert result["LOG_LEVEL"] == "info"

    def test_unrelated_location_key_survives_without_its_promotion_sibling(self) -> None:
        """The regression a suffix blocklist could not have caught.

        `INFRA_GEO_LOCATION` is an ordinary runtime setting that ends in
        `_LOCATION` exactly like the classification key does, so no
        suffix-matching rule can tell them apart. It is kept because no
        `INFRA_GEO_STATE_PROMOTION` travels with it, while postgres's pair in
        the same map is still excluded.
        """
        env = {
            "INFRA_GEO_LOCATION": "eu-central",
            "INFRA_POSTGRES_STATE_PROMOTION": "dual",
            "INFRA_POSTGRES_LOCATION": "always-on",
        }
        result = K8sGenerator()._extract_app_env_vars(env, "api")

        assert result["INFRA_GEO_LOCATION"] == "eu-central"
        assert "INFRA_POSTGRES_STATE_PROMOTION" not in result
        assert "INFRA_POSTGRES_LOCATION" not in result

    def test_unrelated_promotion_key_survives(self) -> None:
        """`*_PROMOTION` alone is not `*_STATE_PROMOTION`."""
        env = {"INFRA_CAMPAIGN_PROMOTION": "summer", "INFRA_GEO_ALLOCATION": "eu"}
        result = K8sGenerator()._extract_app_env_vars(env, "api")

        assert result["INFRA_CAMPAIGN_PROMOTION"] == "summer"
        assert result["INFRA_GEO_ALLOCATION"] == "eu"

    def test_orphan_location_without_any_promotion_key_survives(self) -> None:
        """A classified service that somehow lost its promotion axis is a gate
        problem, not a generator one — the generator must not silently swallow
        the key, or the omission becomes invisible."""
        env = {"INFRA_POSTGRES_LOCATION": "always-on"}
        result = K8sGenerator()._extract_app_env_vars(env, "api")

        assert result["INFRA_POSTGRES_LOCATION"] == "always-on"
