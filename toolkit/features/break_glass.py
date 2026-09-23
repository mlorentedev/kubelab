"""Break-glass: how each service that depends on Authelia is reached while Authelia is down.

AUTH-004 AC7, ADR-062 D4. The emergency path must share no dependency with the
normal one, so it never goes through the public router or the IdP. It goes over
the private network instead: a port-forward to the Service, or its EndpointSlice
address over the tailnet. Where a service has no usable account, the path is the
cluster credential itself (a certificate kubeconfig, independent of any IdP).

Three things are derived rather than declared, so nothing here can go stale:

- **Which services depend on Authelia.** An OIDC client redirecting to the
  service's host (SSOT-017), or the `authelia` ForwardAuth middleware on its
  IngressRoute. Both are read from the rendered manifests.
- **Where the service is.** The IngressRoute's backend, and at run time the live
  Service: a selector means pods and a port-forward, none means an external
  backend reached at its EndpointSlice address.
- **Which SOPS file holds the password.** Found from key names, which SOPS
  leaves in plaintext, so it needs no decryption.

The declaration at `apps.services.security.authelia.break_glass` only says which
account opens the door, in one of four forms:

    grafana: {identity: superadmin, secret: <SECRET_CATALOG key>}  # local account
    loki: {}                                                       # reachable, no account
    argocd: {cluster: hub}                                         # the kubeconfig is the path
    vikunja: {none: "<reason>"}                                    # no break-glass, on purpose
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DECLARATION_PATH = "apps.services.security.authelia.break_glass"
FORWARD_AUTH_MIDDLEWARE = "authelia"
#: Kubeconfigs a `cluster:` path may name (`~/.kube/kubelab-<target>-config`).
CLUSTER_TARGETS = ("staging", "prod", "hub")
_FORMS = ("identity", "secret", "cluster", "none")
_HOST = re.compile(r"Host\(`([^`]+)`\)")


class BreakGlassError(ValueError):
    """A break-glass declaration or lookup that cannot be honoured."""


@dataclass(frozen=True)
class Backend:
    namespace: str
    name: str
    port: int | None
    kind: str  # "Service" or a Traefik-internal kind such as "TraefikService"


@dataclass(frozen=True)
class Route:
    name: str
    hosts: tuple[str, ...]
    forward_auth: bool
    backend: Backend | None


@dataclass(frozen=True)
class PortForward:
    namespace: str
    service: str
    port: int | None


@dataclass(frozen=True)
class Direct:
    url: str


@dataclass(frozen=True)
class ClusterCredential:
    target: str


@dataclass(frozen=True)
class NoBreakGlass:
    reason: str


Plan = PortForward | Direct | ClusterCredential | NoBreakGlass


def _lookup(values: Mapping[str, Any], dotted: str) -> Any:
    node: Any = values
    for part in dotted.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node


# --------------------------------------------------------------------------- derivation


def routes(docs: Iterable[Mapping[str, Any]]) -> dict[str, Route]:
    """Every IngressRoute, by name, with its hosts, ForwardAuth flag and backend.

    The backend is taken from the rule that carries ForwardAuth when one does,
    because that rule is the one the IdP gates. Otherwise it comes from the first
    rule with a backend (OIDC-only routes are gated by the application, not by a
    rule).
    """
    found: dict[str, Route] = {}
    for doc in docs:
        if doc.get("kind") != "IngressRoute":
            continue
        namespace = doc["metadata"].get("namespace", "kubelab")
        hosts: list[str] = []
        gated: Backend | None = None
        first: Backend | None = None
        for rule in doc.get("spec", {}).get("routes", []) or []:
            hosts.extend(_HOST.findall(rule.get("match", "")))
            services = rule.get("services") or []
            backend = (
                Backend(
                    namespace=services[0].get("namespace", namespace),
                    name=services[0]["name"],
                    port=services[0].get("port"),
                    kind=services[0].get("kind", "Service"),
                )
                if services
                else None
            )
            first = first or backend
            if any(m.get("name") == FORWARD_AUTH_MIDDLEWARE for m in rule.get("middlewares") or []):
                gated = gated or backend or first
        name = doc["metadata"]["name"]
        found[name] = Route(
            name=name, hosts=tuple(dict.fromkeys(hosts)), forward_auth=gated is not None, backend=gated or first
        )
    return found


def dependents(env: str, docs: Iterable[Mapping[str, Any]], values: Mapping[str, Any]) -> dict[str, Route]:
    """The routes whose access depends on Authelia in `env`, keyed by route name."""
    from toolkit.features.oidc_clients import resolve_clients

    all_routes = routes(docs)
    result = {name: route for name, route in all_routes.items() if route.forward_auth}
    by_host = {host: route for route in all_routes.values() for host in route.hosts}
    for client in resolve_clients(dict(values), env):
        for uri in client["redirect_uris"]:
            host = uri.split("://", 1)[1].split("/", 1)[0]
            route = by_host.get(host)
            if route is None:
                raise BreakGlassError(
                    f"OIDC client '{client['client_id']}' redirects to {host}, but no IngressRoute in {env} "
                    f"serves that host: its break-glass path cannot be derived"
                )
            result[route.name] = route
    return result


# --------------------------------------------------------------------------- declaration


def declarations(values: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    declared = _lookup(values, DECLARATION_PATH) or {}
    return {name: dict(decl or {}) for name, decl in declared.items()}


def validate(decls: Mapping[str, Mapping[str, Any]], values: Mapping[str, Any]) -> None:
    """Raise one error listing every invalid declaration, each naming its service."""
    from toolkit.features.secrets_manager import SECRET_CATALOG

    catalog = {spec.key_path for spec in SECRET_CATALOG}
    identities = _lookup(values, "apps.auth.identities") or {}
    problems: list[str] = []
    for name, decl in decls.items():
        unknown = sorted(set(decl) - set(_FORMS))
        if unknown:
            problems.append(f"{name}: unknown field(s) {unknown}")
            continue
        forms = [f for f in ("cluster", "none") if f in decl]
        if {"identity", "secret"} & set(decl):
            forms.append("account")
        if len(forms) > 1:
            problems.append(f"{name}: declares {forms}; exactly one of account, cluster, none, or {{}}")
            continue
        if "none" in decl and not str(decl["none"]).strip():
            problems.append(f"{name}: `none` needs a reason")
        if "cluster" in decl and decl["cluster"] not in CLUSTER_TARGETS:
            problems.append(f"{name}: cluster '{decl['cluster']}' is not one of {CLUSTER_TARGETS}")
        if forms == ["account"]:
            if "secret" not in decl:
                problems.append(f"{name}: an account needs its `secret`")
            elif decl["secret"] not in catalog:
                problems.append(f"{name}: secret '{decl['secret']}' is not in SECRET_CATALOG")
            if "identity" not in decl:
                problems.append(f"{name}: an account needs its `identity`")
            elif decl["identity"] not in identities:
                problems.append(f"{name}: identity '{decl['identity']}' is not in apps.auth.identities")
    if problems:
        raise BreakGlassError("invalid break-glass declaration: " + "; ".join(problems))


def coverage_gaps(deps: Mapping[str, Route], decls: Mapping[str, Any]) -> list[str]:
    return sorted(set(deps) - set(decls))


def unreachable_backends(deps: Mapping[str, Route], decls: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Dependents that claim a reachable path (`{}` or an account) on a backend no tunnel can reach."""
    return sorted(
        name
        for name, route in deps.items()
        if name in decls
        and not ({"cluster", "none"} & set(decls[name]))
        and (route.backend is None or route.backend.kind != "Service")
    )


