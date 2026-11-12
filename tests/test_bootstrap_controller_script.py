"""Guards for `scripts/bootstrap-controller.sh`.

The script installs the tools that `make` cannot install, because `make` is one
of them: GNU make and Poetry, then it hands off to `make setup-ansible` for the
venv, the collection pins and the doctor. A bootstrap script is the one file in
a repo that is allowed to duplicate a version, since it has to run before the
lockfile can be read — so what these tests protect is that the duplication stays
honest:

- the Poetry pin still satisfies `poetry.lock`, and the Python floor still
  matches `pyproject.toml`, so the copy cannot drift from the SSOT it mirrors;
- `--check` really reports and installs nothing, since that is the mode the
  runbook tells a cautious operator to run first;
- the Windows guard fires, because that shell is the failure this whole ticket
  exists to name, and a guard that never runs is a comment.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts/bootstrap-controller.sh"
RUNBOOK = REPO / "docs/runbooks/ansible-controller.md"


def _pin(name: str) -> str:
    """Read a `NAME="value"` constant out of the script."""
    match = re.search(rf'^{name}="([^"]+)"$', SCRIPT.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, f"{name} is not declared in scripts/bootstrap-controller.sh"
    return match.group(1)


def _major_minor(version: str) -> tuple[int, int]:
    parts = version.split(".")
    return int(parts[0]), int(parts[1])


def test_poetry_pin_satisfies_the_lockfile():
    """`poetry.lock` records `lock-version = "2.1"`, which only Poetry >= 2.1 can
    read. Pinning below it would install a Poetry that refuses the repo's own
    lock — the seat would then disagree with the runner about the dependency
    graph, which is the class of defect TOOL-131 exists to remove."""
    lock = (REPO / "poetry.lock").read_text(encoding="utf-8")
    lock_version = re.search(r'^lock-version = "([\d.]+)"$', lock, re.MULTILINE)
    assert lock_version, "poetry.lock declares no lock-version"

    pinned = _pin("POETRY_VERSION")
    assert _major_minor(pinned) >= _major_minor(lock_version.group(1)), (
        f"bootstrap-controller.sh pins Poetry {pinned}, but poetry.lock needs >= {lock_version.group(1)}"
    )


def test_python_floor_matches_pyproject():
    """The script carries `PYTHON_MIN` as a copy of `python = "^3.12"` because it
    runs before anything can parse pyproject. The copy is only defensible if
    something fails when the two disagree — this is that something."""
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r'^python = "\^([\d.]+)"$', pyproject, re.MULTILINE)
    assert declared, "pyproject.toml declares no python constraint"

    assert _pin("PYTHON_MIN") == declared.group(1), (
        f"bootstrap-controller.sh requires Python {_pin('PYTHON_MIN')}, but "
        f"pyproject.toml requires ^{declared.group(1)}"
    )


def test_the_script_fails_fast():
    """`set -euo pipefail` is what makes a failed `apt-get` stop the script
    instead of letting it report success and hand off to a broken `make`."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert re.search(r"^set -euo pipefail$", text, re.MULTILINE)


def test_the_script_has_no_carriage_returns():
    """A `.sh` authored on Windows arrives with CRLF, and `.gitattributes` only
    normalises it on the way into git — the working-tree copy stays broken. bash
    then reads `set -euo pipefail\\r` as `set: pipefail` followed by
    `$'\\r': command not found`, so the script dies on line 15 before any check.

    Asserted on the bytes, not through `read_text`, because universal newlines
    silently translate the CR away and the failure disappears from the test.
    """
    assert b"\r" not in SCRIPT.read_bytes(), "scripts/bootstrap-controller.sh has CRLF line endings"


def test_the_runbook_points_at_the_script():
    """A manual recipe in the runbook and a script in `scripts/` are two sources
    of truth for the same install. The runbook must send the operator to the
    script, and the script is where the steps change."""
    assert "scripts/bootstrap-controller.sh" in RUNBOOK.read_text(encoding="utf-8")


_needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="the script is bash")
# These two assert behaviour of a POSIX host: on Windows the script refuses at
# the uname guard before reaching either path, which is its own test below.
_posix = pytest.mark.skipif(sys.platform == "win32", reason="asserts the POSIX path; Windows stops at the uname guard")


def _run(*args: str, path_prefix: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = None
    if path_prefix is not None:
        env = dict(os.environ)
        env["PATH"] = f"{path_prefix}:{env['PATH']}"
        # The script prepends ~/.local/bin to PATH whenever a poetry is there, so a
        # developer seat that installed Poetry that way shadows the stub and the
        # test asserts the seat's Poetry instead of the fake one. A stub PATH means
        # a stub HOME too.
        env["HOME"] = tempfile.mkdtemp(prefix="bootstrap-home-")
    # Relative path with cwd set to the repo: the `bash` on PATH may be WSL's,
    # which does not translate a Windows path and silently strips its
    # backslashes into a name that does not exist.
    return subprocess.run(  # noqa: S603 - fixed argv, repo-local script
        ["bash", "scripts/bootstrap-controller.sh", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=120,
        check=False,
    )


@_needs_bash
def test_help_exits_zero():
    result = _run("--help")
    assert result.returncode == 0
    assert "Usage:" in result.stdout


@_needs_bash
def test_an_unknown_argument_is_rejected():
    result = _run("--force")
    assert result.returncode == 2
    assert "unknown argument" in result.stderr


@_needs_bash
@_posix
def test_check_mode_reports_and_installs_nothing():
    """The runbook's first step is `--check`, so the mode has to be a real dry
    run. It is asserted by its own marker and by the absence of any install
    line, not by the exit status: that status legitimately differs between a
    machine that can be a controller and one that cannot."""
    result = _run("--check")
    combined = result.stdout + result.stderr
    assert "--check: installs nothing" in combined
    assert "installing " not in combined
    assert result.returncode in (0, 1)


def test_check_mode_asks_the_doctor_instead_of_assuming():
    """`--check` used to answer the ansible question from `command -v` alone, so
    a host with python3, make and poetry and no ansible-core reached FAILED=0
    and was told it could be a controller. The authority on that question is the
    doctor, so the mode has to run it — and has to be able to fail on what it
    says."""
    lines = SCRIPT.read_text(encoding="utf-8").splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip() == "if make check-ansible; then"), None)
    assert start is not None, (
        "--check no longer runs the doctor, so the only remaining evidence about "
        "ansible-core is the presence of its prerequisites"
    )
    block = [ln.strip() for ln in lines[start + 1 : start + 6]]
    assert any(ln.startswith("ok ") for ln in block), "the doctor's pass is not reported"
    assert any(ln.startswith("bad ") for ln in block), (
        "--check runs the doctor but cannot fail on its verdict, which is the same false green one level down"
    )


