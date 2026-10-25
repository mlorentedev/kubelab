"""The suite runs the nodes' shell scripts on a GNU userland, on every workstation.

The scripts target Ubuntu. CI is Linux, so it has GNU coreutils natively; macOS
gets them from `tests/conftest.py`, which puts Homebrew's gnubin first. The
`base64 -w0` and `chown --version` checks fail on a BSD userland, so a conftest
that stopped doing that is caught here, and not as 90 unrelated-looking failures.
There is no `timeout` check: Homebrew links an unprefixed GNU `timeout` and the
conftest aborts the session when coreutils is absent, so it would always pass.
"""

from __future__ import annotations

import subprocess


def test_base64_takes_the_gnu_wrap_flag() -> None:
    result = subprocess.run(["base64", "-w0"], input=b"kubelab", capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout == b"a3ViZWxhYg=="


def test_chown_takes_long_options(tmp_path) -> None:
    """The scripts call `chown --reference`; BSD chown has no long options.

    Checked by behavior, not by the `--version` banner: Ubuntu 25.10 ships uutils
    coreutils, which takes the same options and does not print "GNU coreutils".
    """
    ref, target = tmp_path / "ref", tmp_path / "target"
    ref.touch()
    target.touch()
    result = subprocess.run(["chown", f"--reference={ref}", str(target)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


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


def test_gnubin_is_prepended_when_path_is_bsd(tmp_path, monkeypatch) -> None:
    """With only BSD tools on PATH, the GNU dir goes first, ahead of everything else (review of #2237)."""
    import tests.conftest as conftest

    gnubin = tmp_path / "gnubin"
    bsd = tmp_path / "bsd"
    gnubin.mkdir()
    bsd.mkdir()
    for tool in conftest.GNU_TOOLS:
        for directory, output in ((gnubin, f"{tool} (GNU coreutils) 9.5"), (bsd, f"usage: {tool}")):
            fake = directory / tool
            fake.write_text(f"#!/bin/sh\necho '{output}'\n")
            fake.chmod(0o755)
    monkeypatch.setattr(conftest.sys, "platform", "darwin")
    monkeypatch.setattr(conftest, "GNU_COREUTILS", (gnubin,))
    # PATH is the BSD fakes only: on Linux /usr/bin is GNU and would make the function return early.
    monkeypatch.setenv("PATH", str(bsd))
    conftest._gnu_userland_first()
    assert conftest.os.environ["PATH"] == f"{gnubin}{conftest.os.pathsep}{bsd}"


def test_the_session_hook_puts_the_gnu_userland_first(monkeypatch) -> None:
    """The unit tests above call the function; this proves the hook still does (review of #2237).

    On Linux every other check here passes with the call removed, because the host is GNU already.
    """
    import tests.conftest as conftest

    calls: list[str] = []
    monkeypatch.setattr(conftest, "_gnu_userland_first", lambda: calls.append("gnu"))
    monkeypatch.setattr(conftest, "_install_host_client_barrier", lambda: None)
    conftest.pytest_configure(None)  # type: ignore[arg-type]
    assert calls == ["gnu"]
