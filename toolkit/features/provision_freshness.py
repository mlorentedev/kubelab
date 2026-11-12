"""Refuse an Ansible run from a checkout that is behind `origin/master` (OPS-041, #2441).

Ansible renders what the checkout declares, so provisioning from a branch that
predates a change on master quietly puts the older declaration back: on
2026-10-17 the Beelink runner went from `gitea/runner:4.1.0` to
`gitea/act_runner:0.2.13` and nothing failed. A handoff note saying "do not
provision bee" is a reminder, and reminders fail when the situation arrives.

The check is "master changed these paths since this checkout last merged it",
which is `HEAD...origin/master` (three dots: the master side of the merge base).
A branch with its own unmerged changes passes; a branch that has not pulled a
change to the roles or the values it renders does not. It does not try to work
out which roles a playbook pulls in: role dependencies and `import_playbook`
make that brittle, and a refusal that costs one `git merge` is cheaper than a
rollback that costs a running job.

The controller is the other half of what a run renders: the Galaxy collections
the roles call. They are pinned exactly in `requirements.yml` (ANSIBLE-070,
#2735), and a run compares them with what the controller holds, because a pin
the controller never installed changes nothing. A floor had left the operator's
controller on an `authorized_key` with a known privilege escalation.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml
from yaml.composer import ComposerError

#: What an Ansible run renders: the playbooks and roles, the values they read, and the code that
#: turns the values into the inventory (a change to its host vars reaches a node the same way).
RENDERED_PATHS = ("infra/ansible", "infra/config/values", "toolkit/features/generator_ansible.py")

MASTER_REF = "origin/master"

#: The Galaxy collections the roles call, each pinned to one version.
REQUIREMENTS = "infra/ansible/requirements.yml"

#: The one repair for a collection that is not at its pin. `collections_refusal_message` and the
#: doctor both print it: a seat that reads either has to end up at the same command, or the two
#: diagnoses disagree about what to do and one of them is a dead end (TOOL-131).
COLLECTIONS_FIX = (
    "make setup-ansible and run again. It installs into the user path, so a stale copy elsewhere "
    "stays: the full `ansible` package bundles its own, so uninstall it and keep ansible-core."
)

#: A listing nothing can read is not a version problem -- there is no version to compare, so
#: `make setup-ansible` is only a guess and the message must not claim it is the repair.
COLLECTIONS_LISTING_FIX = (
    "run `ansible-galaxy collection list --format json` and fix what it reports; if it fails to run "
    "at all, `make setup-ansible` repairs the venv it comes from."
)

#: A declaration nothing can read is neither of the above: the run is held to that file, so the file
#: is what has to be repaired. `ansible-galaxy` is a working tool asked to compare against nothing.
DECLARATION_FIX = f"repair {REQUIREMENTS}: the run is held to it, so it has to be readable"


class FreshnessError(Exception):
    """The checkout could not be compared with master; treated as a refusal."""


class DeclarationError(FreshnessError):
    """`requirements.yml` cannot be read, so there is nothing to compare against.

    A subclass of `FreshnessError` because every caller already refuses on that type; the split
    exists so the refusal can name the file. Answered as `FreshnessError`, a `requirements.yml` with
    a stray second document was reported as "Fix ansible-galaxy" -- a repair for a tool that works,
    for a file the operator was never told was the problem.
    """


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603 - fixed git argv, no shell
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if done.returncode != 0:
        raise FreshnessError(f"git {' '.join(args)}: {done.stderr.strip() or done.stdout.strip()}")
    return done.stdout


def repo_root(start: Path) -> Path:
    return Path(_git(start, "rev-parse", "--show-toplevel").strip())


def paths_behind_master(start: Path, *, fetch: bool = True) -> list[str]:
    """Rendered files `origin/master` changed that this checkout has not merged."""
    root = repo_root(start)
    if fetch:
        _git(root, "fetch", "--quiet", "origin", "master")
    changed = _git(root, "diff", "--name-only", f"HEAD...{MASTER_REF}", "--", *RENDERED_PATHS)
    return [line for line in changed.splitlines() if line]


def refusal_message(behind: list[str]) -> str:
    shown = "\n".join(f"  {path}" for path in behind[:10])
    more = f"\n  ... and {len(behind) - 10} more" if len(behind) > 10 else ""
    return (
        f"ERROR: this checkout is behind {MASTER_REF} on what Ansible renders ({len(behind)} files):\n"
        f"{shown}{more}\n"
        "WHY: the run applies what this checkout declares, so it would put the older declaration back "
        "on the node (OPS-041, the Beelink runner rolled back 2026-10-17).\n"
        f"FIX: git merge {MASTER_REF} and run again; FORCE=1 only if the older declaration is what you mean to apply."
    )


def declared_collections(root: Path) -> dict[str, str]:
    """The version `requirements.yml` pins for each collection.

    Every way the declaration can be unreadable raises `DeclarationError` instead of
    the parser's or the mapping's own exception. Both callers already treat its
    parent type as "refuse and say why" -- a bare `FileNotFoundError` or `KeyError`
    would leave the preflight as a traceback and the doctor as a crash, which is the
    difference between a refusal and a bug -- and the subtype is what tells the
    refusal to name the file rather than the tool.
    """
    try:
        text = (root / REQUIREMENTS).read_text(encoding="utf-8")
    except OSError as exc:
        raise DeclarationError(f"{REQUIREMENTS}: {exc.strerror or exc}") from exc
    try:
        data = yaml.safe_load(text) or {}
    except ComposerError as exc:
        # `safe_load` reads exactly one document, so a second `---` is not a syntax error.
        # Reporting it as one sends the reader looking for a typo that is not there.
        raise DeclarationError(f"{REQUIREMENTS} is more than one YAML document: {exc}") from exc
    except yaml.YAMLError as exc:
        raise DeclarationError(f"{REQUIREMENTS} is not YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise DeclarationError(f"{REQUIREMENTS} is a {type(data).__name__}, not a mapping")
    entries = data.get("collections")
    # An absent or empty `collections` yields an empty declaration, and an empty
    # declaration makes `collections_off_declaration` return nothing for any
    # controller: the gate would pass vacuously, which is the fail-open this
    # ticket exists for. Say so instead.
    if not isinstance(entries, list) or not entries:
        raise DeclarationError(
            f"{REQUIREMENTS} declares no usable `collections` list ({entries!r}), so nothing is pinned"
        )
    declared: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict) or "name" not in entry or "version" not in entry:
            raise DeclarationError(f"{REQUIREMENTS}: {entry!r} is not a `name`/`version` mapping")
        declared[str(entry["name"])] = str(entry["version"])
    return declared


def collections_off_declaration(declared: dict[str, str]) -> list[str]:
    """Each declared collection the controller holds at any other version, or not at all.

    Every copy counts, not only the one Ansible would load: `ansible-galaxy
    collection list` walks its search paths as a set, so its output cannot say
    which copy wins, and a second copy is a stale version waiting for the
    search path to change.

    Like `declared_collections`, every way the listing can be unreadable raises
    `FreshnessError`: both callers treat that type as "refuse and say why", so a
    bare `FileNotFoundError` or `JSONDecodeError` is a traceback where the
    contract is a refusal -- and it takes `FORCE=1` with it. Deliberately the
    parent type and not `DeclarationError`: this is the tool failing, not the file.
    """
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["ansible-galaxy", "collection", "list", "--format", "json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except OSError as exc:
        # `ansible-playbook` on PATH does not imply this one is, and the doctor
        # checks only the former before it reaches this call.
        raise FreshnessError(f"ansible-galaxy cannot be run: {exc.strerror or exc}") from exc
    if done.returncode != 0:
        raise FreshnessError(f"ansible-galaxy collection list: {done.stderr.strip() or done.stdout.strip()}")
    try:
        listed = json.loads(done.stdout or "{}")
    except ValueError as exc:
        raise FreshnessError(f"ansible-galaxy collection list is not JSON: {exc}") from exc
    if not isinstance(listed, dict):
        raise FreshnessError(f"ansible-galaxy collection list is a {type(listed).__name__}, not a mapping")
    held: dict[str, dict[str, list[str]]] = {}  # name -> version -> the paths holding it
    for path, collections in listed.items():
        if not isinstance(collections, dict):
            raise FreshnessError(f"ansible-galaxy collection list: {path!r} maps to a {type(collections).__name__}")
        for name, meta in collections.items():
            if not isinstance(meta, dict):
                raise FreshnessError(f"ansible-galaxy collection list: {name!r} maps to a {type(meta).__name__}")
            held.setdefault(name, {}).setdefault(str(meta.get("version")), []).append(path)
    off = []
    for name, version in sorted(declared.items()):
        found = held.get(name, {})
        if set(found) != {version}:
            # Where a stale copy is, because `make setup-ansible` replaces only the user path's.
            copies = [v if v == version else f"{v} at {', '.join(sorted(found[v]))}" for v in sorted(found)]
            off.append(f"{name} {', '.join(copies) or 'missing'} (declared {version})")
    return off


def collections_refusal_message(off: list[str]) -> str:
    shown = "\n".join(f"  {line}" for line in off)
    return (
        f"ERROR: this controller does not hold the Galaxy collections {REQUIREMENTS} pins:\n"
        f"{shown}\n"
        "WHY: the roles run whatever version the controller has, and a stale one keeps the bugs and "
        "security fixes the pin moved past (ANSIBLE-070, authorized_key on ansible.posix 2.1.0).\n"
        f"FIX: {COLLECTIONS_FIX} "
        "FORCE=1 only if you mean to run with these versions."
    )
