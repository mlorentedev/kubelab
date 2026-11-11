"""The receiver's decisions as toolkit commands (IDP-053 S6a).

``product-image-receiver.yml`` used to decide in inline shell which app a dispatch
means, whether this run may act, which commit the image tag names and where the
contract is read. Each is a function here, so it is tested without a runner and goes
through the forge adapter instead of calling ``gh api`` itself. The workflow only
passes the event's context in and reads the answer back.

``route`` reads the registry and nothing else: the receiver needs to know which runner
can reach a product's forge before it can run anything on one.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from toolkit.features import product_registry
from toolkit.features.forge_adapter import ForgeAdapter, ForgeError, adapter_for
from toolkit.features.product_contract import ContractError
from toolkit.features.product_ready import CONTRACT_PATH, commit_of, entry_for, forge_for

#: The immutable CI build tag the receiver admits (ADR-046); the shape is promotion._SHA_TAG's.
_SHA_TAG = re.compile(r"sha-([0-9a-f]{7,})")
_FULL_SHA = re.compile(r"[0-9a-f]{40}")

#: Where a forge's reads run when it is not on a hosted runner: a runner on the homelab, which reaches it.
_SELF_HOSTED = {"gitea": ["self-hosted", "linux", "docker"]}
HOSTED = ["ubuntu-latest"]


@dataclass(frozen=True)
class Resolved:
    app: str
    repository: str
    tag: str
    sha: str
    on_default_branch: bool


@dataclass(frozen=True)
class Fetched:
    app: str
    repository: str
    sha: str


def not_merged(answer: Resolved) -> ContractError:
    return ContractError(
        f"commit {answer.sha} is not on {answer.repository}'s default branch",
        "the image and the contract must come from a commit the product merged.",
        "dispatch the tag of a commit on the default branch.",
    )


def _resolve_on(forge: ForgeAdapter, app: str, tag: str) -> Resolved:
    match = _SHA_TAG.fullmatch(tag)
    if match is None:
        raise ContractError(
            f"unexpected tag '{tag}'",
            "staging tracks only immutable sha-<7+ hex> tags (ADR-046).",
            "pass the tag the product's CI published.",
        )
    sha = commit_of(
        forge,
        tag,
        match.group(1),
        "pass the tag of a commit on the default branch, with more hex digits if two share them.",
    )
    try:
        merged = forge.is_on_default_branch(sha)
    except ForgeError as e:
        raise ContractError(
            f"cannot compare {sha} with {forge.repository}'s default branch",
            f"{forge.name} answered: {e}",
            "run it again once the API answers.",
        ) from None
    return Resolved(app=app, repository=forge.repository, tag=tag, sha=sha, on_default_branch=merged)


def resolve(app: str, tag: str, registry: Path | None = None) -> Resolved:
    """The commit an image tag names on ``app``'s repository and whether the default branch has it."""
    return _resolve_on(forge_for(app, registry), app, tag)


def _dispatched_app(event_type: str, registry: Path | None) -> product_registry.EventRoute:
    try:
        return product_registry.event_route(event_type, registry)
    except product_registry.UnknownEventError:
        raise ContractError(
            f"event type '{event_type}' is not mapped to any product",
            "the registry alone says which event type means which app; the dispatch payload never names it",
            f"admit the product, or add the event type to its entry, in {product_registry.registry_path()}",
        ) from None


