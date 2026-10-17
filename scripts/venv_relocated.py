"""Exit 1 when a virtualenv's console scripts name an interpreter outside it.

A venv records its own absolute path in every script's shebang. Rename or move
the directory that holds an in-project venv and each script keeps pointing at
the old location: `pytest` is present and executable, its interpreter is not,
and `poetry run` reports "Command not found" while `poetry env info` calls the
environment fine (TOOL-067, #1707). `make worktree-init` treated the presence of
the directory as readiness, so re-running it did nothing.

Standard library only and run with the system python on purpose: the check has
to work exactly when the project's own venv does not.
"""

from __future__ import annotations

import pathlib
import sys


def relocated_shebang(venv: pathlib.Path) -> str | None:
    """Return the first shebang that points at another venv's interpreter, or None."""
    bin_dir = venv / "bin"
    if not bin_dir.is_dir():
        return None
    # A venv reached through a symlinked parent can be written down either way.
    own = (str(venv.resolve() / "bin") + "/", str(venv.absolute() / "bin") + "/")
    for script in sorted(bin_dir.iterdir()):
        if script.is_symlink() or not script.is_file():
            continue
        try:
            with script.open("rb") as handle:
                first = handle.readline(512).decode("utf-8", errors="replace").strip()
        except OSError:
            continue
        if not first.startswith("#!"):
            continue
        parts = first[2:].split()
        interpreter = parts[0] if parts else ""
        # Only a python interpreter is judged: `#!/bin/sh` and `#!/usr/bin/env` are not the venv's.
        if not pathlib.PurePosixPath(interpreter).name.startswith("python"):
            continue
        if not interpreter.startswith(own):
            return f"{script.name}: {first}"
    return None


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: venv_relocated.py <venv-dir>", file=sys.stderr)
        return 2
    stale = relocated_shebang(pathlib.Path(argv[1]))
    if stale is None:
        return 0
    print(f"venv {argv[1]} was moved: {stale} (expected a path under {pathlib.Path(argv[1]).resolve()}/bin/)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
