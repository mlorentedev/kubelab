"""Read-only diagnosis of the Ansible controller a checkout needs to provision.

`make setup-ansible` reported success on a machine that could not run Ansible:
when `ansible-galaxy` was missing it printed `skipping` and exited 0 (TOOL-131,
#3202). The consequence is worse than a missing tool — `collections_refusal_message()`
in `provision_freshness` tells the operator literally `FIX: make setup-ansible`,
which pointed at the target that was silently doing nothing.

So the setup path needs a check that can FAIL, and the same check has to be
runnable afterwards, by hand, to answer "is this machine a working controller?".
That is this module.

It touches no network and no host: every check is local state, so it is safe to
run before a host window is agreed, and it is what `make setup-ansible` ends with.

The checks, and why each one is here:

1. **`ansible-playbook` resolves and reports a version.** `toolkit infra ansible
   run` shells out to it (`toolkit/cli/infra.py`), so it must be on the PATH of
   the process that runs the toolkit — not merely installed somewhere. Two
   different failures live here and they need different fixes: the binary is not
   installed, or it is installed and cannot execute. `ansible-core` refuses a
   Windows controller outright — every CLI entry point calls `check_blocking_io()`,
   which raises `OSError: [WinError 87]` on `os.get_blocking` (measured on 2.21.6,
   TOOL-131). Telling someone to `make setup-ansible` there sends them to reinstall
   a package that will fail again.
2. **The Galaxy collections match `requirements.yml`.** The pins are exact by
   design (ANSIBLE-070, #2735): with floors, `ansible-galaxy collection install
   -r` is a no-op when the installed version satisfies the range, and a controller
   sat one release behind a privilege-escalation fix in `authorized_key`.
3. **The config file in effect is this repo's `infra/ansible/ansible.cfg`.**
   Ansible reads exactly one config file, the first it finds, and the repo's
   turns a host-pattern mismatch into a failure (lesson-356, #1228). A raw
   `ansible-playbook` run from another directory silently gets the default
   (warning, exit 0) and reports success having touched nothing.
4. **The static inventory parses and carries hosts.** It is what
   `make lint-ansible` and CI use, and what an offline controller can be checked
   against. This one needs neither `ansible-playbook` nor `ansible-galaxy`, so it
   still answers on a machine where nothing else runs.
"""

from __future__ import annotations

import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from toolkit.features import command
from toolkit.features.provision_freshness import (
    REQUIREMENTS,
    FreshnessError,
    collections_off_declaration,
    declared_collections,
)

#: The config file Ansible must be reading when it runs from `infra/ansible`.
CONFIG_FILE = "infra/ansible/ansible.cfg"

#: The inventory CI and `make lint-ansible` use: committed, no SSOT decrypt.
STATIC_INVENTORY = "infra/ansible/inventories/homelab.yml"

#: One entry point installs the controller and ends by running this module.
SETUP_FIX = "make setup-ansible"

#: Where the controller has to run, for the case where installing cannot help.
POSIX_FIX = "run this from WSL or a Linux host; ansible-core has no Windows controller"

#: The version banner is flush left; every line after it is indented two spaces.
_VERSION_LINE = re.compile(r"^ansible-playbook \[core ([^\]]+)\]", re.MULTILINE)
_CONFIG_LINE = re.compile(r"^[ \t]*config file = (.+)$", re.MULTILINE)


@dataclass(frozen=True)
class Check:
    """One diagnosis result. `fix` is empty when nothing is wrong."""

    name: str
    ok: bool
    detail: str
    fix: str = ""


@dataclass(frozen=True)
class Probe:
    """What `ansible-playbook --version` produced, or enough to say why it did not."""

    output: str | None
    located: bool
    error: str


def _probe(ansible_dir: Path) -> Probe:
    """Run `ansible-playbook --version` from the repo without raising.

    `shell=True` means a missing binary is a non-zero exit rather than an
    exception, which is what lets this stay a diagnosis instead of a crash.
    """
    located = shutil.which("ansible-playbook") is not None
    done = command.run(
        "ansible-playbook --version",
        cwd=ansible_dir,
        check=False,
        capture_output=True,
    )
    if done.returncode == 0:
        return Probe(output=done.stdout or "", located=located, error="")
    lines = [line.strip() for line in (done.stderr or done.stdout or "").splitlines() if line.strip()]
    # The traceback's last line is the cause; the first is `Traceback (most recent call last):`.
    return Probe(output=None, located=located, error=lines[-1] if lines else f"exit {done.returncode}")


