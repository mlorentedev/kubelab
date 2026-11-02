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

import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from toolkit.features import product_ready, product_registry
from toolkit.features.product_contract import ContractError
from toolkit.features.product_guards import validate_registered
from toolkit.features.registry import SHA_TAG_PREFIX, tag_digest

#: The git tag a product's release-please cuts for image ``<version>``.
RELEASE_TAG_PREFIX = "v"

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class Release:
    app: str
    repository: str
    version: str
    sha: str
    digest: str


def _repository(app: str, registry: Path | None) -> str:
    try:
        entry = product_registry.product(app, registry)
    except product_registry.RegistryError as e:
        raise ContractError(
            str(e),
            "the registry alone admits a product, and names the repository its contract is fetched from.",
            "admit the product in infra/config/products.yaml first.",
        ) from None
    if entry.forge != "github" or entry.repository is None:
        raise ContractError(
            f"'{app}' has no release contract (forge: {entry.forge})",
            "only a product received from a GitHub repository renders prod from a contract; "
            "an in-tree product's prod values are hand-authored.",
            "promote it without a render; nothing reads a contract for it.",
        )
    return entry.repository


def _release_commit(repository: str, version: str) -> str:
    tag = f"{RELEASE_TAG_PREFIX}{version}"
    answer = product_ready._gh("api", f"repos/{repository}/commits/{tag}", "--jq", ".sha")
    sha = answer.stdout.strip()
    if answer.returncode != 0 or not _FULL_SHA.match(sha):
        raise ContractError(
            f"{repository} has no release tag {tag}",
            f"prod renders the contract at the commit the release was cut from. GitHub answered: "
            f"{(answer.stderr or sha).strip()}",
            f"promote a version {repository} has released, or push its {tag} tag.",
        )
    return sha


def _prove_image(app: str, version: str, sha: str, registry: Path | None) -> str:
    """The digest of ``<image>:<version>``, once it is shown to be the build of ``sha``."""
    image = product_registry.derived_image(app, registry)
    host, image_name = image.rsplit("/", 1)
    built = f"{SHA_TAG_PREFIX}{sha[:7]}"
    released, at_commit = tag_digest(host, image_name, version), tag_digest(host, image_name, built)
    if released is None or at_commit is None:
        unread = version if released is None else built
        raise ContractError(
            f"the digest of {image}:{unread} cannot be read",
            "the release's contract is the one prod runs only if the release image is the build of its commit, "
            "and without both digests nothing proves it.",
            f"check that {image}:{unread} exists, then run the promotion again.",
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
    repository = _repository(app, registry)
    sha = _release_commit(repository, version)
    digest = _prove_image(app, version, sha, registry)
    fetched = product_ready._gh(
        "api", "-H", "Accept: application/vnd.github.raw", f"repos/{repository}/contents/kubelab.yaml?ref={sha}"
    )
    if fetched.returncode != 0:
        raise ContractError(
            f"{repository} has no readable kubelab.yaml at {RELEASE_TAG_PREFIX}{version} ({sha})",
            "a product is deployed only from the contract committed with its image (ADR-067); "
            "a release older than its kubelab.yaml cannot render prod.",
            "promote a release that carries kubelab.yaml.",
        )
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / "kubelab.yaml"
        path.write_text(fetched.stdout, encoding="utf-8")
        validate_registered(path, app, registry)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
    return Release(app=app, repository=repository, version=version, sha=sha, digest=digest)
