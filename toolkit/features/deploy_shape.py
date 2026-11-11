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
                    (a product's forge that does not answer is the exception: the
                    commit it could not place is not proven, so not-mechanical)

The class itself (env, files, version path, tag pattern) is declared in the
reviewer registry, `mechanical`, and read from there; this module names none of
it. Branch name and author are never read: anyone who can push a branch can
mint either.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

from toolkit.features.forge_adapter import ForgeAdapter, ForgeError, GitHubForge, Runner, adapter_for
from toolkit.features.product_contract import ContractError
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
    values_file: str
    overlay_files: tuple[str, ...]
    version_path: tuple[str, ...]
    tag_pattern: re.Pattern[str]

    @property
    def files(self) -> tuple[str, ...]:
        return (self.values_file, *self.overlay_files)


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
    except (OSError, ValueError, AttributeError) as exc:  # ValueError: bad JSON or bytes
        raise DeclarationError(f"cannot read the mechanical declaration from {path}: {exc}") from exc
    if not isinstance(block, dict):
        raise DeclarationError(f"{path} declares no `mechanical` block")
    name, check, env, values_file, tag_pattern = (
        block.get(k) for k in ("name", "check", "env", "values_file", "tag_pattern")
    )
    overlay_files, version_path = block.get("overlay_files"), block.get("version_path")
    if not all(isinstance(v, str) and v for v in (name, check, env, values_file, tag_pattern)) or not all(
        isinstance(v, list) and v and all(isinstance(i, str) and i for i in v) for v in (overlay_files, version_path)
    ):
        raise DeclarationError(
            f"{path}: `mechanical` needs non-empty name, check, env, values_file, overlay_files[], "
            "tag_pattern and version_path[]"
        )
    assert isinstance(overlay_files, list) and isinstance(version_path, list) and isinstance(tag_pattern, str)
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
        values_file=str(values_file),
        overlay_files=tuple(overlay_files),
        version_path=tuple(version_path),
        tag_pattern=pattern,
    )


# --------------------------------------------------------------------------- #
# The pure predicate
# --------------------------------------------------------------------------- #

_MISSING = object()


def _leaves(before: Any, after: Any, path: tuple[Any, ...] = ()) -> list[tuple[tuple[Any, ...], Any, Any]]:
    """Every leaf that differs, as (path, before, after). A shape change is one leaf.

    Leaves compare by type and value: Python has `false == 0 == 0.0`, and a YAML
    type change is a change (#3062 F5).
    """
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
    return [] if (type(before), before) == (type(after), after) else [(path, before, after)]


def _owner(docs: Any, path: tuple[Any, ...]) -> Any:
    """The `name` of the mapping that holds the leaf at `path`, or None."""
    node = docs
    try:
        for key in path[:-1]:
            node = node[key]
    except (KeyError, IndexError, TypeError):
        return None
    return node.get("name") if isinstance(node, dict) else None


def classify_diff(
    changes: list[dict[str, Any]],
    before: Mapping[str, str],
    after: Mapping[str, str],
    apps: Iterable[str],
    decl: Declaration,
) -> Shape:
    """Judge one diff against the declaration. Pure: no IO, no network.

    `changes` is the PR's file list (`filename`, `status`); `before`/`after` hold
    each declared file's text at the merge base and at the head. Each rule is its
    own function, and the first one that refuses decides.
    """
    refusal = _file_set_refusal(changes, decl)
    if refusal:
        return refusal
    try:
        values, overlay = _changed_leaves(before, after, decl)
    except (KeyError, yaml.YAMLError) as exc:
        return Shape(UNKNOWN, f"cannot read the declared files: {exc!r}")
    moved = _version_move(values, apps, decl)
    if isinstance(moved, Shape):
        return moved
    app, old, new = moved
    return _overlay_refusal(overlay, app, old, new) or Shape(
        MECHANICAL, f"{app} {old} -> {new}, overlay image only", app=app, old=old, new=new
    )


