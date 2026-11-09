"""Guards for `toolkit infra ansible doctor` (TOOL-131, #3202).

The bug this ticket exists for is a fail-open: `make setup-ansible` printed
`skipping` and exited 0 when `ansible-galaxy` was absent, while
`collections_refusal_message()` told the operator to run exactly that target.
A check that cannot fail is not a check, so these tests are written the same
way the doctor is: every one of them fails if the corresponding diagnosis
stops being able to say no.

`ansible-playbook` itself is never executed here — it is POSIX-only and the
suite runs on both platforms. What is reproduced is its OUTPUT, which is the
whole contract the doctor reads.
"""

from __future__ import annotations

import ast
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from toolkit.features import ansible_doctor as doctor

REPO = Path(__file__).resolve().parent.parent
ANSIBLE_DIR = REPO / "infra/ansible"
CONFIG = ANSIBLE_DIR / "ansible.cfg"

#: Real `ansible-playbook --version` output, trimmed to the lines that matter.
#: Note the two-space indent: the banner is flush left and everything after it
#: is not. A regex that anchors `^config file` on the flush-left form matches
#: nothing and reports "Ansible reads nothing" with the file perfectly in place.
BANNER = """ansible-playbook [core 2.21.6]
  config file = {config}
  configured module search path = ['/home/x/.ansible/plugins/modules']
  python version = 3.12.3
"""

WINERROR = """Traceback (most recent call last):
  File "ansible/cli/__init__.py", line 54, in <module>
    check_blocking_io()
  File "ansible/cli/__init__.py", line 46, in check_blocking_io
    if not os.get_blocking(fd):
OSError: [WinError 87] The parameter is incorrect"""