def receive(
    event: str,
    *,
    app: str,
    tag: str,
    event_type: str,
    dry_run: str,
    ref: str,
    default_branch: str,
    registry: Path | None = None,
) -> dict[str, object]:
    """What the receiver's resolve step decides for one trigger, in the order it decided.

    ``{"skip": True, "reason": ...}`` when the run has nothing to receive, else the six outputs
    the promote job reads. ``app`` and ``dry_run`` are a manual run's inputs; a dispatch takes
    its app from ``event_type`` and never dry-runs. A refusal is a ``ContractError``.
    """
    manual = event == "workflow_dispatch"
    writes = not manual or dry_run == "false"
    if event == "repository_dispatch":
        routed = _dispatched_app(event_type, registry)
        if routed.lane != "staging":
            return {
                "skip": True,
                "reason": f"event type '{event_type}' belongs to the {routed.lane} lane: not this lane",
            }
        app = routed.app
    elif manual:
        # Both checkouts take the run's branch: from any other, its unmerged commits would ride
        # the force-push to deploy/staging-<app>, and its own registry would decide the legacy check.
        if writes and ref != f"refs/heads/{default_branch}":
            raise ContractError(
                f"a write run must start from {default_branch}, not {ref}",
                f"the branch it starts from is what gets pushed to deploy/staging-{app}",
                f"start it from {default_branch}, or run it with dry_run=true",
            )
    else:
        raise ContractError(
            f"unexpected trigger '{event}'",
            "this workflow runs on repository_dispatch and workflow_dispatch",
            "start it with one of those",
        )
    entry = entry_for(app, registry)
    forge = adapter_for(app, entry)
    if entry.receiver == "legacy":
        if not manual:
            return {"skip": True, "reason": f"'{app}' is receiver: legacy; its own workflow receives this dispatch"}
        if writes:
            raise ContractError(
                f"'{app}' is received by its legacy workflow, so this run may not write deploy/staging-{app}",
                "two receivers writing one branch race each other (IDP-042 design point 10)",
                "run with dry_run=true, or move the product to receiver: generic in infra/config/products.yaml",
            )
    answer = _resolve_on(forge, app, tag)
    if not answer.on_default_branch:
        raise not_merged(answer)
    return {
        "skip": False,
        "app": app,
        "repository": answer.repository,
        "tag": tag,
        "sha": answer.sha,
        "dry_run": not writes,
    }


def fetch_contract(app: str, sha: str, out: Path, registry: Path | None = None) -> Fetched:
    """Write ``app``'s ``kubelab.yaml`` at the commit ``sha`` to ``out``; nothing is written if it cannot be read."""
    if not _FULL_SHA.fullmatch(sha):
        raise ContractError(
            f"'{sha}' is not a full commit sha",
            "the contract is read at one commit, and the sha becomes part of an API path.",
            "pass the 40-hex sha `toolkit product resolve` printed.",
        )
    forge = forge_for(app, registry)
    try:
        fetched = forge.read_file(CONTRACT_PATH, sha)
    except ForgeError as e:
        raise ContractError(
            f"{forge.repository} has no readable kubelab.yaml at {sha}",
            f"a product is deployed only from the contract committed with its image (ADR-067); "
            f"{forge.name} answered: {e}",
            f"add kubelab.yaml at the root of {forge.repository} and publish a new image",
        ) from None
    out.write_text(fetched, encoding="utf-8")
    return Fetched(app=app, repository=forge.repository, sha=sha)


def _hosted(given: str) -> list[str]:
    """``given`` (``RUNNER_DOCKER``: a JSON string or list) as a ``runs-on`` list; empty is the default."""
    try:
        value = json.loads(given) if given else HOSTED
    except ValueError:
        value = None
    value = [value] if isinstance(value, str) else value
    if not (isinstance(value, list) and value and all(isinstance(v, str) and v for v in value)):
        raise ContractError(
            f"RUNNER_DOCKER is not a runner: {given!r}",
            "it becomes the receiver's runs-on, so it must be a JSON string or a non-empty list of them.",
            'set it to something like ["ubuntu-latest"], or unset it for the default.',
        )
    return value


def route(app: str, hosted_runner: str = "", registry: Path | None = None) -> dict[str, object]:
    """The forge ``app`` lives on and the ``runs-on`` its forge reads need, from the registry alone."""
    entry = entry_for(app, registry)
    if not entry.contract_managed:
        raise ContractError(
            f"'{app}' receives no image dispatch (forge: {entry.forge})",
            "an in-tree product has no repository to read, so there is no runner to choose (ADR-048).",
            f"promote it with toolkit deployment promote --env staging --app {app}",
        )
    return {"forge": entry.forge, "runs_on": _SELF_HOSTED.get(entry.forge) or _hosted(hosted_runner)}