def _file_set_refusal(changes: list[dict[str, Any]], decl: Declaration) -> Shape | None:
    """Exactly the declared files, each one modified."""
    names = {c.get("filename") for c in changes}
    if names != set(decl.files) or len(changes) != len(decl.files):
        return Shape(NOT_MECHANICAL, f"the changed files are not exactly the {decl.name} set")
    if any(c.get("status") != "modified" for c in changes):
        return Shape(NOT_MECHANICAL, "a declared file was added, removed or renamed, not modified")
    return None


# (path, before, after), and for the overlay the container the leaf belongs to.
_Leaf = tuple[tuple[Any, ...], Any, Any]
_OverlayLeaf = tuple[tuple[Any, ...], Any, Any, Any]


def _changed_leaves(
    before: Mapping[str, str], after: Mapping[str, str], decl: Declaration
) -> tuple[list[_Leaf], list[_OverlayLeaf]]:
    """The values leaves that differ, and the overlay leaves with the container each belongs to."""
    values = _leaves(yaml.safe_load(before[decl.values_file]), yaml.safe_load(after[decl.values_file]))
    overlay: list[_OverlayLeaf] = []
    for overlay_path in decl.overlay_files:
        docs_before = list(yaml.safe_load_all(before[overlay_path]))
        docs_after = list(yaml.safe_load_all(after[overlay_path]))
        overlay += [(p, b, a, _owner(docs_after, p)) for p, b, a in _leaves(docs_before, docs_after)]
    return values, overlay


def _version_move(values: list[_Leaf], apps: Iterable[str], decl: Declaration) -> Shape | tuple[str, str, str]:
    """(app, old, new) when the one changed value is a registered app's version moving to an admitted tag."""
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
    return app, old, new


def _overlay_refusal(overlay: list[_OverlayLeaf], app: str, old: str, new: str) -> Shape | None:
    """Only `app`'s image moved in the overlay, from <repo>:<old> to <repo>:<new>."""
    if not overlay:
        return Shape(NOT_MECHANICAL, f"{app}'s version moved and the overlay did not")
    for leaf_path, image_before, image_after, owner in overlay:
        if not leaf_path or leaf_path[-1] != "image":
            return Shape(NOT_MECHANICAL, f"the overlay changed {leaf_path!r}, which is not an image")
        if not isinstance(image_before, str) or not isinstance(image_after, str):
            return Shape(NOT_MECHANICAL, "an overlay image is not a string")
        repo, _, tag_before = image_before.rpartition(":")
        repo_after, _, tag_after = image_after.rpartition(":")
        if not repo or repo != repo_after or (tag_before, tag_after) != (old, new):
            return Shape(NOT_MECHANICAL, f"the overlay moved {image_before} to {image_after}, not {old} to {new}")
        # Two apps can share a tag after a joint deploy, so old -> new alone does not say
        # whose image moved; the container it belongs to does (#2983).
        if owner != app:
            return Shape(NOT_MECHANICAL, f"the overlay moved the image of container {owner!r}, not {app}'s")
    return None


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


def gh_over(api: Api) -> Runner:
    """The GitHub adapter's `gh` runner, answering through `api`.

    The judge reads the PR and the product through one transport, so a read that fails is
    the same exception either way: `unknown`, never a verdict. `GitHubForge` makes two kinds
    of call (`--jq .field` and a raw `-H` fetch); anything else is refused, not guessed at.
    """

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        if len(args) == 4 and args[0] == "api" and args[2] == "--jq" and re.fullmatch(r"\.\w+", args[3]):
            out = str(api.json(args[1])[args[3][1:]])
        elif len(args) == 4 and args[:2] == ("api", "-H"):
            out = api.raw(args[3])
        else:
            raise ValueError(f"unsupported gh call: {args}")
        return subprocess.CompletedProcess(list(args), 0, stdout=out, stderr="")

    return run


