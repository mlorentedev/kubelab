"""Decide whether a pull request is a mechanical staging deploy (DELIVERY-004, #1619).

A mechanical deploy is what `toolkit deployment promote --env staging` writes and
nothing else: one app's version moved to an immutable `sha-` tag, and the
regenerated overlay pointing the same image at the same tag. Such a PR carries
nothing a reviewer could act on, so it is exempt from review, and once the
operator flips the switch it merges without a click. That makes this module a
grant, and every condition below narrows it.

Three verdicts, never two:

    mechanical      every condition holds at one verified head sha
    not-mechanical  evaluated, and some condition does not hold: the PR takes
                    the normal review path
    unknown         something could not be read or parsed: fails closed

The class itself (env, files, version path, tag pattern) is declared in the
reviewer registry, `mechanical`, and read from there; this module names none of
it. Branch name and author are never read: anyone who can push a branch can
mint either.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

from toolkit.features.product_registry import Product

MECHANICAL = "mechanical"
NOT_MECHANICAL = "not-mechanical"
UNKNOWN = "unknown"


class DeclarationError(ValueError):
    """The registry's `mechanical` block is missing or the wrong shape."""


@dataclass(frozen=True)
class Declaration:
    name: str
    check: str
    env: str
    files: tuple[str, ...]
    version_path: tuple[str, ...]
    tag_pattern: re.Pattern[str]


@dataclass(frozen=True)
class Shape:
    verdict: str
    reason: str
    app: str | None = None
    old: str | None = None
    new: str | None = None
    head_sha: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


def load_declaration(path: Path) -> Declaration:
    """Read the `mechanical` block, failing closed on any missing or empty field."""
    try:
        block = json.loads(path.read_text(encoding="utf-8")).get("mechanical")
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        raise DeclarationError(f"cannot read the mechanical declaration from {path}: {exc}") from exc
    if not isinstance(block, dict):
        raise DeclarationError(f"{path} declares no `mechanical` block")
    name, check, env, tag_pattern = (block.get(k) for k in ("name", "check", "env", "tag_pattern"))
    files, version_path = block.get("files"), block.get("version_path")
    if not all(isinstance(v, str) and v for v in (name, check, env, tag_pattern)) or not all(
        isinstance(v, list) and v and all(isinstance(i, str) and i for i in v) for v in (files, version_path)
    ):
        raise DeclarationError(
            f"{path}: `mechanical` needs non-empty name, check, env, tag_pattern, files[] and version_path[]"
        )
    assert isinstance(files, list) and isinstance(version_path, list) and isinstance(tag_pattern, str)
    if "{app}" not in version_path:
        raise DeclarationError(f"{path}: `mechanical.version_path` must name the app as `{{app}}`")
    try:
        pattern = re.compile(tag_pattern)
    except re.error as exc:
        raise DeclarationError(f"{path}: `mechanical.tag_pattern` is not a regex: {exc}") from exc
    return Declaration(
        name=str(name),
        check=str(check),
        env=str(env),
        files=tuple(files),
        version_path=tuple(version_path),
        tag_pattern=pattern,
    )


# --------------------------------------------------------------------------- #
# The pure predicate
# --------------------------------------------------------------------------- #

_MISSING = object()


def _leaves(before: Any, after: Any, path: tuple[Any, ...] = ()) -> list[tuple[tuple[Any, ...], Any, Any]]:
    """Every leaf that differs, as (path, before, after). A shape change is one leaf."""
    if isinstance(before, dict) and isinstance(after, dict):
        out = []
        for key in list(before) + [k for k in after if k not in before]:
            out += _leaves(before.get(key, _MISSING), after.get(key, _MISSING), (*path, key))
        return out
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        out = []
        for i, (b, a) in enumerate(zip(before, after, strict=True)):
            out += _leaves(b, a, (*path, i))
        return out
    return [] if before == after else [(path, before, after)]


def classify_diff(
    changes: list[dict[str, Any]],
    before: Mapping[str, str],
    after: Mapping[str, str],
    apps: Iterable[str],
    decl: Declaration,
) -> Shape:
    """Judge one diff against the declaration. Pure: no IO, no network.

    `changes` is the PR's file list (`filename`, `status`); `before`/`after` hold
    each declared file's text at the merge base and at the head.
    """
    names = {c.get("filename") for c in changes}
    if names != set(decl.files) or len(changes) != len(decl.files):
        return Shape(NOT_MECHANICAL, f"the changed files are not exactly the {decl.name} set")
    if any(c.get("status") != "modified" for c in changes):
        return Shape(NOT_MECHANICAL, "a declared file was added, removed or renamed, not modified")

    values_path, *overlay_paths = decl.files
    try:
        values = _leaves(yaml.safe_load(before[values_path]), yaml.safe_load(after[values_path]))
        overlay: list[tuple[tuple[Any, ...], Any, Any]] = []
        for overlay_path in overlay_paths:
            docs_before = list(yaml.safe_load_all(before[overlay_path]))
            docs_after = list(yaml.safe_load_all(after[overlay_path]))
            overlay += _leaves(docs_before, docs_after)
    except (KeyError, yaml.YAMLError) as exc:
        return Shape(UNKNOWN, f"cannot read the declared files: {exc!r}")

    if len(values) != 1:
        return Shape(NOT_MECHANICAL, f"{len(values)} values changed; a deploy moves exactly one version")
    (leaf, old, new) = values[0]
    slot = decl.version_path.index("{app}")
    app = leaf[slot] if len(leaf) == len(decl.version_path) and isinstance(leaf[slot], str) else None
    expected = tuple(app if part == "{app}" else part for part in decl.version_path)
    if app is None or leaf != expected or app not in set(apps):
        return Shape(NOT_MECHANICAL, f"the changed value {'.'.join(map(str, leaf))} is not a registered app's version")
    if not isinstance(old, str) or not isinstance(new, str) or not decl.tag_pattern.fullmatch(new):
        return Shape(NOT_MECHANICAL, f"{app} moved to {new!r}, which is not an immutable tag this class admits")

    if not overlay:
        return Shape(NOT_MECHANICAL, f"{app}'s version moved and the overlay did not")
    for leaf_path, image_before, image_after in overlay:
        if not leaf_path or leaf_path[-1] != "image":
            return Shape(NOT_MECHANICAL, f"the overlay changed {leaf_path!r}, which is not an image")
        if not isinstance(image_before, str) or not isinstance(image_after, str):
            return Shape(NOT_MECHANICAL, "an overlay image is not a string")
        repo, _, tag_before = image_before.rpartition(":")
        repo_after, _, tag_after = image_after.rpartition(":")
        if not repo or repo != repo_after or (tag_before, tag_after) != (old, new):
            return Shape(NOT_MECHANICAL, f"the overlay moved {image_before} to {image_after}, not {old} to {new}")

    return Shape(MECHANICAL, f"{app} {old} -> {new}, overlay image only", app=app, old=old, new=new)


