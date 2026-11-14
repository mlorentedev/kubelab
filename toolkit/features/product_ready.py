"""Is a product ready for the generic receiver? (IDP-042 AC4)

Flipping a product to ``receiver: generic`` makes every image dispatch fetch
``kubelab.yaml`` at the image's own commit and refuse an image without one, so a
product whose contract is missing stalls staging on its first push after the
flip. This asks the receiver's question once, before the flip, at the commit
staging runs now: the pin in ``values/staging.yaml``, resolved on the product's
repository as the registry names it.

The commit is resolved the way the receiver resolves it (one 40-hex commit that
starts with the short sha), and the contract is judged by the same
``validate_registered``. Unlike the rest of ``toolkit product``, this reads the
forge: it is the operator's gate, not a step the receiver runs.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from toolkit.features import product_registry, promotion
from toolkit.features.forge_adapter import ForgeAdapter, ForgeError, adapter_for
from toolkit.features.product_contract import ContractError
from toolkit.features.product_guards import validate_registered

CONTRACT_PATH = "kubelab.yaml"


@dataclass(frozen=True)
class Ready:
    app: str
    repository: str
    tag: str
    sha: str


def entry_for(app: str, registry: Path | None = None) -> product_registry.Product:
    """The registry entry for ``app``, or ``ContractError`` saying the registry does not admit it."""
    try:
        return product_registry.product(app, registry)
    except product_registry.RegistryError as e:
        raise ContractError(
            str(e),
            "the registry alone admits a product, and names the repository its contract is fetched from.",
            "admit the product in infra/config/products.yaml first.",
        ) from None


def forge_for(app: str, registry: Path | None = None) -> ForgeAdapter:
    """The adapter for ``app``'s repository, or ``ContractError`` if the registry or its forge refuses."""
    return adapter_for(app, entry_for(app, registry))


def commit_of(forge: ForgeAdapter, subject: str, short: str, fix: str) -> str:
    try:
        return forge.resolve_commit(short)
    except ForgeError as e:
        raise ContractError(
            f"{subject} does not resolve to one commit of {forge.repository}", f"{forge.name} answered: {e}", fix
        ) from None


def check_ready(app: str, env: str = "staging", registry: Path | None = None) -> Ready:
    """Return what the receiver would deploy for ``app``, or raise ``ContractError`` saying why it would not."""
    forge = forge_for(app, registry)
    try:
        tag = promotion.resolve_image_sha(env, app)
    except ValueError as e:
        raise ContractError(
            str(e), f"the gate checks the commit {env} runs now.", f"deploy a sha build to {env}."
        ) from None
    short = tag.removeprefix("sha-")

    sha = commit_of(
        forge,
        f"{env} pin {tag}",
        short,
        f"deploy an image of a commit on {forge.repository}'s default branch to {env}.",
    )
    try:
        fetched = forge.read_file(CONTRACT_PATH, sha)
    except ForgeError:
        raise ContractError(
            f"{forge.repository} has no readable kubelab.yaml at {tag} ({sha})",
            "after the flip, every image without a contract at its commit is refused, so staging would stall.",
            f"merge kubelab.yaml in {forge.repository}, then let its next image reach {env}, then check again.",
        ) from None
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / CONTRACT_PATH
        path.write_text(fetched, encoding="utf-8", newline="\n")
        validate_registered(path, app, registry)
    return Ready(app=app, repository=forge.repository, tag=tag, sha=sha)