def _stub(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
    path.chmod(0o755)


@_needs_bash
@_posix
def test_check_mode_refuses_a_host_without_ansible(tmp_path: Path):
    """The case the red-team built: python3, GNU make and Poetry all present,
    ansible-core absent. Every `command -v` the script consults says yes, so the
    old `--check` printed the success verdict and exited 0 — on a host that
    cannot run a single play."""
    stub = tmp_path / "bin"
    stub.mkdir()
    _stub(stub, "python3", 'echo "3.12.3"\nexit 0\n')
    _stub(
        stub,
        "make",
        'case "$1" in\n  --version) echo "GNU Make 4.3" ;;\n'
        '  check-ansible) echo "  [FAIL] ansible-core is not importable from the venv" >&2; exit 1 ;;\n'
        "  *) exit 2 ;;\nesac\n",
    )
    _stub(
        stub,
        "poetry",
        'case "$1" in\n  --version) echo "Poetry (version 2.5.1)" ;;\n  run) exit 0 ;;\n  *) exit 2 ;;\nesac\n',
    )

    result = _run("--check", path_prefix=stub)
    combined = result.stdout + result.stderr
    assert result.returncode == 1, combined
    assert "the doctor refused this machine" in combined
    assert "can be a controller" not in combined, "a host whose doctor refused was still told it can be a controller"


# --------------------------------------------------- the install path itself --

# This script exists for one machine: the one that does not yet have make and
# Poetry. Every test above exercises a machine that already has them, which is
# the only machine that never needed the script — and that is how the defect
# below survived. Reaching the install path means controlling PATH completely, so
# the stub directory holds the fakes and a second directory holds symlinks to the
# coreutils the script shells out to, with `make` and `poetry` absent from both.

# `true` is in the list because `can_root` asks `sudo -n true`: the stub sudo
# execs its arguments, and with PATH replaced wholesale the real `true` is not
# reachable, so a missing entry here reads as "no root" and skips the install.
_COREUTILS = ("sed", "id", "uname", "dirname", "env", "mkdir", "chmod", "cat", "rm", "basename", "tr", "grep", "true")

# Creates a GNU make when asked to install one, the way the real apt-get would.
# The hand-off target is reported on stdout so a test can see it ran.
_APT_GET_INSTALLS_MAKE = """
case "$1" in
  install)
    printf '#!/bin/sh\\n' > "STUBDIR/make"
    printf 'case "$1" in --version) echo "GNU Make 4.3" ;; *) echo "HANDOFF:$*" ;; esac\\n' >> "STUBDIR/make"
    printf 'exit 0\\n' >> "STUBDIR/make"
    chmod +x "STUBDIR/make"
    ;;
esac
exit 0
"""

# Answers the two `python3 -c` probes the version check makes, and — when it is
# the pipe target of the Poetry installer (`python3 -`) — writes the binary the
# script then looks for in ~/.local/bin.
_PYTHON3_INSTALLS_POETRY = """
case "$1" in
  -)
    mkdir -p "$HOME/.local/bin"
    printf '#!/bin/sh\\necho "Poetry (version 2.5.1)"\\n' > "$HOME/.local/bin/poetry"
    chmod +x "$HOME/.local/bin/poetry"
    cat >/dev/null
    ;;
  *) echo "3.12.3" ;;
esac
exit 0
"""

_SUDO_ACCEPTS_DASH_N = 'shift\nexec "$@"\n'

# The measured behaviour of a host whose sudo has no cached credential: `-n`
# fails instead of prompting. A bare `sudo` would then block on /dev/tty.
_SUDO_WANTS_A_PASSWORD = """
case "$1" in
  -n) echo "sudo: a password is required" >&2; exit 1 ;;
  *) exec "$@" ;;
esac
"""

# `can_root` asks `id -u` BEFORE it consults sudo, so a sudo stub alone cannot
# decide the privileged path: the runner's own UID does. Anything other than 0
# is delegated to the real binary, which is only ever asked that one question.
_ID_REPORTS_UID = """
case "$1" in
  -u) echo "REPORTED_UID" ;;
  *) exec "REALDIR/id" "$@" ;;
esac
"""


def _isolated_host(
    tmp_path: Path, *, root_available: bool, poetry: bool = False, is_root: bool = False
) -> tuple[Path, Path]:
    """A PATH holding nothing this script is looking for, plus the stubs it needs
    to observe its own behaviour: no make, and an apt-get that would install one.

    `poetry=True` reproduces the state the official installer leaves behind —
    the binary in `~/.local/bin`, which the script prepends to PATH itself — so a
    test can isolate one missing prerequisite from two.

    `is_root=True` answers `id -u` with 0. Combined with `root_available=False` it
    is the state that matters most and that the suite could not reach before: a
    real root shell, where sudo is never needed and the sudo stub would fail."""
    stub = tmp_path / "bin"
    stub.mkdir()
    real = tmp_path / "real"
    real.mkdir()
    for name in _COREUTILS:
        source = shutil.which(name)
        assert source, f"these tests shell out to {name}"
        (real / name).symlink_to(source)

    home = tmp_path / "home"
    home.mkdir()
    if poetry:
        (home / ".local" / "bin").mkdir(parents=True)
        _stub(home / ".local" / "bin", "poetry", 'echo "Poetry (version 2.5.1)"\nexit 0\n')

    _stub(stub, "python3", _PYTHON3_INSTALLS_POETRY)
    _stub(stub, "apt-get", _APT_GET_INSTALLS_MAKE.replace("STUBDIR", str(stub)))
    _stub(stub, "curl", "exit 0\n")
    _stub(stub, "sudo", _SUDO_ACCEPTS_DASH_N if root_available else _SUDO_WANTS_A_PASSWORD)
    _stub(stub, "id", _ID_REPORTS_UID.replace("REPORTED_UID", "0" if is_root else "1000").replace("REALDIR", str(real)))
    return stub, home


def _run_isolated(stub: Path, home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """`bash` is invoked by absolute path: PATH is replaced wholesale, so the
    interpreter would not otherwise resolve."""
    bash = shutil.which("bash")
    assert bash, "the script is bash"
    env = dict(os.environ)
    env["PATH"] = f"{stub}:{stub.parent / 'real'}"
    env["HOME"] = str(home)
    return subprocess.run(  # noqa: S603 - fixed argv, repo-local script
        [bash, "scripts/bootstrap-controller.sh", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=120,
        check=False,
    )


@_needs_bash
@_posix
def test_install_path_hands_off_after_installing(tmp_path: Path):
    """The defect: `bad` increments FAILED and `ok` does not decrement it, so the
    hand-off sees the number of things that were missing at the start. On a stock
    WSL image that is 2 — make and Poetry — and the script installs both, reports
    `[ok]` for both, and then exits 1 without ever running `make setup-ansible`.
    The verdict has to describe the machine after the attempt, not before it."""
    stub, home = _isolated_host(tmp_path, root_available=True)

    result = _run_isolated(stub, home)
    combined = result.stdout + result.stderr

    assert "GNU Make 4.3" in combined, (
        "the fake install did not produce a make; the test is not exercising the install path"
    )
    assert "HANDOFF:setup-ansible" in combined, (
        "the script installed what it reported missing and then refused to hand off to make:\n" + combined
    )
    assert result.returncode == 0, combined
    assert "unresolved" not in combined, combined


@_needs_bash
@_posix
def test_install_path_still_refuses_when_an_install_fails(tmp_path: Path):
    """The other half of the same verdict: an install that does not take must
    still block the hand-off. Removing the counter without this would turn the
    script into one that always hands off."""
    stub, home = _isolated_host(tmp_path, root_available=True)
    # apt-get that reports success and installs nothing.
    _stub(stub, "apt-get", "exit 0\n")

    result = _run_isolated(stub, home)
    combined = result.stdout + result.stderr

    assert result.returncode == 1, combined
    assert "HANDOFF:setup-ansible" not in combined, "the hand-off ran although make was never installed"
    assert "unresolved" in combined, combined


@_needs_bash
@_posix
def test_check_mode_reports_a_passworded_sudo(tmp_path: Path):
    """`--check` promised an install it could not perform: on a host whose sudo
    wants a password it printed `would install: make` and exited 0, and the run
    that followed blocked on /dev/tty with no output. The privilege question is
    part of whether this machine can be a controller, so the dry run has to
    answer it."""
    stub, home = _isolated_host(tmp_path, root_available=False)

    result = _run_isolated(stub, home, "--check")
    combined = result.stdout + result.stderr

    assert result.returncode == 1, combined
    assert "root is not available without a password" in combined, combined
    assert "sudo -v" in combined, "the report names the problem but not the repair"
    assert "installing " not in combined, "--check installed something"


@_needs_bash
@_posix
def test_check_mode_counts_one_missing_prerequisite_as_one_failure(tmp_path: Path):
    """A missing make and the root it would take to install it are one verdict,
    not two. Counting both made the summary read `2 check(s) failed` for a
    machine with exactly one thing wrong, and the count is what the operator
    triages against."""
    stub, home = _isolated_host(tmp_path, root_available=False, poetry=True)

    result = _run_isolated(stub, home, "--check")
    combined = result.stdout + result.stderr

    assert result.returncode == 1, combined
    assert "[ERROR] 1 check(s) failed" in combined, combined
    assert "[FAIL] GNU make is missing" in combined, combined
    # Root still has to be reported — it is why the install cannot happen — but as
    # a note about the attempt, not as a second thing wrong with the machine.
    assert "root is not available without a password" in combined, combined
    assert "[FAIL] root" not in combined, combined


@_needs_bash
@_posix
def test_install_mode_does_not_attempt_apt_without_root(tmp_path: Path):
    """Not blocking is not the same as proceeding: with no passwordless root the
    install must not be attempted at all, or the failure arrives as an apt error
    that reads like a broken repository."""
    stub, home = _isolated_host(tmp_path, root_available=False)

    result = _run_isolated(stub, home)
    combined = result.stdout + result.stderr

    assert result.returncode == 1, combined
    assert "root is not available without a password" in combined, combined
    assert "GNU Make 4.3" not in combined, "apt-get ran without root"
    assert "HANDOFF:setup-ansible" not in combined


@_needs_bash
@_posix
def test_install_path_runs_as_root_without_sudo(tmp_path: Path):
    """The other privileged path, and the one the suite could not reach before:
    on a host that really is root, `as_root` runs the command itself and never
    asks sudo. It is exercised with root_available=False on purpose — that stub
    fails every `-n`, so a single sudo call would turn this red."""
    stub, home = _isolated_host(tmp_path, root_available=False, is_root=True)

    result = _run_isolated(stub, home)
    combined = result.stdout + result.stderr

    assert result.returncode == 0, combined
    assert "root is not available without a password" not in combined, combined
    assert "HANDOFF:setup-ansible" in combined, combined


def _code_only(path: Path) -> str:
    """The script's executable lines, without comment lines.

    Asserted against these rather than the raw text so a comment that quotes the
    rejected form — which is how the reason for the rejection survives — does not
    read as an occurrence of it.
    """
    return "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#")
    )


def test_as_root_never_invokes_sudo_without_dash_n():
    """`sudo` reads its password from /dev/tty, not stdin, so without `-n` a
    non-interactive run does not fail — it waits, silently and indefinitely
    (measured: PID alive at 123 s). No invocation in this script may prompt."""
    text = _code_only(SCRIPT)
    assert 'sudo "$@"' not in text, "as_root invokes sudo without -n, which blocks on /dev/tty"
    assert re.search(r'sudo -n "\$@"', text), "as_root must invoke sudo with -n"


def test_apt_update_is_not_quiet_quiet():
    """`apt-get update -qq` was measured returning 0 while printing "Could not
    open lock file … Permission denied", so the quiet flag hid the one failure a
    bootstrap script must not hide. The install that follows is the real gate,
    but a gate that only ever reports "still not GNU make" names the symptom."""
    text = _code_only(SCRIPT)
    assert re.search(r"apt-get update\b", text), "the script no longer refreshes the package index"
    assert "apt-get update -qq" not in text, "-qq hides a permission or lock failure behind exit 0"


@_needs_bash
@_posix
def test_a_windows_shell_is_refused_before_anything_runs(tmp_path: Path):
    """The msi's Git Bash reaches ansible-core's `os.get_blocking()` and gets
    OSError [WinError 87]. The guard names that instead of letting it surface as
    a broken install, so it must run before the first check and before any
    `apt-get` — a refusal that installs first is not a refusal."""
    stub = tmp_path / "bin"
    stub.mkdir()
    uname = stub / "uname"
    uname.write_text("#!/bin/sh\necho MINGW64_NT-10.0\n", encoding="utf-8")
    uname.chmod(0o755)

    result = _run("--check", path_prefix=stub)
    assert result.returncode == 1
    assert "no Windows controller" in result.stderr
    assert "python3" not in result.stdout
