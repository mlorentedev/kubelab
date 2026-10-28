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

#: What an Ansible run renders: the playbooks and roles, the values they read, and the code that
#: turns the values into the inventory (a change to its host vars reaches a node the same way).
RENDERED_PATHS = ("infra/ansible", "infra/config/values", "toolkit/features/generator_ansible.py")

MASTER_REF = "origin/master"

#: The Galaxy collections the roles call, each pinned to one version.
REQUIREMENTS = "infra/ansible/requirements.yml"


class FreshnessError(Exception):
    """The checkout could not be compared with master; treated as a refusal."""


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603 - fixed git argv, no shell
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
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
    """The version `requirements.yml` pins for each collection."""
    data = yaml.safe_load((root / REQUIREMENTS).read_text(encoding="utf-8")) or {}
    return {str(c["name"]): str(c["version"]) for c in data.get("collections") or []}


def collections_off_declaration(declared: dict[str, str]) -> list[str]:
    """Each declared collection the controller holds at any other version, or not at all.

    Every copy counts, not only the one Ansible would load: `ansible-galaxy
    collection list` walks its search paths as a set, so its output cannot say
    which copy wins, and a second copy is a stale version waiting for the
    search path to change.
    """
    done = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["ansible-galaxy", "collection", "list", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise FreshnessError(f"ansible-galaxy collection list: {done.stderr.strip() or done.stdout.strip()}")
    held: dict[str, set[str]] = {}
    for collections in json.loads(done.stdout or "{}").values():
        for name, meta in collections.items():
            held.setdefault(name, set()).add(str(meta.get("version")))
    off = []
    for name, version in sorted(declared.items()):
        found = held.get(name, set())
        if found != {version}:
            off.append(f"{name} {', '.join(sorted(found)) or 'missing'} (declared {version})")
    return off


def collections_refusal_message(off: list[str]) -> str:
    shown = "\n".join(f"  {line}" for line in off)
    return (
        f"ERROR: this controller does not hold the Galaxy collections {REQUIREMENTS} pins:\n"
        f"{shown}\n"
        "WHY: the roles run whatever version the controller has, and a stale one keeps the bugs and "
        "security fixes the pin moved past (ANSIBLE-070, authorized_key on ansible.posix 2.1.0).\n"
        "FIX: make setup-ansible and run again; FORCE=1 only if you mean to run with these versions."
    )
