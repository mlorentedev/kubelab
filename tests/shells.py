"""Shells the tests run, by full path (#3409).

On Windows `subprocess` resolves a bare `"bash"` through CreateProcess, which
searches System32 before PATH and starts `System32\\bash.exe`, the WSL launcher,
even when Git Bash is on PATH. `shutil.which` searches PATH only, so it finds
Git Bash, and that is the bash the tests' `which("bash")` guards already check.
"""

from __future__ import annotations

import shutil

BASH = shutil.which("bash") or "bash"
