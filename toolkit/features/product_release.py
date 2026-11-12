"""The contract a prod promotion renders: ``kubelab.yaml`` at the release's own commit (IDP-042).

A product's release re-tags the digest built from the release commit as
``<image>:<version>`` (build-once, ADR-055/ADR-056), so that commit's contract is
the one prod runs. It is not the commit staging pins: the staging deploy PR is
long-lived and can lag or lead the release.

The commit is found through the product's release tag (``v<version>``, the tag
release-please cuts) and then proven, not trusted: ``<image>:<version>`` and
``<image>:sha-<commit>`` must name one digest. A tag that names another commit, a
digest that cannot be read and a release without a contract are all refused
before anything is written, so the prod promotion opens no PR for them.
"""

from __future__ import annotations

import functools
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from toolkit.features import product_ready, product_registry
from toolkit.features.forge_adapter import ForgeAdapter, ForgeError
from toolkit.features.product_contract import ContractError
from toolkit.features.product_guards import validate_registered
from toolkit.features.registry import (
    SHA_TAG_HEX_LENGTHS,
    SHA_TAG_PREFIX,
    RegistryCredential,
    catalog_secret,
    is_docker_hub,
    tag_digest,
)

#: The git tag a product's release-please cuts for image ``<version>``.
RELEASE_TAG_PREFIX = "v"


@dataclass(frozen=True)
class Release:
    app: str
    repository: str
    version: str
    sha: str
    digest: str


def _release_commit(forge: ForgeAdapter, version: str) -> str:
    tag = f"{RELEASE_TAG_PREFIX}{version}"
    try:
        return forge.resolve_tag(tag)
    except ForgeError as e:
        raise ContractError(
            f"{forge.repository} has no release tag {tag}",
            f"prod renders the contract at the commit the release was cut from. {forge.name} answered: {e}",
            f"promote a version {forge.repository} has released, or push its {tag} tag.",
        ) from None


def _credential(
    app: str, host: str, entry: product_registry.Product, secret: Callable[[str], str | None] | None
) -> RegistryCredential | None:
    """The login the entry's ``pull_credential`` names, resolved from the catalog; ``None`` for a public entry."""
    declared = entry.pull_credential
    if declared is None:
        return None
    token = (secret or catalog_secret)(declared.secret)
    if not token:
        raise ContractError(
            f"the pull credential for {host} is not available: the catalog key {declared.secret} holds no value here",
            f"'{app}' is private on {host}, so the release proof reads it as {declared.username} with that token; "
            "the catalog decrypts only where the SOPS age key is, so a runner without it cannot read the image.",
            f"run the promotion where `toolkit secrets` decrypts {declared.secret}, or set it "
            f"(`toolkit secrets set {declared.secret} --env common --stdin`).",
        )
    return RegistryCredential(declared.username, token)


def _unreadable(image: str, version: str, host: str, credential: RegistryCredential | None) -> ContractError:
    if is_docker_hub(host):
        return ContractError(
            f"the digest of {image}:{version} cannot be read",
            "the proof reads Docker Hub anonymously, and Docker Hub answers a private repository the same way "
            "as an absent tag, so the tag is missing or the repository is private.",
            f"check that {image}:{version} exists in a public repository, then run the promotion again.",
        )
    reader = f"the login of {credential.username}" if credential else "an anonymous read"
    return ContractError(
        f"the digest of {image}:{version} cannot be read from {host}",
        f"{host} gave no manifest digest to {reader}: the tag is absent, the registry refused the read "
        "(a private package needs `private: true` and a `pull_credential` on the product's registry entry), "
        "or it does not speak the OCI manifest API.",
        f"confirm {host} lets {reader} pull {image} (and that {version} was pushed there), then run the promotion "
        "again. A registry that delegates its login to another host is not supported by this reader; "
        "that needs an explicit decision, not a retry.",
    )


def _prove_image(
    app: str,
    version: str,
    sha: str,
    registry: Path | None,
    *,
    http: Callable[..., httpx.Response] | None = None,
    secret: Callable[[str], str | None] | None = None,
) -> str:
    """The digest of ``<image>:<version>``, once it is shown to be the build of ``sha``."""
    image = product_registry.derived_image(app, registry)
    host, image_name = image.rsplit("/", 1)
    credential = _credential(app, host, product_registry.product(app, registry), secret)
    digest_of = functools.partial(tag_digest, credential=credential, http=http)
    released = digest_of(host, image_name, version)
    if released is None:
        raise _unreadable(image, version, host, credential)
    # The product's CI picks the hex length; the receiver admits 7 to 40, so any prefix in that range is the build.
    built, at_commit = f"{SHA_TAG_PREFIX}{sha[:7]}", None
    for length in SHA_TAG_HEX_LENGTHS:
        built = f"{SHA_TAG_PREFIX}{sha[:length]}"
        at_commit = digest_of(host, image_name, built)
        if at_commit is not None:
            break
    if at_commit is None:
        first, last = SHA_TAG_HEX_LENGTHS[0], SHA_TAG_HEX_LENGTHS[-1]
        raise ContractError(
            f"no tag of {image} from sha-{sha[:first]} to sha-{sha[:last]} can be read",
            "the release's contract is the one prod runs only if the release image is the build of its commit, "
            "and without a digest of that build nothing proves it.",
            f"check that {image} carries a sha- tag of commit {sha}, then run the promotion again.",
        )
    if released != at_commit:
        raise ContractError(
            f"{image}:{version} ({released}) and {image}:{built} ({at_commit}) are different digests",
            f"the release tag names commit {sha}, but the image released as {version} was not built from it, "
            "so that commit's contract is not the one prod would run.",
            "re-tag the release from the build of its own commit, or promote the version that was.",
        )
    return released


def fetch_release_contract(
    app: str,
    version: str,
    dest: Path,
    registry: Path | None = None,
    *,
    http: Callable[..., httpx.Response] | None = None,
    secret: Callable[[str], str | None] | None = None,
) -> Release:
    """Write the contract of ``app``'s release ``version`` to ``dest``, or raise ``ContractError`` and write nothing."""
    forge = product_ready.forge_for(app, registry)
    sha = _release_commit(forge, version)
    digest = _prove_image(app, version, sha, registry, http=http, secret=secret)
    try:
        fetched = forge.read_file(product_ready.CONTRACT_PATH, sha)
    except ForgeError:
        raise ContractError(
            f"{forge.repository} has no readable kubelab.yaml at {RELEASE_TAG_PREFIX}{version} ({sha})",
            "a product is deployed only from the contract committed with its image (ADR-067); "
            "a release older than its kubelab.yaml cannot render prod.",
            "promote a release that carries kubelab.yaml.",
        ) from None
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / product_ready.CONTRACT_PATH
        path.write_text(fetched, encoding="utf-8")
        validate_registered(path, app, registry)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
    return Release(app=app, repository=forge.repository, version=version, sha=sha, digest=digest)