def _check_ansible_core(probe: Probe) -> Check:
    if probe.output is not None:
        found = _VERSION_LINE.search(probe.output)
        if found is not None:
            return Check(name="ansible-core", ok=True, detail=f"ansible-core {found.group(1)}")
        return Check(
            name="ansible-core",
            ok=False,
            detail="`ansible-playbook --version` answered without a core version line",
            fix=SETUP_FIX,
        )
    if not probe.located:
        return Check(
            name="ansible-core",
            ok=False,
            detail="`ansible-playbook` is not installed, so `toolkit infra ansible run` cannot start a play",
            fix=SETUP_FIX,
        )
    # Installed and still failing. On Windows that is the platform, not the install.
    fix = POSIX_FIX if sys.platform == "win32" else SETUP_FIX
    return Check(
        name="ansible-core",
        ok=False,
        detail=f"`ansible-playbook` is installed but does not run: {probe.error}",
        fix=fix,
    )


def _check_collections(root: Path, core: Check) -> Check:
    if not core.ok:
        return Check(
            name="galaxy collections",
            ok=False,
            detail=f"cannot be read without a working `ansible-galaxy`; {REQUIREMENTS} is unverified",
            fix=core.fix,
        )
    try:
        declared = declared_collections(root)
        off = collections_off_declaration(declared)
    except FreshnessError as exc:
        return Check(
            name="galaxy collections",
            ok=False,
            detail=str(exc),
            fix=core.fix,
        )
    if off:
        return Check(
            name="galaxy collections",
            ok=False,
            detail=f"not what {REQUIREMENTS} pins: {'; '.join(off)}",
            fix=core.fix,
        )
    return Check(
        name="galaxy collections",
        ok=True,
        detail=f"{len(declared)} collections at the pinned versions",
    )


def _check_config_file(ansible_dir: Path, core: Check, probe: Probe) -> Check:
    expected = (ansible_dir / "ansible.cfg").resolve()
    if probe.output is None:
        return Check(
            name="ansible.cfg",
            ok=False,
            detail="cannot be read without a working `ansible-playbook`",
            fix=core.fix,
        )
    found = _CONFIG_LINE.search(probe.output)
    # `config file = None` is what Ansible prints when it found nothing, and the
    # default is the one that reports success having matched no host.
    in_effect = Path(found.group(1).strip()).resolve() if found else None
    if in_effect != expected:
        return Check(
            name="ansible.cfg",
            ok=False,
            detail=(
                f"{CONFIG_FILE} is not in effect (Ansible reads {in_effect or 'nothing'}); "
                "host_pattern_mismatch would be a warning and a run against the wrong inventory would exit 0"
            ),
            fix=f"run from infra/ansible, or restore {CONFIG_FILE}",
        )
    return Check(name="ansible.cfg", ok=True, detail=f"{CONFIG_FILE} is in effect")


def _count_hosts(node: object) -> int:
    """Hosts in one inventory group, counting the children Ansible walks."""
    if not isinstance(node, dict):
        return 0
    total = len(node.get("hosts") or {})
    for child in (node.get("children") or {}).values():
        total += _count_hosts(child)
    return total


def _check_inventory(root: Path) -> Check:
    path = root / STATIC_INVENTORY
    if not path.exists():
        return Check(name="static inventory", ok=False, detail=f"{STATIC_INVENTORY} is missing", fix="restore it")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return Check(
            name="static inventory",
            ok=False,
            detail=f"{STATIC_INVENTORY} is not YAML: {exc}",
            fix="fix the file",
        )
    hosts = _count_hosts(data.get("all") if isinstance(data, dict) else None)
    if hosts == 0:
        return Check(
            name="static inventory",
            ok=False,
            detail=f"{STATIC_INVENTORY} parses but declares no host",
            fix="restore the host list",
        )
    return Check(name="static inventory", ok=True, detail=f"{hosts} hosts under `all`")


def diagnose(root: Path) -> list[Check]:
    """Every check, in the order a fix would be applied. Offline; no host contact."""
    ansible_dir = root / "infra" / "ansible"
    probe = _probe(ansible_dir)
    core = _check_ansible_core(probe)
    return [
        core,
        _check_collections(root, core),
        _check_config_file(ansible_dir, core, probe),
        _check_inventory(root),
    ]
