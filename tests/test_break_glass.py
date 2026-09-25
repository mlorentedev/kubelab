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
    # `operator` has no email of its own, so it gets `apps.contact.email`: a collision
    # with it is only caught if validation resolves emails the way the generators do.
    users = [
        {"identity": "superadmin", "email": "manu@example.test", "groups": ["admins"]},
        {"identity": "operator", "groups": ["admins"]},
        {"username": "testuser", "email": "test@example.test", "groups": ["e2e"]},
    ]
    return {
        "apps": {
            "contact": {"email": "info@example.test"},
            "auth": {"identities": {"superadmin": "manu", "operator": "operator"}},
            "services": {"security": {"authelia": {"break_glass": break_glass, "oidc_clients": [], "users": users}}},
        }
    }


_GRAFANA_SECRET = "apps.services.observability.grafana.admin_password"


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
            grafana={"login": "breakglass", "email": "breakglass@example.test", "secret": _GRAFANA_SECRET},
            gitea={"identity": "superadmin", "secret": "apps.services.core.gitea.admin_password"},
            argocd={"cluster": "hub"},
            loki={},
            vikunja={"none": "not a 3 AM service (ADR-028)"},
        )

    def test_a_reachable_form_may_name_the_page_to_open(self) -> None:
        self._ok(
            grafana={
                "identity": "superadmin",
                "secret": "apps.services.observability.grafana.admin_password",
                "path": "/login?disableAutoLogin=true",
            },
            loki={"path": "/ready"},
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
            # A local account (#951): nobody's in Authelia, and provably so.
            ({"identity": "superadmin", "login": "bg", "email": "bg@x.test", "secret": _GRAFANA_SECRET}, "exactly one"),
            ({"identity": "superadmin", "email": "bg@x.test", "secret": _GRAFANA_SECRET}, "local `login`"),
            ({"login": "bg", "secret": _GRAFANA_SECRET}, "own `email`"),
            ({"login": "operator", "email": "bg@x.test", "secret": _GRAFANA_SECRET}, "'operator' is an Authelia"),
            ({"login": "testuser", "email": "bg@x.test", "secret": _GRAFANA_SECRET}, "'testuser' is an Authelia"),
            ({"login": "Operator", "email": "bg@x.test", "secret": _GRAFANA_SECRET}, "'Operator' is an Authelia"),
            ({"login": "bg", "email": "Manu@Example.test", "secret": _GRAFANA_SECRET}, "adopt"),
            ({"login": "bg", "email": "info@example.test", "secret": _GRAFANA_SECRET}, "adopt"),
            ({"cluster": "hub", "path": "/login"}, "reachable"),
            ({"none": "x", "path": "/login"}, "reachable"),
            ({"identity": "superadmin", "secret": "apps.services.observability.grafana.admin_password", "path": "login"}, "'/'"),
        ],
    )
    def test_invalid_declarations_fail_naming_the_service(self, decl: dict[str, Any], fragment: str) -> None:
        with pytest.raises(bg.BreakGlassError, match=rf"grafana.*{fragment}|{fragment}.*grafana"):
            self._ok(grafana=decl)

    def test_an_account_signs_in_as_its_own_login_or_its_identity(self) -> None:
        values = _values()
        assert bg.account_login({"identity": "superadmin", "secret": _GRAFANA_SECRET}, values) == "manu"
        assert (
            bg.account_login({"login": "breakglass", "email": "b@x", "secret": _GRAFANA_SECRET}, values) == "breakglass"
        )

    def test_a_non_service_backend_cannot_claim_a_reachable_path(self) -> None:
        docs = [
            _route(
                "traefik-dashboard",
                "t.example.test",
                forward_auth=True,
                backend={"name": "api@internal", "kind": "TraefikService"},
            )
        ]
        deps = bg.dependents("prod", docs, _values())
        assert bg.unreachable_backends(deps, {"traefik-dashboard": {}}) == ["traefik-dashboard"]
        assert bg.unreachable_backends(deps, {"traefik-dashboard": {"none": "diagnostic view"}}) == []


# --------------------------------------------------------------------------- resolution


class TestPlanAccess:
    route = bg.Route(
        name="grafana",
        hosts=("grafana.example.test",),
        forward_auth=True,
        backend=bg.Backend("kubelab", "grafana", 3000, "Service"),
    )

    def test_a_service_with_pods_is_port_forwarded(self) -> None:
        plan = bg.plan_access({}, self.route, {"spec": {"selector": {"app": "grafana"}}}, [])
        assert plan == bg.PortForward(namespace="kubelab", service="grafana", port=3000)

    def test_a_service_without_pods_is_reached_at_its_endpoint(self) -> None:
        slices = [
            {"ports": [{"port": 3000}], "endpoints": [{"addresses": ["100.64.0.3"], "conditions": {"ready": True}}]}
        ]
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


class TestAnnounceUse:
    config = {"apps": {"services": {"automation": {"n8n": {"domain": "n8n.example.test"}}}}}

    def test_every_use_pages_with_the_service_env_and_actor(self) -> None:
        sent: list[tuple[str, dict[str, Any], dict[str, str]]] = []
        ok = bg.announce_use(
            "prod",
            "grafana",
            who="manu@msi",
            merged_config=self.config,
            webhook_secret="s",
            post=lambda url, env, headers: sent.append((url, env, headers)) or 200,
        )
        assert ok
        [(url, envelope, headers)] = sent
        assert url == "https://n8n.example.test/webhook/notify"
        assert envelope["severity"] == "page"
        assert "grafana" in envelope["title"] and "prod" in envelope["title"] and "manu@msi" in envelope["body"]
        assert headers == {"Authorization": "Bearer s"}

    def test_a_failed_announcement_is_reported_not_raised(self) -> None:
        def boom(*_: Any) -> int:
            raise OSError("network down")

        assert (
            bg.announce_use("prod", "grafana", who="x", merged_config=self.config, webhook_secret="s", post=boom)
            is False
        )
        assert bg.announce_use("prod", "grafana", who="x", merged_config=self.config, webhook_secret=None) is False


def test_the_backend_comes_from_the_rule_the_idp_gates() -> None:
    doc = {
        "kind": "IngressRoute",
        "metadata": {"name": "n8n", "namespace": "kubelab"},
        "spec": {
            "routes": [
                {
                    "match": "Host(`n.example.test`) && PathPrefix(`/webhook`)",
                    "services": [{"name": "hooks", "port": 1}],
                },
                {
                    "match": "Host(`n.example.test`)",
                    "middlewares": [{"name": "authelia"}],
                    "services": [{"name": "editor", "port": 2}],
                },
            ]
        },
    }
    route = bg.routes([doc])["n8n"]
    assert route.forward_auth and route.backend is not None and route.backend.name == "editor"


def test_a_broken_render_is_one_line_not_a_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    """pr-agent on #1795: a failing `kubectl kustomize` must reach the operator as a sentence."""
    import types

    from typer.testing import CliRunner

    from toolkit.cli import auth
    from toolkit.main import app

    def failing_run(*_: Any, **__: Any) -> Any:
        return types.SimpleNamespace(returncode=1, stdout="", stderr="Error: accumulating resources: boom\n")

    monkeypatch.setattr(auth.subprocess, "run", failing_run)
    result = CliRunner().invoke(app, ["auth", "break-glass", "grafana", "--env", "staging", "--dry-run"])
    assert result.exit_code == 1
    assert "could not render the staging overlay" in result.output and "boom" in result.output
    assert "Traceback" not in result.output
