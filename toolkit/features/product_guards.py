"""Guards that keep a product contract inside what the platform granted (IDP-042 AC6).

``product_contract`` answers "is this a well-formed contract". This module
answers "may this product claim what it claims", against state the product
cannot write (proposal design point 2):

- ``image`` must equal the repository the platform derives for the product, or
  the registry's override for it (Q7), so a contract cannot point at another
  product's image. The deriver is passed in, so the caller decides which
  registry entries are contract-managed; an in-tree product has no contract.
- every ``secrets`` name must already be in ``SECRET_CATALOG`` (Q6).
- no hostname may belong to another declared route. A hostname is checked
  against the domains declared in BOTH environments, minus the product's own
  ``apps.platform.<app>.`` subtree: a staging host equal to another product's
  prod host is a collision too, and checking the union is the simpler rule.

``auth: oidc`` passes here and is refused by ``refuse_oidc_at_render``, which
the renderer calls (design point 5): the schema accepts it, rendering cannot
honour it yet.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from toolkit.features.declared_domains import VALUES_DIR, declared_domains
from toolkit.features.product_contract import Contract, ContractError, validate_contract
from toolkit.features.product_registry import RegistryError, derived_image, load_registry

ENVIRONMENTS = ("staging", "prod")

#: Values subtree a product owns; declarations under it are the product's own.
OWN_SUBTREE = "apps.platform.{app}."


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


def _check_hostnames(contract: Contract, app: str, values_dir: Path) -> None:
    own = OWN_SUBTREE.format(app=app)
    owners: dict[str, str] = {}
    for env in ENVIRONMENTS:
        for key, domain in declared_domains(env, values_dir).items():
            if not key.startswith(own):
                owners.setdefault(domain, key)
    for env in ENVIRONMENTS:
        host = getattr(contract.hostnames, env)
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
) -> None:
    """Raise ``ContractError`` on the first claim of ``contract`` the platform did not grant ``app``."""
    _check_image(contract, app, image_for)
    _check_secrets(contract, _catalog_keys() if catalog is None else frozenset(catalog))
    _check_hostnames(contract, app, values_dir)


def validate_against_platform(
    path: Path,
    app: str,
    *,
    image_for: Callable[[str], str],
    catalog: Iterable[str] | None = None,
    values_dir: Path = VALUES_DIR,
) -> Contract:
    """Validate the contract at ``path`` (schema first), then every guard for ``app``."""
    contract = validate_contract(path)
    try:
        check_against_platform(contract, app, image_for=image_for, catalog=catalog, values_dir=values_dir)
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
    return validate_against_platform(path, app, image_for=lambda name: derived_image(name, registry))
