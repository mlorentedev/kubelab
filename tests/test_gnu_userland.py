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


def test_a_gnu_timeout_already_on_path_is_accepted(tmp_path, monkeypatch) -> None:
    """GNU coreutils outside the Homebrew prefixes (nix, a custom prefix) is enough (review of #2237)."""
    import tests.conftest as conftest

    for tool in conftest.GNU_TOOLS:
        fake = tmp_path / tool
        fake.write_text(f"#!/bin/sh\necho '{tool} (GNU coreutils) 9.5'\n")
        fake.chmod(0o755)
    monkeypatch.setattr(conftest.sys, "platform", "darwin")
    monkeypatch.setattr(conftest, "GNU_COREUTILS", (tmp_path / "absent",))
    monkeypatch.setenv("PATH", str(tmp_path))
    conftest._gnu_userland_first()
    assert conftest.os.environ["PATH"] == str(tmp_path)


def test_a_gnu_timeout_alone_is_not_enough(tmp_path, monkeypatch) -> None:
    """Homebrew's unprefixed `timeout` is GNU while `chown` and `base64` stay BSD."""
    import pytest

    import tests.conftest as conftest

    # PATH is the fakes only: on Linux /usr/bin/chown is GNU and would pass this.
    for tool, version in (("timeout", "timeout (GNU coreutils) 9.5"), ("chown", "usage: chown"), ("base64", "usage")):
        fake = tmp_path / tool
        fake.write_text(f"#!/bin/sh\necho '{version}'\n")
        fake.chmod(0o755)
    monkeypatch.setattr(conftest.sys, "platform", "darwin")
    monkeypatch.setattr(conftest, "GNU_COREUTILS", (tmp_path / "absent",))
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(pytest.UsageError):
        conftest._gnu_userland_first()
