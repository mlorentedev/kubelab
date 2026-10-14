"""The suite runs the nodes' shell scripts on a GNU userland, on every workstation.

The scripts target Ubuntu. CI is Linux, so it has GNU coreutils natively; macOS
gets them from `tests/conftest.py`, which puts Homebrew's gnubin first. These
checks fail on a BSD userland, so a conftest that stopped doing that is caught
here, and not as 90 unrelated-looking failures.
"""

from __future__ import annotations

import shutil
import subprocess


def test_timeout_is_on_path() -> None:
    assert shutil.which("timeout"), "GNU timeout is missing: the node scripts call it"


def test_base64_takes_the_gnu_wrap_flag() -> None:
    result = subprocess.run(["base64", "-w0"], input=b"kubelab", capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout == b"a3ViZWxhYg=="


def test_chown_takes_long_options() -> None:
    result = subprocess.run(["chown", "--version"], capture_output=True, text=True, check=False)
    assert result.returncode == 0 and "GNU coreutils" in result.stdout, result.stderr
