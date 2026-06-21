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
