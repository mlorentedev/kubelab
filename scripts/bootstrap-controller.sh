#!/usr/bin/env bash
# Bootstrap an Ansible controller on this machine: GNU make and Poetry, then hand
# off to `make setup-ansible`, which installs ansible-core into the project venv
# and ends in the doctor. Idempotent — anything already correct is left alone.
#
# It exists because the tools below `make` cannot be installed BY `make`: the
# entry point has to be something that already runs. The alternative is a runbook
# of apt-get lines, which is a manual procedure no CI can execute and which drifts
# in silence (Standing Order #1: automate, don't instruct).
#
#   bash scripts/bootstrap-controller.sh --check   # diagnose only, changes nothing
#   bash scripts/bootstrap-controller.sh           # install what is missing
#
# Nothing here contacts a fleet host. See docs/runbooks/ansible-controller.md.

set -euo pipefail

# Pinned to the Poetry that generated poetry.lock (lock-version = "2.1" needs
# Poetry >= 2.1). This script is the SSOT for that pin: nothing else declares it.
# Bumping it means re-checking the lock, so it is a deliberate edit, not a range.
POETRY_VERSION="2.5.1"

# Mirrors `python = "^3.12"` in pyproject.toml. The test suite fails if the two
# disagree, so this is a copy with a guard, not a second declaration.
PYTHON_MIN="3.12"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

FAILED=0
CHECK_ONLY=0

ok()   { printf '  [ok]   %s\n' "$*"; }
bad()  { printf '  [FAIL] %s\n' "$*"; FAILED=$((FAILED + 1)); }
note() { printf '         %s\n' "$*"; }
step() { printf '\n%s\n' "$*"; }

usage() {
  cat <<'EOF'
Usage: bash scripts/bootstrap-controller.sh [--check]

  (no argument)  install whatever is missing, then run `make setup-ansible`
  --check        report only; installs nothing, exits 1 if the machine cannot
                 be a controller
  --help, -h     this text

Safe to re-run: a machine that is already correct is left untouched.
EOF
}

case "${1:-}" in
  --check) CHECK_ONLY=1 ;;
  --help|-h) usage; exit 0 ;;
  "") ;;
  *) printf '[ERROR] unknown argument: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
esac
if [ "$#" -gt 1 ]; then
  printf '[ERROR] expected at most one argument\n' >&2
  exit 2
fi

# A Windows shell reaches the same wall the doctor reports: ansible-core calls
# os.get_blocking() at import and gets OSError [WinError 87] there. Say so here
# rather than letting it surface as a broken install three steps later.
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    printf '[ERROR] this is a Windows shell; ansible-core has no Windows controller.\n' >&2
    printf '        os.get_blocking() raises OSError [WinError 87] at import, in all three\n' >&2
    printf '        entry points. Run this from WSL or a Linux host.\n' >&2
    exit 1 ;;
esac

as_root() {
  if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo "$@"; fi
}

# Poetry's installer drops the binary in ~/.local/bin, which is on PATH in most
# interactive shells but not in a non-login one. Prepend it unconditionally when
# the binary is there: the hand-off to `make` runs `poetry` from PATH.
if [ -x "$HOME/.local/bin/poetry" ]; then
  case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) export PATH="$HOME/.local/bin:$PATH" ;;
  esac
fi

# ---------------------------------------------------------------- python3 ----

step "python3 (>= ${PYTHON_MIN}, per pyproject.toml)"
if ! command -v python3 >/dev/null 2>&1; then
  bad "python3 is not on PATH"
  note "install Python ${PYTHON_MIN}+ first; this script does not manage interpreters"
else
  py_version="$(python3 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
  if python3 -c "import sys; sys.exit(0 if sys.version_info[:2] >= tuple(int(p) for p in '${PYTHON_MIN}'.split('.')) else 1)"; then
    ok "python3 ${py_version} ($(command -v python3))"
  else
    bad "python3 ${py_version} is older than ${PYTHON_MIN}"
    note "pyproject.toml requires python = \"^${PYTHON_MIN}\""
  fi
fi

# ------------------------------------------------------------------- make ----