# --------------------------------------------------------------------------- resolution


def plan_access(
    decl: Mapping[str, Any],
    route: Route,
    service: Mapping[str, Any] | None,
    endpoint_slices: Iterable[Mapping[str, Any]],
) -> Plan:
    """Turn a declaration plus the live Service into the concrete way in."""
    if "none" in decl:
        return NoBreakGlass(reason=str(decl["none"]))
    if "cluster" in decl:
        return ClusterCredential(target=str(decl["cluster"]))
    backend = route.backend
    if backend is None or backend.kind != "Service":
        raise BreakGlassError(f"{route.name}: its backend is not a Service, so no private path reaches it")
    if service is None:
        raise BreakGlassError(f"{route.name}: Service {backend.namespace}/{backend.name} not found in the cluster")
    if (service.get("spec") or {}).get("selector"):
        return PortForward(namespace=backend.namespace, service=backend.name, port=backend.port)
    for eps in endpoint_slices:
        ports = [p.get("port") for p in eps.get("ports") or []]
        port = backend.port if backend.port in ports else (ports[0] if ports else backend.port)
        for endpoint in eps.get("endpoints") or []:
            if (endpoint.get("conditions") or {}).get("ready", True) and endpoint.get("addresses"):
                return Direct(url=f"http://{endpoint['addresses'][0]}:{port}")
    raise BreakGlassError(
        f"{route.name}: Service {backend.namespace}/{backend.name} has no selector and no ready endpoint"
    )


def secret_file(key: str, env: str, secrets_dir: Path) -> str:
    """Which SOPS file holds `key`: the env file if it carries it, else common. Reads key names only."""
    for candidate in (env, "common"):
        path = secrets_dir / f"{candidate}.enc.yaml"
        if path.exists() and _lookup(yaml.safe_load(path.read_text(encoding="utf-8")) or {}, key) is not None:
            return candidate
    raise BreakGlassError(f"{key} is in neither {env}.enc.yaml nor common.enc.yaml")


# --------------------------------------------------------------------------- audit


def announce_use(
    env: str,
    service: str,
    *,
    who: str,
    merged_config: Mapping[str, Any],
    webhook_secret: str | None,
    post: Any = None,
) -> bool:
    """Page the operator's channel that a break-glass path was opened. Never raises.

    Every use is announced because an emergency credential used silently is
    indistinguishable from a stolen one. It goes through the notify webhook,
    whose route carries no ForwardAuth, so it still works with the IdP down. A
    failure to announce is reported to the caller, but it never blocks the way
    in: in an emergency, access wins over bookkeeping.
    """
    from toolkit.features.notify_smoke import _default_post, build_envelope, resolve_service_domain, webhook_url

    if not webhook_secret:
        return False
    try:
        url = webhook_url(resolve_service_domain(dict(merged_config), "n8n"))
        envelope = build_envelope(
            "page",
            title=f"break-glass opened: {service} ({env})",
            body=f"{who} opened the break-glass path to {service} in {env}. Rotate its credential after use.",
            domain="security",
            source="break-glass",
        )
        send = post or _default_post(verify_tls=env == "prod")
        return 200 <= send(url, envelope, {"Authorization": f"Bearer {webhook_secret}"}) < 300
    except Exception:  # noqa: BLE001 -- an unannounced use is reported, never fatal
        return False