def _banner(config: Path | str = CONFIG) -> str:
    return BANNER.format(config=config)


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _spawned() -> list[list[str]]:
    """Every argv this module hands to a spawner, read from the AST.

    A substring search over the source cannot tell a command from a comment, a
    docstring or a test fixture name, and this module explains itself at length:
    the previous version of `test_the_doctor_never_shells_out_to_a_remote`
    asserted `"become" not in source` while the module never spawned anything,
    so it passed for the wrong reason and would have failed on prose.
    """
    tree = ast.parse(Path(doctor.__file__).read_text(encoding="utf-8"))
    argvs: list[list[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        owner = getattr(func, "value", None)
        if not isinstance(func, ast.Attribute) or not isinstance(owner, ast.Name):
            continue
        if owner.id not in {"command", "subprocess"}:
            continue
        literal = node.args[0]
        if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
            argvs.append(shlex.split(literal.value))
        elif isinstance(literal, (ast.List, ast.Tuple)):
            argvs.append([elt.value for elt in literal.elts if isinstance(elt, ast.Constant)])
        else:
            argvs.append(["<not a literal>"])
    return argvs


def _core(ok: bool = True, fix: str = "") -> doctor.Check:
    return doctor.Check(name="ansible-core", ok=ok, detail="", fix=fix)


# --- check 1: the binary resolves and runs ---------------------------------


def test_a_working_binary_reports_its_version(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/bin/ansible-playbook")
    monkeypatch.setattr(doctor.command, "run", lambda *a, **k: _completed(stdout=_banner()))
    probe = doctor._probe(ANSIBLE_DIR)
    check = doctor._check_ansible_core(probe)
    assert check.ok
    assert "2.21.6" in check.detail


def test_a_missing_binary_is_a_diagnosis_and_not_a_crash(monkeypatch):
    """`shell=True` turns a missing binary into exit 127 rather than
    FileNotFoundError, which is what lets the doctor keep going instead of
    dying on the first check and reporting nothing about the other three."""
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        doctor.command,
        "run",
        lambda *a, **k: _completed(returncode=127, stderr="ansible-playbook: not recognized"),
    )
    check = doctor._check_ansible_core(doctor._probe(ANSIBLE_DIR))
    assert not check.ok
    assert "not installed" in check.detail
    assert check.fix == doctor.SETUP_FIX


def test_windows_gets_the_posix_fix_not_the_install_fix(monkeypatch):
    """Measured on ansible-core 2.21.6: every CLI entry point calls
    `check_blocking_io()` at import and raises WinError 87. Telling someone to
    `make setup-ansible` there sends them to reinstall a package that will fail
    the same way, so the two failures must not share a fix line."""
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/bin/ansible-playbook")
    monkeypatch.setattr(doctor.command, "run", lambda *a, **k: _completed(returncode=1, stderr=WINERROR))
    monkeypatch.setattr(sys, "platform", "win32")
    check = doctor._check_ansible_core(doctor._probe(ANSIBLE_DIR))
    assert not check.ok
    assert check.fix == doctor.POSIX_FIX


def test_the_same_failure_on_linux_is_an_install_problem(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/bin/ansible-playbook")
    monkeypatch.setattr(doctor.command, "run", lambda *a, **k: _completed(returncode=1, stderr=WINERROR))
    monkeypatch.setattr(sys, "platform", "linux")
    check = doctor._check_ansible_core(doctor._probe(ANSIBLE_DIR))
    assert not check.ok
    assert check.fix == doctor.SETUP_FIX


def test_the_cause_is_reported_rather_than_the_traceback_header(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/bin/ansible-playbook")
    monkeypatch.setattr(doctor.command, "run", lambda *a, **k: _completed(returncode=1, stderr=WINERROR))
    check = doctor._check_ansible_core(doctor._probe(ANSIBLE_DIR))
    assert "WinError 87" in check.detail
    assert "Traceback" not in check.detail


# --- check 3: the config file actually in effect ---------------------------


def test_the_indented_config_line_is_parsed():
    """Regression: the first version anchored `^config file = ` flush left and
    matched nothing, so a fully working WSL controller reported "Ansible reads
    nothing". Verified against real `ansible-playbook --version` output, whose
    lines after the banner are indented two spaces."""
    check = doctor._check_config_file(ANSIBLE_DIR, _core(), doctor.Probe(output=_banner(), located=True, error=""))
    assert check.ok, check.detail


def test_ansible_reading_no_config_fails():
    """`config file = None` is what Ansible prints when it found nothing, and
    the built-in default turns a host-pattern mismatch into a warning — a run
    against the wrong inventory then exits 0 having touched nothing."""
    check = doctor._check_config_file(
        ANSIBLE_DIR, _core(), doctor.Probe(output=_banner("None"), located=True, error="")
    )
    assert not check.ok
    assert "not in effect" in check.detail


def test_the_word_none_is_not_a_path():
    """`None` is a word in this banner, not an absence: `Path("None").resolve()`
    is a perfectly real path, so the operator was told Ansible reads a config
    file called `None` in whatever directory the doctor happened to run from."""
    check = doctor._check_config_file(
        ANSIBLE_DIR, _core(), doctor.Probe(output=_banner("None"), located=True, error="")
    )
    assert "reads nothing" in check.detail
    assert "None" not in check.detail.split("reads nothing")[0]


def test_a_relative_config_path_is_resolved_against_the_ansible_dir(tmp_path):
    """Ansible can print the path it was given rather than the absolute one, so
    resolving against the doctor's own cwd would report a file that is not the
    one in effect — and the check would fail on a healthy controller."""
    ansible_dir = tmp_path / "infra/ansible"
    ansible_dir.mkdir(parents=True)
    (ansible_dir / "ansible.cfg").write_text("[defaults]\n", encoding="utf-8")
    check = doctor._check_config_file(
        ansible_dir, _core(), doctor.Probe(output=_banner("ansible.cfg"), located=True, error="")
    )
    assert check.ok, check.detail


def test_somebody_elses_config_fails(tmp_path):
    """The property is not "a config file exists" but "it is THIS repo's"."""
    other = tmp_path / "ansible.cfg"
    other.write_text("[defaults]\n", encoding="utf-8")
    check = doctor._check_config_file(ANSIBLE_DIR, _core(), doctor.Probe(output=_banner(other), located=True, error=""))
    assert not check.ok
    assert str(other) in check.detail


def test_the_config_check_defers_when_ansible_cannot_run():
    """No invented answer: with no working binary there is nothing to ask."""
    check = doctor._check_config_file(
        ANSIBLE_DIR, _core(ok=False, fix=doctor.POSIX_FIX), doctor.Probe(output=None, located=True, error="boom")
    )
    assert not check.ok
    assert check.fix == doctor.POSIX_FIX
    assert "cannot be read" in check.detail


# --- check 2: collections --------------------------------------------------


def test_collections_are_not_claimed_verified_without_a_working_core():
    """The pins are exact on purpose (ANSIBLE-070). Saying "collections OK"
    from a machine that cannot query them is the fail-open this replaces."""
    check = doctor._check_collections(REPO, _core(ok=False, fix=doctor.POSIX_FIX))
    assert not check.ok
    assert check.fix == doctor.POSIX_FIX
    assert "unverified" in check.detail


def test_a_collection_off_the_pin_fails(monkeypatch):
    monkeypatch.setattr(doctor, "declared_collections", lambda _root: {"community.docker": "5.4.0"})
    monkeypatch.setattr(doctor, "collections_off_declaration", lambda _declared: ["community.docker 5.3.9 != 5.4.0"])
    check = doctor._check_collections(REPO, _core())
    assert not check.ok
    assert "community.docker 5.3.9" in check.detail
    # A failed check with no FIX line is a diagnosis that stops at the symptom,
    # and `core.fix` is empty exactly when core passed -- which is this case.
    assert doctor.SETUP_FIX in check.fix


def test_an_unreadable_declaration_fails_instead_of_raising(monkeypatch):
    def explode(_root):
        raise doctor.DeclarationError("infra/ansible/requirements.yml: No such file")

    monkeypatch.setattr(doctor, "declared_collections", explode)
    check = doctor._check_collections(REPO, _core())
    assert not check.ok
    assert "No such file" in check.detail
    # The fix names the file, not `make setup-ansible`: reinstalling does not
    # make an unreadable declaration readable.
    assert check.fix == doctor.DECLARATION_FIX
    assert doctor.REQUIREMENTS in check.fix


def test_any_other_freshness_error_from_the_declaration_read_still_fails(monkeypatch):
    """The declaration read raises only its subclass, so this is the defensive branch:
    it exists so a new raise path cannot turn the check back into a traceback."""

    def explode(_root):
        raise doctor.FreshnessError("something the split does not know about")

    monkeypatch.setattr(doctor, "declared_collections", explode)
    check = doctor._check_collections(REPO, _core())
    assert not check.ok
    assert "does not know about" in check.detail
    assert doctor.COLLECTIONS_LISTING_FIX in check.fix


def test_a_galaxy_listing_it_cannot_read_is_a_failed_check_not_a_traceback(monkeypatch):
    """Core passing does not imply the listing is readable: `ansible-galaxy` can be
    absent or answer with something that is not the JSON the parse expects."""

    def explode(_declared):
        raise doctor.FreshnessError("ansible-galaxy collection list is not JSON")

    monkeypatch.setattr(doctor, "collections_off_declaration", explode)
    check = doctor._check_collections(REPO, _core())
    assert not check.ok
    assert "not JSON" in check.detail
    # Nothing was compared, so the repair is the listing, not a reinstall.
    assert "collection list" in check.fix
    assert check.fix != doctor.COLLECTIONS_FIX


def test_the_doctor_and_the_preflight_prescribe_the_same_repair():
    """Two entry points diagnose the same drift, so they cannot prescribe two
    different commands: whichever one the operator reads has to land them on the
    same fix (TOOL-131 — the doctor's own FIX line named a flag that did not exist)."""
    from toolkit.features import provision_freshness

    assert doctor.COLLECTIONS_FIX is provision_freshness.COLLECTIONS_FIX
    assert doctor.SETUP_FIX in provision_freshness.collections_refusal_message(["x 1.0 (declared 2.0)"])


# --- check 4: the static inventory ----------------------------------------


def test_the_inventory_counts_hosts_under_nested_children(tmp_path):
    """Ansible walks `children` arbitrarily deep and this repo does use two
    levels; counting only the top-level `hosts` would report 0 on a valid file.
    The node passed is `all`, not the document — `_check_inventory` does the
    same, and a test that passes the document instead counts nothing."""
    inventory = tmp_path / "infra/ansible/inventories/homelab.yml"
    inventory.parent.mkdir(parents=True)
    inventory.write_text(
        "all:\n"
        "  hosts:\n"
        "    a: {}\n"
        "  children:\n"
        "    cloud:\n"
        "      hosts:\n"
        "        b: {}\n"
        "      children:\n"
        "        deeper:\n"
        "          hosts:\n"
        "            c: {}\n",
        encoding="utf-8",
    )
    assert doctor._count_hosts({"hosts": {"a": {}}}) == 1
    assert doctor._count_hosts({"children": {"x": {"children": {"y": {"hosts": {"z": {}}}}}}}) == 1
    check = doctor._check_inventory(tmp_path)
    assert check.ok
    assert "3 hosts" in check.detail


def test_an_empty_inventory_fails(tmp_path):
    inventory = tmp_path / "infra/ansible/inventories/homelab.yml"
    inventory.parent.mkdir(parents=True)
    inventory.write_text("all:\n  children: {}\n", encoding="utf-8")
    check = doctor._check_inventory(tmp_path)
    assert not check.ok
    assert "declares no host" in check.detail


def test_an_inventory_that_cannot_be_read_is_a_check_not_a_traceback(tmp_path):
    """A directory in the file's place, a permission bit, a broken symlink: none
    of them raise `YAMLError`, so the guard has to be wider than the parser.
    `diagnose()` promises four checks, not an exception."""
    inventory = tmp_path / "infra/ansible/inventories/homelab.yml"
    inventory.mkdir(parents=True)
    check = doctor._check_inventory(tmp_path)
    assert not check.ok
    assert "cannot be read" in check.detail


# --- the whole diagnosis ---------------------------------------------------


def test_a_healthy_controller_passes_all_four(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/bin/ansible-playbook")
    monkeypatch.setattr(doctor.command, "run", lambda *a, **k: _completed(stdout=_banner()))
    monkeypatch.setattr(doctor, "declared_collections", lambda _root: {"community.docker": "5.4.0"})
    monkeypatch.setattr(doctor, "collections_off_declaration", lambda _declared: [])
    checks = doctor.diagnose(REPO)
    assert [c.name for c in checks] == ["ansible-core", "galaxy collections", "ansible.cfg", "static inventory"]
    assert all(c.ok for c in checks), [c for c in checks if not c.ok]


def test_the_inventory_check_answers_with_nothing_else_working(monkeypatch):
    """It needs neither binary, which is why it still reports on a Windows seat
    and is the one line that is not a POSIX complaint there."""
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: None)
    monkeypatch.setattr(doctor.command, "run", lambda *a, **k: _completed(returncode=127))
    monkeypatch.setattr(sys, "platform", "win32")
    checks = doctor.diagnose(REPO)
    assert [c.ok for c in checks] == [False, False, False, True]


# --- the entry points that must not drift ----------------------------------


def test_setup_ansible_ends_in_the_doctor_and_never_skips():
    """The original defect in one assertion: the target used to branch on
    `command -v ansible-galaxy` and print `skipping` on the else path, exiting 0.
    A target that can silently do nothing cannot be the FIX line that
    `collections_refusal_message()` prints."""
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    body = makefile[makefile.index("\nsetup-ansible:") :]
    body = body[: body.index("\n.PHONY:", 1)]
    assert "infra ansible doctor" in body, "setup-ansible no longer ends in the check that can fail"
    assert "skipping" not in body
    assert "--with ansible" in body, "ansible-core must land in this project's venv, not a system one"


@pytest.mark.parametrize("target", ["provision", "deploy"])
def test_the_ansible_entry_points_run_the_doctor_first(target):
    """The gate belongs in front of the two targets that shell out to
    ansible-playbook, not only in the target a human is expected to remember.
    `make setup-ansible` teaches; `make provision` has to enforce."""
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    header = next(ln for ln in makefile.splitlines() if ln.startswith(f"{target}:"))
    assert "check-ansible" in header.split(":", 1)[1], (
        f"`make {target}` no longer depends on check-ansible, so a seat that "
        "cannot run ansible-playbook fails deep inside a play instead"
    )


def test_the_doctor_is_reachable_from_the_cli():
    """`make setup-ansible` calls it through `$(TOOLKIT)`, so the command has to
    be registered under `infra ansible` or the target fails on an unknown name."""
    from toolkit.cli import infra

    assert "doctor" in {c.name for c in infra.ansible_app.registered_commands}


def test_the_flag_the_checkout_fix_names_is_one_the_command_accepts(tmp_path):
    """The FIX line says `toolkit infra ansible doctor --root <path>`, and for a
    while there was no `--root`: the repair named a command line Typer rejected
    with "No such option", which is a dead end dressed as a fix. Invoke it rather
    than read the signature — the flag is real only if the parser accepts it."""
    from typer.testing import CliRunner

    from toolkit.cli import infra

    result = CliRunner().invoke(infra.app, ["ansible", "doctor", "--root", str(tmp_path)])
    assert "No such option" not in result.output
    assert result.exit_code == 1, "a root that is not a checkout cannot pass"
    assert "checkout:" in result.output


def test_the_doctor_only_spawns_the_local_version_probe():
    """It runs before a host window is agreed, so it must not be able to reach a
    node: the only command it may start is the local version probe.

    Read from the AST rather than from the source text. A substring assertion
    cannot fail for the right reason: it is satisfied by a comment, and it
    rejects the word `become` in a sentence explaining why there is no `become`.
    """
    assert _spawned() == [["ansible-playbook", "--version"]]


@pytest.mark.parametrize(
    "name",
    ["SETUP_FIX", "POSIX_FIX", "COLLECTIONS_FIX", "COLLECTIONS_LISTING_FIX"],
)
def test_every_fix_line_is_actionable(name):
    """A fix that says "install ansible" to a Windows seat is worse than none:
    it is a loop. Every line names a command or a platform, never a wish.

    The two collection lines are parametrised here as well as shared with the
    preflight: sharing the constant keeps the two messages identical, and this
    keeps the shared text honest."""
    fix = getattr(doctor, name)
    assert fix
    assert any(token in fix for token in ("make ", "run this from", "WSL", "Linux"))


# --- the precondition: a root that is not a checkout -----------------------


def test_a_root_that_is_not_a_checkout_is_named_and_not_crashed(tmp_path):
    """`_probe` hands `cwd=<root>/infra/ansible` to subprocess, and `cwd` is
    resolved before the shell starts. On a root without one, subprocess raises
    `NotADirectoryError` (POSIX: `FileNotFoundError`) and the doctor -- the one
    command whose whole job is to answer instead of raising -- became a
    traceback naming a path the operator never typed."""
    checks = doctor.diagnose(tmp_path)

    assert [c.name for c in checks] == ["checkout"], "every later check reads through this one"
    assert not checks[0].ok
    assert str(tmp_path) in checks[0].detail
    assert "infra/ansible" in checks[0].detail
    assert "doctor --root" in checks[0].fix, "a fix that does not name the flag is a wish"


def test_the_probe_answers_a_missing_directory_instead_of_raising(tmp_path):
    """The guard has to hold at `_probe` too, not only behind `diagnose`'s early
    return: `_probe` is the function that passes the `cwd`, so it is the one that
    owns the precondition."""
    probe = doctor._probe(tmp_path / "infra" / "ansible")

    assert probe.output is None
    assert "is not a directory" in probe.error
    assert probe.located in (True, False), "it still reports whether the binary is on PATH"
