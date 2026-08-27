"""TOOLKIT-010: same-origin `/api` route on the web host (ADR-054, kubelab#774).

The web frontend posts to a relative `/api/subscribe` with no host baked in. The
generated IngressRoute only ever matched `Host(...)`, so that request reached the
static site and came back as the site's own 404 — the newsletter form has been
broken in staging and prod since it shipped.

These guard the two halves that were easy to get wrong: the route must be built
from the SSOT with the target's own port, and `EXTRA_ROUTES` must stay out of the
ConfigMap.
"""

from __future__ import annotations

from toolkit.features.generator_k8s import K8sGenerator

WEB_ENV = {
    "APPS_PLATFORM_WEB_EXTRA_ROUTES": [{"path_prefix": "/api", "service": "api"}],
    "APPS_PLATFORM_API_DEFAULT_PORT": "8080",
}


class TestBuildExtraRoutes:
    def test_resolves_target_port_from_the_target_app(self) -> None:
        """The port is never restated in the route entry — it is looked up."""
        routes = K8sGenerator()._build_extra_routes(WEB_ENV, "web")

        assert routes == [
            {"path_prefix": "/api", "service": "api", "port": 8080, "priority": 100}
        ]

    def test_app_without_extra_routes_gets_an_empty_list(self) -> None:
        """Every other app must keep rendering exactly one host rule."""
        assert K8sGenerator()._build_extra_routes({}, "api") == []

    def test_route_to_an_unresolvable_service_is_dropped(self) -> None:
        """A typo must not render an IngressRoute pointing at port None.

        That failure would surface at apply time, far from its cause.
        """
        env = {"APPS_PLATFORM_WEB_EXTRA_ROUTES": [{"path_prefix": "/api", "service": "typo"}]}

        assert K8sGenerator()._build_extra_routes(env, "web") == []

    def test_default_priority_outranks_a_host_catch_all_rule_length(self) -> None:
        """Traefik gives a router with no explicit priority the LENGTH of its rule.

        The web host catch-all `Host(`staging.mlorente.dev`)` is ~31 characters,
        so it sits at ~31. A route priority below that is generated, applied and
        never matched — which is exactly what shipped first.
        """
        routes = K8sGenerator()._build_extra_routes(WEB_ENV, "web")

        assert routes[0]["priority"] > len("Host(`staging.mlorente.dev`)")

    def test_explicit_priority_overrides_the_default(self) -> None:
        env = {
            "APPS_PLATFORM_WEB_EXTRA_ROUTES": [
                {"path_prefix": "/api", "service": "api", "priority": 50}
            ],
            "APPS_PLATFORM_API_DEFAULT_PORT": "8080",
        }

        assert K8sGenerator()._build_extra_routes(env, "web")[0]["priority"] == 50


class TestExtraRoutesStayOutOfTheConfigMap:
    def test_extra_routes_is_not_emitted_as_pod_env(self) -> None:
        """`_flatten_dict` keeps lists intact, so this value reaches the extractor
        as a Python list. Emitted, it would become a repr in the ConfigMap,
        change the configMapGenerator hash, and roll the pod on every deploy.
        """
        env_vars = K8sGenerator()._extract_app_env_vars(WEB_ENV, "web")

        assert "EXTRA_ROUTES" not in env_vars

    def test_unrelated_app_config_still_reaches_the_configmap(self) -> None:
        """Regression guard: the exclusion must not widen into real config."""
        env = dict(WEB_ENV, APPS_PLATFORM_WEB_SITE_TITLE="Manu Lorente")

        assert K8sGenerator()._extract_app_env_vars(env, "web")["SITE_TITLE"] == "Manu Lorente"
