"""One interface over the forge a product's repository lives on (IDP-053 S5).

The receiver, ``product ready`` and ``product release-contract`` read the product's
repository to resolve an image's commit, to prove it was merged and to fetch
``kubelab.yaml`` there. Each used to call ``gh api`` itself and refuse any forge
but GitHub by comparing a string. They ask a ``ForgeAdapter`` now, and ``adapter_for``
is the only place that knows which forges exist: a forge with no implementation is
refused there, and ``tests/test_no_forge_names_outside_adapter.py`` fails if a string
compare on a forge name comes back anywhere else.

The runner is injectable (``Runner``), so a test pins the exact ``gh api`` calls
without a network.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from toolkit.features.product_contract import ContractError
from toolkit.features.product_registry import Product

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")

#: Runs ``gh <args>`` and returns the finished process; a test passes a fake.
Runner = Callable[..., subprocess.CompletedProcess[str]]


class ForgeError(Exception):
    """The forge could not answer, or answered with something that is not what was asked for.

    The message is what the forge said. Each caller words the refusal for its own reader.
    """


@runtime_checkable
class ForgeAdapter(Protocol):
    """What the product path asks of a product's repository, whichever forge hosts it."""

    name: str
    repository: str

    def resolve_commit(self, short: str) -> str:
        """The one full commit sha that starts with ``short``."""
        ...

    def is_on_default_branch(self, sha: str) -> bool:
        """Whether the default branch has ``sha`` (it is the head, or has moved past it)."""
        ...

    def read_file(self, path: str, ref: str) -> str:
        """The bytes of ``path`` at the commit ``ref``."""
        ...

    def resolve_tag(self, tag: str) -> str:
        """The full commit sha a git tag names."""
        ...


def run_gh(*args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["gh", *args], capture_output=True, text=True, check=False)  # noqa: S603, S607
    except FileNotFoundError:
        raise ContractError(
            "the gh CLI is not installed", "the product's repository is read through it", "install gh and log in"
        ) from None


class GitHubForge:
    """``ForgeAdapter`` over ``gh api``, making the calls the receiver workflow made inline."""

    name = "GitHub"

    def __init__(self, repository: str, runner: Runner) -> None:
        self.repository = repository
        self._run = runner

    def _call(self, *args: str) -> str:
        done = self._run("api", *args)
        if done.returncode != 0:
            raise ForgeError((done.stderr or done.stdout).strip())
        return done.stdout

    def _api(self, *args: str) -> str:
        return self._call(*args).strip()

    def _commit(self, ref: str) -> str:
        sha = self._api(f"repos/{self.repository}/commits/{ref}", "--jq", ".sha")
        if not _FULL_SHA.match(sha):
            raise ForgeError(f"{ref} resolved to '{sha}', which is not a full commit sha")
        return sha

    def resolve_commit(self, short: str) -> str:
        sha = self._commit(short)
        if not sha.startswith(short):
            raise ForgeError(f"{short} resolved to {sha}, which does not start with it")
        return sha

    def resolve_tag(self, tag: str) -> str:
        return self._commit(tag)

    def is_on_default_branch(self, sha: str) -> bool:
        branch = self._api(f"repos/{self.repository}", "--jq", ".default_branch")
        status = self._api(f"repos/{self.repository}/compare/{branch}...{sha}", "--jq", ".status")
        # identical: the branch's head. behind: merged, and the branch moved on.
        # ahead or diverged: a commit the product never merged, or a fork's.
        return status in ("identical", "behind")

    def read_file(self, path: str, ref: str) -> str:
        return self._call(
            "-H", "Accept: application/vnd.github.raw", f"repos/{self.repository}/contents/{path}?ref={ref}"
        )


#: The implementation of each forge a registry entry can name; a forge absent here is refused.
_IMPLEMENTATIONS: dict[str, Callable[[str, Runner], ForgeAdapter]] = {"github": GitHubForge}


def adapter_for(app: str, entry: Product, runner: Runner | None = None) -> ForgeAdapter:
    """The adapter for the repository ``entry`` names, or ``ContractError`` if its forge has none."""
    build = _IMPLEMENTATIONS.get(entry.forge)
    if build is None or entry.repository is None:
        raise ContractError(
            f"'{app}' has no repository the toolkit can read (forge: {entry.forge})",
            f"a product's repository is read through a forge adapter, and only {', '.join(sorted(_IMPLEMENTATIONS))} "
            "has one; an in-tree product has no repository to read.",
            "promote an in-tree product in-tree; a product on another forge waits for that forge's adapter.",
        )
    return build(entry.repository, runner or run_gh)
