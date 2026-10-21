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

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from toolkit.features import product_registry, promotion
from toolkit.features.product_contract import ContractError
from toolkit.features.product_guards import validate_registered

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class Ready:
    app: str
    repository: str
    tag: str
    sha: str


def _gh(*args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["gh", *args], capture_output=True, text=True, check=False)  # noqa: S603, S607
    except FileNotFoundError:
        raise ContractError(
            "the gh CLI is not installed", "this gate reads the product repository", "install gh and log in"
        ) from None


def check_ready(app: str, env: str = "staging", registry: Path | None = None) -> Ready:
    """Return what the receiver would deploy for ``app``, or raise ``ContractError`` saying why it would not."""
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
            f"'{app}' is not received from a GitHub repository (forge: {entry.forge})",
            "only a product with a remote contract moves to the generic receiver.",
            "nothing to check: this product is promoted in-tree.",
        )
    try:
        tag = promotion.resolve_image_sha(env, app)
    except ValueError as e:
        raise ContractError(
            str(e), f"the gate checks the commit {env} runs now.", f"deploy a sha build to {env}."
        ) from None
    short = tag.removeprefix("sha-")

    commit = _gh("api", f"repos/{entry.repository}/commits/{short}", "--jq", ".sha")
    sha = commit.stdout.strip()
    if commit.returncode != 0 or not _FULL_SHA.match(sha) or not sha.startswith(short):
        raise ContractError(
            f"{env} pin {tag} does not resolve to one commit of {entry.repository}",
            f"GitHub answered: {(commit.stderr or sha).strip()}",
            f"deploy an image of a commit on {entry.repository}'s default branch to {env}.",
        )

    fetched = _gh(
        "api", "-H", "Accept: application/vnd.github.raw", f"repos/{entry.repository}/contents/kubelab.yaml?ref={sha}"
    )
    if fetched.returncode != 0:
        raise ContractError(
            f"{entry.repository} has no readable kubelab.yaml at {tag} ({sha})",
            "after the flip, every image without a contract at its commit is refused, so staging would stall.",
            f"merge kubelab.yaml in {entry.repository}, then let its next image reach {env}, then check again.",
        )
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / "kubelab.yaml"
        path.write_text(fetched.stdout, encoding="utf-8")
        validate_registered(path, app, registry)
    return Ready(app=app, repository=entry.repository, tag=tag, sha=sha)
