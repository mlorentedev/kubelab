"""AUTH-004 AC7: every service that depends on Authelia declares its break-glass path.

"Depends on Authelia" is derived, never listed: a service is a dependent when an
OIDC client redirects to its host (SSOT-017) or when its IngressRoute carries the
`authelia` ForwardAuth middleware. So adding SSO or ForwardAuth to a service
without saying how to reach it when the IdP is down fails here, in CI.

WHERE a service is reached is derived too, from the route's backend and, at run
time, from the live Service: a selector means a port-forward, no selector means
the EndpointSlice address over the tailnet. The declaration only says which
account opens it, so nothing here carries a host, an address or a port.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.features import break_glass as bg
from toolkit.features import oidc_clients

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _render(env: str) -> list[dict[str, Any]]:
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not on PATH: break-glass coverage was NOT checked")
    out = subprocess.run(
        ["kubectl", "kustomize", str(PROJECT_ROOT / "infra/k8s/overlays" / env)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def _route(name: str, host: str, *, forward_auth: bool = False, backend: dict[str, Any] | None = None) -> dict:
    middlewares = [{"name": "secure-headers"}] + ([{"name": "authelia"}] if forward_auth else [])
    return {
        "kind": "IngressRoute",
        "metadata": {"name": name, "namespace": "kubelab"},
        "spec": {
            "routes": [
                {
                    "match": f"Host(`{host}`)",
                    "middlewares": middlewares,
                    "services": [backend or {"name": name, "port": 3000}],
                }
            ]
        },
    }


def _values(**break_glass: Any) -> dict[str, Any]:
    return {
        "apps": {
            "auth": {"identities": {"superadmin": "manu", "operator": "operator"}},
            "services": {"security": {"authelia": {"break_glass": break_glass, "oidc_clients": []}}},
        }
    }


# --------------------------------------------------------------------------- coverage


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_every_authelia_dependent_declares_break_glass(env: str) -> None:
    values = oidc_clients.load_values(env)
    dependents = bg.dependents(env, _render(env), values)
    assert dependents, f"{env}: no service depends on Authelia -- the derivation found nothing"

    gaps = bg.coverage_gaps(dependents, bg.declarations(values))
    assert not gaps, (
        f"{env}: these services depend on Authelia but declare no break-glass path in "
        f"{bg.DECLARATION_PATH}: {gaps}. Declare an account, `cluster:`, `{{}}` or `none:` with a reason."
    )


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_the_committed_declaration_is_valid(env: str) -> None:
    values = oidc_clients.load_values(env)
    bg.validate(bg.declarations(values), values)
    assert not bg.unreachable_backends(bg.dependents(env, _render(env), values), bg.declarations(values))


# --------------------------------------------------------------------------- derivation


class TestDependents:
    def test_a_forward_auth_route_is_a_dependent(self) -> None:
        docs = [_route("loki", "loki.example.test", forward_auth=True)]
        assert set(bg.dependents("prod", docs, _values())) == {"loki"}

    def test_an_oidc_client_makes_its_routed_host_a_dependent(self) -> None:
        values = _values()
        values["apps"]["services"]["observability"] = {"grafana": {"domain": "grafana.example.test"}}
        values["apps"]["services"]["security"]["authelia"]["oidc_clients"] = [
            {
                "client_id": "grafana",
                "client_name": "Grafana",
                "envs": ["prod"],
                "redirect": {"domain": "apps.services.observability.grafana.domain", "path": "/cb"},
                "scopes": ["openid"],
                "token_endpoint_auth_method": "client_secret_basic",
                "authorization_policy": "one_factor",
                "consent_mode": "implicit",
            }
        ]
        docs = [_route("grafana", "grafana.example.test"), _route("other", "other.example.test")]
        assert set(bg.dependents("prod", docs, values)) == {"grafana"}

    def test_an_oidc_client_with_no_route_in_the_env_fails_loudly(self) -> None:
        values = _values()
        values["apps"]["services"]["observability"] = {"grafana": {"domain": "grafana.example.test"}}
        values["apps"]["services"]["security"]["authelia"]["oidc_clients"] = [
            {
                "client_id": "grafana",
                "client_name": "Grafana",
                "envs": ["prod"],
                "redirect": {"domain": "apps.services.observability.grafana.domain", "path": "/cb"},
                "scopes": ["openid"],
                "token_endpoint_auth_method": "client_secret_basic",
                "authorization_policy": "one_factor",
                "consent_mode": "implicit",
            }
        ]
        with pytest.raises(bg.BreakGlassError, match="grafana"):
            bg.dependents("prod", [], values)

    def test_a_route_with_neither_is_not_a_dependent(self) -> None:
        assert bg.dependents("prod", [_route("web", "web.example.test")], _values()) == {}


# --------------------------------------------------------------------------- declaration


class TestValidate:
    def _ok(self, **decl: Any) -> None:
        values = _values(**decl)
        bg.validate(bg.declarations(values), values)

    def test_the_four_forms_are_accepted(self) -> None:
        self._ok(
            grafana={"identity": "superadmin", "secret": "apps.services.observability.grafana.admin_password"},
            argocd={"cluster": "hub"},
            loki={},
            vikunja={"none": "not a 3 AM service (ADR-028)"},
        )

    @pytest.mark.parametrize(
        ("decl", "fragment"),
        [
            ({"identity": "superadmin"}, "secret"),
            ({"secret": "apps.services.observability.grafana.admin_password"}, "identity"),
            ({"identity": "nobody", "secret": "apps.services.observability.grafana.admin_password"}, "nobody"),
            ({"identity": "superadmin", "secret": "not.in.the.catalog"}, "catalog"),
            ({"none": ""}, "reason"),
            ({"cluster": "moon"}, "moon"),
            ({"none": "x", "cluster": "hub"}, "exactly one"),
            ({"typo": 1}, "typo"),
        ],
    )
    def test_invalid_declarations_fail_naming_the_service(self, decl: dict[str, Any], fragment: str) -> None:
        with pytest.raises(bg.BreakGlassError, match=rf"grafana.*{fragment}|{fragment}.*grafana"):
            self._ok(grafana=decl)

    def test_a_non_service_backend_cannot_claim_a_reachable_path(self) -> None:
        docs = [_route("traefik-dashboard", "t.example.test", forward_auth=True, backend={"name": "api@internal", "kind": "TraefikService"})]
        deps = bg.dependents("prod", docs, _values())
        assert bg.unreachable_backends(deps, {"traefik-dashboard": {}}) == ["traefik-dashboard"]
        assert bg.unreachable_backends(deps, {"traefik-dashboard": {"none": "diagnostic view"}}) == []


# --------------------------------------------------------------------------- resolution


class TestPlanAccess:
    route = bg.Route(name="grafana", hosts=("grafana.example.test",), forward_auth=True, backend=bg.Backend("kubelab", "grafana", 3000, "Service"))

    def test_a_service_with_pods_is_port_forwarded(self) -> None:
        plan = bg.plan_access({}, self.route, {"spec": {"selector": {"app": "grafana"}}}, [])
        assert plan == bg.PortForward(namespace="kubelab", service="grafana", port=3000)

    def test_a_service_without_pods_is_reached_at_its_endpoint(self) -> None:
        slices = [{"ports": [{"port": 3000}], "endpoints": [{"addresses": ["100.64.0.3"], "conditions": {"ready": True}}]}]
        plan = bg.plan_access({}, self.route, {"spec": {}}, slices)
        assert plan == bg.Direct(url="http://100.64.0.3:3000")

    def test_a_service_without_pods_and_without_endpoints_is_an_error(self) -> None:
        with pytest.raises(bg.BreakGlassError, match="grafana"):
            bg.plan_access({}, self.route, {"spec": {}}, [])

    def test_cluster_and_none_need_no_lookup(self) -> None:
        assert bg.plan_access({"cluster": "hub"}, self.route, None, []) == bg.ClusterCredential(target="hub")
        assert bg.plan_access({"none": "why"}, self.route, None, []) == bg.NoBreakGlass(reason="why")


class TestSecretFile:
    """Where the password lives, read from SOPS key names -- which are plaintext, so no decryption."""

    def test_an_env_file_key_wins_over_common(self, tmp_path: Path) -> None:
        (tmp_path / "prod.enc.yaml").write_text("a:\n  b: ENC[x]\n")
        (tmp_path / "common.enc.yaml").write_text("a:\n  b: ENC[y]\n")
        assert bg.secret_file("a.b", "prod", tmp_path) == "prod"

    def test_a_key_only_in_common_resolves_to_common(self, tmp_path: Path) -> None:
        (tmp_path / "prod.enc.yaml").write_text("x: ENC[x]\n")
        (tmp_path / "common.enc.yaml").write_text("a:\n  b: ENC[y]\n")
        assert bg.secret_file("a.b", "prod", tmp_path) == "common"

    def test_a_key_in_neither_is_an_error(self, tmp_path: Path) -> None:
        (tmp_path / "prod.enc.yaml").write_text("x: 1\n")
        (tmp_path / "common.enc.yaml").write_text("y: 1\n")
        with pytest.raises(bg.BreakGlassError, match="a.b"):
            bg.secret_file("a.b", "prod", tmp_path)
