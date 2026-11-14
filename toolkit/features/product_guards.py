"""Guards that keep a product contract inside what the platform granted (IDP-042 AC6).

``product_contract`` answers "is this a well-formed contract". This module
answers "may this product claim what it claims", against state the product
cannot write (proposal design point 2):

- ``image`` must equal the repository the platform derives for the product, or
  the registry's override for it (Q7), so a contract cannot point at another
  product's image. The deriver is passed in, so the caller decides which
  registry entries are contract-managed; an in-tree product has no contract.
- every ``secrets`` name must already be in ``SECRET_CATALOG`` (Q6).
- a hostname is required for each env the registry entry declares a lane for
  (``events``), and may be absent for one it does not: a product with no
  ``events.prod`` has no prod lane and need not name a prod hostname (IDP-053 D5).
- no hostname may belong to another declared route. A hostname is checked
  against the domains declared in BOTH environments, minus the product's own
  ``apps.platform.<app>.`` subtree: a staging host equal to another product's
  prod host is a collision too, and checking the union is the simpler rule.
  Hosts in the committed manifests under ``infra/k8s/`` count too: some routes
  (Argo CD, the Traefik dashboard, redirects) are hand-authored IngressRoutes
  with no values declaration. A manifest host equal to one the product itself
  declares is its own generated route.

``auth: oidc`` passes here and is refused by ``refuse_oidc_at_render``, which
the renderer calls (design point 5): the schema accepts it, rendering cannot
honour it yet.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from pathlib import Path

from toolkit.config.settings import PROJECT_ROOT
from toolkit.features.declared_domains import VALUES_DIR, declared_domains
from toolkit.features.edge_dns import (
    WILDCARD_ZONE,
    EdgeDnsError,
    declared_staging_zones,
    granted_apexes,
    staging_zone_for,
)
from toolkit.features.product_contract import Contract, ContractError, validate_contract
from toolkit.features.product_registry import Product, RegistryError, derived_image, load_registry

ENVIRONMENTS = ("staging", "prod")

#: Where a product's apex is granted (EDGE-001), named in refusals.
DNS_ZONES_RELPATH = "infra/terraform/dns/zones.json"

#: Values subtree a product owns; declarations under it are the product's own.
OWN_SUBTREE = "apps.platform.{app}."

K8S_DIR = PROJECT_ROOT / "infra" / "k8s"
_ROUTE_HOST = re.compile(r"Host(?:SNI)?\(`([^`]+)`\)")


def declared_envs(product: Product) -> tuple[str, ...]:
    """The envs ``product`` runs in: the registry's declaration of its lanes.

    A remote product runs where it has an event (``events.staging``, ``events.prod``);
    one with none is deployed nowhere. An in-tree product has no events at all and
    hand-authored values in both envs, so it counts for both.
    """
    if not product.contract_managed:
        return ENVIRONMENTS
    return tuple(env for env in ENVIRONMENTS if getattr(product.events, env) is not None)


def apps_declaring(env: str, registry: Path | None = None) -> tuple[str, ...]:
    """The registered products that run in ``env``, in registry order."""
    return tuple(name for name, product in load_registry(registry).products.items() if env in declared_envs(product))


def staging_zones(values_dir: Path = VALUES_DIR) -> list[str]:
    """The platform's declared staging zones, ``networking.staging_zones`` in ``common.yaml``.

    Not the effective list: since EDGE-001 a product's zone is derived into
    ``infra/config/products/edge.json`` (``edge_dns.staging_zones``), and this list
    holds only the platform's own zones.
    """
    return declared_staging_zones(values_dir / "common.yaml")


def check_staging_hostname(contract: Contract, zones: Iterable[str], apexes: Iterable[str] | None = None) -> None:
    """Refuse a ``hostnames.staging`` that breaks the hostname convention (IDP-053 D8, EDGE-001).

    Accepted: one label under the wildcard zone, a zone the platform declares in ``zones``
    (``networking.staging_zones``), or ``staging.<domain>`` whose apex is a Cloudflare zone
    granted in ``infra/terraform/dns/zones.json`` (``apexes``; read from there when omitted).
    The last becomes the product's own split-DNS zone, derived into ``edge.json``. A contract
    that also declares prod must name ``staging.`` + its prod hostname. The contract model
    cannot read either file, so this runs at render time.
    """
    host = contract.hostnames.staging
    declared = list(zones)
    _, _, parent = host.partition(".")
    if parent != WILDCARD_ZONE and host not in set(declared) - {WILDCARD_ZONE}:
        own_zone = (
            host.startswith("staging.")
            and "." in host.removeprefix("staging.")
            and not any(host == zone or host.endswith(f".{zone}") for zone in declared)
        )
        if not own_zone:
            raise _staging_refusal(
                host,
                f"is not staging.<product domain> or one label under {WILDCARD_ZONE}",
                f"name it staging.<product domain> (its apex declared in {DNS_ZONES_RELPATH}), "
                f"or <label>.{WILDCARD_ZONE}",
            )
        try:
            staging_zone_for(host, declared, granted_apexes() if apexes is None else apexes)
        except EdgeDnsError as exc:
            raise _staging_refusal(
                host,
                "is in no Cloudflare zone the platform declares",
                f"declare its apex in {DNS_ZONES_RELPATH} (an operator change, reviewed), "
                f"or use <label>.{WILDCARD_ZONE}",
            ) from exc
    prod = contract.hostnames.prod
    if prod is not None and host != f"staging.{prod}":
        raise _staging_refusal(
            host, f"is not 'staging.' + the declared prod hostname '{prod}'", f"set hostnames.staging: staging.{prod}"
        )


def _staging_refusal(host: str, reason: str, fix: str) -> ContractError:
    return ContractError(
        f"field 'hostnames.staging': '{host}' {reason}",
        "D8 (IDP-053): a hosted product's staging hostname is staging.<its domain>, inside a Cloudflare zone the "
        "platform grants, so split DNS and the pod-side hairpin derive its zone (EDGE-001); with no domain yet it "
        "takes one label under the wildcard zone.",
        fix,
    )


def _catalog_keys() -> frozenset[str]:
    # Imported here: secrets_manager pulls in SOPS and configuration helpers that
    # schema-only callers of this module never need.
    from toolkit.features.secrets_manager import SECRET_CATALOG

    return frozenset(spec.key_path for spec in SECRET_CATALOG)


def _check_image(contract: Contract, app: str, image_for: Callable[[str], str]) -> None:
    expected = image_for(app)
    if contract.image != expected:
        raise ContractError(
            f"field 'image': '{contract.image}' is not the image kubelab derives for '{app}'",
            "the image repository comes from kubelab's product registry, so a contract cannot "
            "point the deploy at another product's image.",
            f"set image: {expected}; if that name is wrong, ask the kubelab operator for a registry override.",
        )


def _check_secrets(contract: Contract, catalog: frozenset[str]) -> None:
    unknown = [name for name in contract.secrets if name not in catalog]
    if unknown:
        raise ContractError(
            f"field 'secrets': {', '.join(unknown)} is not a catalogued secret",
            "a contract may only name secrets already registered in SECRET_CATALOG; the catalog "
            "is operator-owned, so a product cannot add to it.",
            "ask the kubelab operator to register the secret, or remove it from the contract.",
        )


def _manifest_hosts(k8s_dir: Path) -> dict[str, str]:
    """``{host: manifest path}`` for every route match in the committed manifests."""
    hosts: dict[str, str] = {}
    for path in sorted(k8s_dir.rglob("*.yaml")):
        for host in _ROUTE_HOST.findall(path.read_text(encoding="utf-8")):
            hosts.setdefault(host, str(path.relative_to(k8s_dir.parent.parent)))
    return hosts


def _check_hostnames(
    contract: Contract, app: str, values_dir: Path, k8s_dir: Path, envs: Iterable[str] = ENVIRONMENTS
) -> None:
    """Refuse a hostname another route owns, and a lane in ``envs`` with no hostname.

    ``envs`` are the lanes the registry entry declares. Another route's hosts are
    collected from every env, because a name is taken wherever it is declared; a
    hostname the contract does declare is checked even for an env outside ``envs``.
    """
    own = OWN_SUBTREE.format(app=app)
    owners: dict[str, str] = {}
    own_hosts: set[str] = set()
    for env in ENVIRONMENTS:
        for key, domain in declared_domains(env, values_dir).items():
            if key.startswith(own):
                own_hosts.add(domain)
            else:
                owners.setdefault(domain, key)
    for host, manifest in _manifest_hosts(k8s_dir).items():
        if host not in own_hosts:
            owners.setdefault(host, manifest)
    for env in ENVIRONMENTS:
        host = getattr(contract.hostnames, env)
        if host is None:
            if env in envs:
                raise ContractError(
                    f"field 'hostnames.{env}': the contract declares no {env} hostname",
                    f"the registry entry declares a {env} lane (events.{env}), and a lane with no hostname "
                    "would deploy a route that serves nothing.",
                    f"declare hostnames.{env} in the contract; if the product has no {env} lane yet, ask the "
                    f"kubelab operator to remove events.{env} from its registry entry.",
                )
            continue
        if host in owners:
            raise ContractError(
                f"field 'hostnames.{env}': '{host}' already belongs to another route",
                f"'{owners[host]}' declares it, and two routes on one host would take each other's traffic.",
                "choose a hostname no other kubelab service declares.",
            )


def check_against_platform(
    contract: Contract,
    app: str,
    *,
    image_for: Callable[[str], str],
    catalog: Iterable[str] | None = None,
    values_dir: Path = VALUES_DIR,
    k8s_dir: Path = K8S_DIR,
    envs: Iterable[str] = ENVIRONMENTS,
) -> None:
    """Raise ``ContractError`` on the first claim of ``contract`` the platform did not grant ``app``.

    ``envs`` are the lanes the product's registry entry declares (``declared_envs``);
    the default, both, is the strict reading for a caller that has no entry to ask.
    """
    _check_image(contract, app, image_for)
    _check_secrets(contract, _catalog_keys() if catalog is None else frozenset(catalog))
    _check_hostnames(contract, app, values_dir, k8s_dir, envs)


def validate_against_platform(
    path: Path,
    app: str,
    *,
    image_for: Callable[[str], str],
    catalog: Iterable[str] | None = None,
    values_dir: Path = VALUES_DIR,
    envs: Iterable[str] = ENVIRONMENTS,
) -> Contract:
    """Validate the contract at ``path`` (schema first), then every guard for ``app``."""
    contract = validate_contract(path)
    try:
        check_against_platform(contract, app, image_for=image_for, catalog=catalog, values_dir=values_dir, envs=envs)
    except ContractError as e:
        raise ContractError(f"{path}: {e.error}", e.why, e.fix) from None
    return contract


def refuse_oidc_at_render(contract: Contract, app: str) -> None:
    """Refuse ``auth: oidc`` until an OIDC client can be rendered from a contract."""
    if contract.auth == "oidc":
        raise ContractError(
            f"field 'auth': '{app}' declares oidc, which kubelab cannot render from a contract yet",
            "an OIDC product needs a client registered in Authelia, and deploying it without one "
            "would leave a login that can never succeed.",
            "use auth: forwardauth for now, or ask the kubelab operator to register the client by hand "
            "(rendering it from the contract is a follow-up to IDP-042).",
        )


def validate_registered(path: Path, app: str, registry: Path | None = None) -> Contract:
    """Validate the contract at ``path`` for ``app`` against the product registry and the platform.

    ``app`` must be a contract-managed registry entry: an in-tree product
    (``api``) has no contract, and an unregistered name is not a product.
    """
    try:
        product = load_registry(registry).products.get(app)
    except RegistryError as e:
        raise ContractError(
            str(e), "the registry is the trust anchor every guard reads.", "fix the registry file first."
        ) from None
    if product is None:
        raise ContractError(
            f"'{app}' is not a registered product",
            "kubelab only deploys products the operator admitted in infra/config/products.yaml.",
            "ask the kubelab operator to add the product's registry entry.",
        )
    if not product.contract_managed:
        raise ContractError(
            f"'{app}' is in-tree, so it has no product contract",
            "an in-tree product's configuration is hand-authored in the values files, not rendered.",
            "validate a contract only for a product whose registry entry names a forge repository.",
        )
    return validate_against_platform(
        path, app, image_for=lambda name: derived_image(name, registry), envs=declared_envs(product)
    )
