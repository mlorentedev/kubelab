"""Shells the tests run, by full path (#3409).

On Windows `subprocess` resolves a bare `"bash"` through CreateProcess, which
searches System32 before PATH and starts `System32\\bash.exe`, the WSL launcher,
even when Git Bash is on PATH. `shutil.which` searches PATH only, so it finds
Git Bash, and that is the bash the tests' `which("bash")` guards already check.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Mapping

BASH = shutil.which("bash") or "bash"


def child_env(env: Mapping[str, str]) -> dict[str, str]:
    """`env` for a child process, plus what Windows cannot start one without.

    A test that passes a minimal `env={"PATH": ...}` drops `SYSTEMROOT`, and on
    Windows a Python child then dies at startup, before it runs a line (#3409).
    Elsewhere the environment comes back unchanged.
    """
    out = dict(env)
    if sys.platform == "win32":
        out.setdefault("SYSTEMROOT", os.environ["SYSTEMROOT"])
    return out