# --------------------------------------------------------------------------- #
# Reading the PR, and the tag's provenance
# --------------------------------------------------------------------------- #


class Api(Protocol):
    def json(self, path: str) -> Any: ...

    def raw(self, path: str) -> str: ...


class GhApi:
    """`gh api`, so the token comes from GH_TOKEN and never reaches a command line."""

    def _run(self, args: list[str]) -> str:
        done = subprocess.run(["gh", "api", *args], capture_output=True, text=True, check=False, timeout=60)
        if done.returncode != 0:
            raise RuntimeError(f"gh api {args[-1]} failed: {done.stderr.strip()[:300]}")
        return done.stdout

    def json(self, path: str) -> Any:
        return json.loads(self._run([path]))

    def raw(self, path: str) -> str:
        return self._run(["-H", "Accept: application/vnd.github.raw", path])


def _head(api: Api, repo: str, number: int) -> tuple[str, str, str]:
    pr = api.json(f"repos/{repo}/pulls/{number}")
    return pr["head"]["sha"], pr["base"]["ref"], pr["base"]["repo"]["default_branch"]


def _provenance(api: Api, repository: str, tag: str) -> str | None:
    """None when the tag's commit is on the repository's default branch, else why not.

    The same checks the receiver runs on its input (product-image-receiver.yml),
    run again on the output, which is all a `pull_request` check can know of the
    dispatch.
    """
    short = tag.split("-", 1)[1]
    sha = api.json(f"repos/{repository}/commits/{short}")["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha or "") or not sha.startswith(short):
        return f"{tag} resolved to {sha!r} in {repository}, not a commit starting with {short}"
    branch = api.json(f"repos/{repository}")["default_branch"]
    status = api.json(f"repos/{repository}/compare/{branch}...{sha}")["status"]
    if status not in ("identical", "behind"):
        return f"{sha} is not on {repository}'s {branch} (compare: {status})"
    return None


def evaluate(number: int, repo: str, api: Api, decl: Declaration, products: Mapping[str, Product]) -> Shape:
    """Read PR `number` of `repo` through `api` and judge it at one head sha.

    Any API or parse failure is `unknown`. The head is read before and after, and a
    push in between is `unknown` too: the verdict must name the sha it judged.
    """
    try:
        head, base_ref, default_branch = _head(api, repo, number)
        if base_ref != default_branch:
            return Shape(NOT_MECHANICAL, f"the PR targets {base_ref}, not {default_branch}", head_sha=head)
        changes = api.json(f"repos/{repo}/pulls/{number}/files?per_page=100")
        if {c.get("filename") for c in changes} != set(decl.files):
            shape = Shape(NOT_MECHANICAL, f"the changed files are not exactly the {decl.name} set")
        else:
            merge_base = api.json(f"repos/{repo}/compare/{default_branch}...{head}")["merge_base_commit"]["sha"]
            before = {p: api.raw(f"repos/{repo}/contents/{p}?ref={merge_base}") for p in decl.files}
            after = {p: api.raw(f"repos/{repo}/contents/{p}?ref={head}") for p in decl.files}
            shape = classify_diff(changes, before, after, products, decl)
            if shape.verdict == MECHANICAL:
                product = products[shape.app or ""]
                if product.forge == "in-tree":
                    repository = repo
                elif product.forge == "github" and product.repository:
                    repository = product.repository
                else:
                    return Shape(NOT_MECHANICAL, f"{shape.app}'s forge ({product.forge}) cannot be proven here")
                why = _provenance(api, repository, shape.new or "")
                if why:
                    shape = Shape(NOT_MECHANICAL, why, app=shape.app, old=shape.old, new=shape.new)
        if _head(api, repo, number)[0] != head:
            return Shape(UNKNOWN, "the PR's head moved while it was being judged")
    except Exception as exc:  # noqa: BLE001 — any failure to read is a verdict of `unknown`
        return Shape(UNKNOWN, f"cannot evaluate PR #{number}: {exc!r}")
    return Shape(shape.verdict, shape.reason, shape.app, shape.old, shape.new, head_sha=head)
