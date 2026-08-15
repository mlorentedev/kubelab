"""SEC-004: `_build_middlewares()` must include `rate-limit` in every route.

The K3s rate limit is blanket (kubelab#970) -- there is no per-route opt-out,
so unlike `enable_auth` this middleware is unconditional.
"""

from __future__ import annotations

from toolkit.features.generator_k8s import K8sGenerator


class TestBuildMiddlewaresIncludesRateLimit:
    def test_unauthenticated_route_includes_rate_limit(self) -> None:
        middlewares = K8sGenerator()._build_middlewares(env_vars={}, enable_auth=False)
        assert "rate-limit" in middlewares

    def test_authenticated_route_includes_rate_limit(self) -> None:
        middlewares = K8sGenerator()._build_middlewares(env_vars={}, enable_auth=True)
        assert "rate-limit" in middlewares

    def test_existing_middlewares_are_not_dropped(self) -> None:
        """Regression guard: adding rate-limit must not regress the pre-existing chain."""
        middlewares = K8sGenerator()._build_middlewares(env_vars={}, enable_auth=False)
        assert "secure-headers" in middlewares
        assert "error-pages" in middlewares