def _commit(forge: ForgeAdapter, tag: str) -> str:
    """The full commit sha a `sha-<short>` tag names in the product's repository."""
    if not re.fullmatch(r"sha-[0-9a-f]{7,40}", tag):
        raise ForgeError(f"{tag!r} is not a sha-<short> tag")
    return forge.resolve_commit(tag.split("-", 1)[1])


def _provenance(forge: ForgeAdapter, old: str, new: str) -> str | None:
    """None when `new` is on the default branch and moves `old` forward, else why not.

    The first half is the receiver's own check on its input (product-image-receiver.yml),
    run again on the output, which is all a `pull_request` check can know of the
    dispatch. The second half refuses a rollback (#796): a pin moved back to an older
    commit is a clean version move too, and it comes from a stale or out-of-order PR,
    never from a generator. A revert rolls back by building a newer commit, which
    passes; going back to an older image is a merge a human makes.

    A `ForgeError` means the forge could not place a commit or answer: `evaluate` words it.
    """
    sha = _commit(forge, new)
    if not forge.is_on_default_branch(sha):
        return f"{sha} is not on {forge.repository}'s default branch"
    try:
        previous = _commit(forge, old)
    except ForgeError as exc:
        raise ForgeError(f"the current pin cannot be placed: {exc}") from None
    if not forge.is_ahead_of(previous, sha):
        return f"{new} does not move {old} forward in {forge.repository}; a rollback is merged by hand"
    return None


def _unproven(forge: ForgeAdapter, new: str, exc: ForgeError) -> str:
    return str(
        ContractError(
            f"{new} cannot be proven against {forge.repository} on {forge.name}: {exc}",
            "a deploy skips review only when its image tag is a commit the product merged and the pin moved forward, "
            "and the forge could not say.",
            "the PR takes the normal review path; once the forge answers, push again or re-run this check.",
        )
    )


ForgeFor = Callable[[str, Product], ForgeAdapter]


def _default_forge(repo: str, api: Api) -> ForgeFor:
    """An in-tree product is proven against `repo` (GitHub, read through `api`), any other through its adapter."""
    runner = gh_over(api)

    def build(app: str, product: Product) -> ForgeAdapter:
        return GitHubForge(repo, runner) if product.forge == "in-tree" else adapter_for(app, product, runner)

    return build


def _proven(shape: Shape, forge_for: ForgeFor, products: Mapping[str, Product]) -> Shape:
    """`shape` when its tag is proven against the product's repository, else the refusal."""
    app = shape.app or ""
    try:
        forge = forge_for(app, products[app])
    except ContractError as exc:  # a forge with no adapter, or one whose settings are missing
        return Shape(NOT_MECHANICAL, str(exc), app=shape.app, old=shape.old, new=shape.new)
    try:
        why = _provenance(forge, shape.old or "", shape.new or "")
    except ForgeError as exc:
        why = _unproven(forge, shape.new or "", exc)
    return Shape(NOT_MECHANICAL, why, app=shape.app, old=shape.old, new=shape.new) if why else shape


def evaluate(
    number: int,
    repo: str,
    api: Api,
    decl: Declaration,
    products: Mapping[str, Product],
    forge_for: ForgeFor | None = None,
) -> Shape:
    """Read PR `number` of `repo` through `api` and judge it at one head sha.

    Any API or parse failure is `unknown`. The head is read before and after, and a
    push in between is `unknown` too: the verdict must name the sha it judged.
    `forge_for` builds the adapter that proves a product's tag against its repository
    (`_default_forge` when absent).
    """
    forge_for = forge_for or _default_forge(repo, api)
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
                shape = _proven(shape, forge_for, products)
        if _head(api, repo, number)[0] != head:
            return Shape(UNKNOWN, "the PR's head moved while it was being judged")
    except Exception as exc:  # noqa: BLE001 — any failure to read is a verdict of `unknown`
        return Shape(UNKNOWN, f"cannot evaluate PR #{number}: {exc!r}")
    return Shape(shape.verdict, shape.reason, shape.app, shape.old, shape.new, head_sha=head)
