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

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from toolkit.features import product_ready, product_registry
from toolkit.features.forge_adapter import ForgeAdapter, ForgeError
from toolkit.features.product_contract import ContractError
from toolkit.features.product_guards import validate_registered
from toolkit.features.registry import SHA_TAG_HEX_LENGTHS, SHA_TAG_PREFIX, reads_digests, tag_digest

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


def _prove_image(app: str, version: str, sha: str, registry: Path | None) -> str:
    """The digest of ``<image>:<version>``, once it is shown to be the build of ``sha``."""
    image = product_registry.derived_image(app, registry)
    host, image_name = image.rsplit("/", 1)
    if not reads_digests(host):
        raise ContractError(
            f"the release proof cannot read digests from {host}",
            "the proof reads tags through Docker Hub's anonymous API, the only registry the toolkit reads, "
            "so a tag there may exist and still be unprovable.",
            f"publish {image_name} to Docker Hub, or teach toolkit/features/registry.py to read {host}.",
        )
    released = tag_digest(host, image_name, version)
    if released is None:
        raise ContractError(
            f"the digest of {image}:{version} cannot be read",
            "the proof reads Docker Hub anonymously, and Docker Hub answers a private repository the same way "
            "as an absent tag, so the tag is missing or the repository is private.",
            f"check that {image}:{version} exists in a public repository, then run the promotion again.",
        )
    # The product's CI picks the hex length; the receiver admits 7 to 40, so any prefix in that range is the build.
    built, at_commit = f"{SHA_TAG_PREFIX}{sha[:7]}", None
    for length in SHA_TAG_HEX_LENGTHS:
        built = f"{SHA_TAG_PREFIX}{sha[:length]}"
        at_commit = tag_digest(host, image_name, built)
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


def fetch_release_contract(app: str, version: str, dest: Path, registry: Path | None = None) -> Release:
    """Write the contract of ``app``'s release ``version`` to ``dest``, or raise ``ContractError`` and write nothing."""
    forge = product_ready.forge_for(app, registry)
    sha = _release_commit(forge, version)
    digest = _prove_image(app, version, sha, registry)
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