step "GNU make"
have_gnu_make() {
  command -v make >/dev/null 2>&1 || return 1
  make --version 2>/dev/null | head -n 1 | grep -q 'GNU Make'
}

if have_gnu_make; then
  ok "$(make --version | head -n 1)"
else
  # A non-GNU make is the interesting case: BusyBox aborts on Makefile:178 before
  # any target runs, `make help` included, so the failure looks like a broken
  # Makefile rather than a wrong make.
  if command -v make >/dev/null 2>&1; then
    bad "make is $(make --version 2>/dev/null | head -n 1) — not GNU make"
    note "BusyBox aborts on Makefile:178 ('expected separator') before any target runs"
  else
    bad "make is not installed"
  fi

  if [ "$CHECK_ONLY" -eq 1 ]; then
    note "would install: make"
  elif command -v apt-get >/dev/null 2>&1; then
    note "installing make via apt-get"
    as_root apt-get update -qq
    as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends make
    have_gnu_make && ok "$(make --version | head -n 1)" \
      || bad "make is still not GNU make after install"
  else
    bad "no apt-get on this host; install GNU make with the system package manager"
    note "the doctor still works without make: poetry run toolkit infra ansible doctor"
  fi
fi

# ----------------------------------------------------------------- poetry ----

step "Poetry ${POETRY_VERSION}"
poetry_version() {
  poetry --version 2>/dev/null | sed -n 's/^Poetry (version \(.*\))$/\1/p'
}

if command -v poetry >/dev/null 2>&1 && [ "$(poetry_version)" = "$POETRY_VERSION" ]; then
  ok "poetry ${POETRY_VERSION} ($(command -v poetry))"
else
  if command -v poetry >/dev/null 2>&1; then
    bad "poetry $(poetry_version) is installed, this repo pins ${POETRY_VERSION}"
    note "lock-version 2.1 needs Poetry >= 2.1; the pin keeps seat and runner identical"
  else
    bad "poetry is not installed"
  fi

  if [ "$CHECK_ONLY" -eq 1 ]; then
    note "would install: poetry ${POETRY_VERSION}"
  elif ! command -v curl >/dev/null 2>&1; then
    bad "curl is required to fetch the Poetry installer"
  else
    note "installing poetry ${POETRY_VERSION} via the official installer"
    # The installer builds its own venv, so PEP 668 never applies — unlike
    # `pip install poetry`, which this distro refuses without --break-system-packages.
    curl -sSL https://install.python-poetry.org | POETRY_VERSION="$POETRY_VERSION" python3 -
    export PATH="$HOME/.local/bin:$PATH"
    if [ "$(poetry_version)" = "$POETRY_VERSION" ]; then
      ok "poetry ${POETRY_VERSION} ($(command -v poetry))"
      printf '\n  Poetry landed in ~/.local/bin. Add it to future shells if it is not\n'
      printf '  already there:\n'
      printf '    export PATH="$HOME/.local/bin:$PATH"\n'
    else
      bad "poetry did not land at ${POETRY_VERSION}; check the installer output above"
    fi
  fi
fi

# --------------------------------------------------------------- hand-off ----

step "ansible-core and the collections"
if [ "$CHECK_ONLY" -eq 1 ]; then
  note "--check: not running 'make setup-ansible'"
  note "that target installs ansible-core into the venv, the collection pins, and"
  note "then runs the doctor — the only authority on whether this machine works"
else
  if [ "$FAILED" -ne 0 ]; then
    printf '\n[ERROR] %d prerequisite(s) above are unresolved; not handing off to make\n' "$FAILED" >&2
    exit 1
  fi
  # Deliberately not duplicated here: the venv install, the collection pins and
  # the doctor are the Makefile's business, and two copies would drift.
  make setup-ansible
fi

if [ "$FAILED" -ne 0 ]; then
  printf '\n[ERROR] %d check(s) failed\n' "$FAILED" >&2
  exit 1
fi
if [ "$CHECK_ONLY" -eq 1 ]; then
  printf '\nThis machine can be a controller. Run without --check to install.\n'
else
  printf '\nDone. `make setup-ansible` already ran and ended in the doctor.\n'
fi
