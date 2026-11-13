"""`make setup` must not pip-install Poetry into the active interpreter (#3399).

`setup-poetry` used to run `python3 -m pip install --upgrade poetry` with its
output discarded. On a host where `python3` is a version manager's interpreter,
that put a second Poetry ahead of the isolated one on PATH. The copy it left
lacked `xattr`, which Poetry imports only when it creates a venv on macOS, so
`make worktree-init` failed on the first run in every new worktree and passed
on the second. Poetry belongs in an isolated tool environment (`uv tool`,
`pipx`, the official installer); the target only checks that one is there.
"""

import re
from pathlib import Path

MAKEFILE = Path(__file__).resolve().parents[1] / "Makefile"


def _recipe(target: str) -> str:
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"{target}:")
    body = []
    for line in lines[start + 1 :]:
        if not line.startswith("\t"):
            break
        body.append(line)
    return "\n".join(body)


def test_setup_poetry_does_not_pip_install_poetry() -> None:
    recipe = _recipe("setup-poetry")
    assert not re.search(r"pip3?\s+install[^\n]*\bpoetry\b", recipe), recipe


def test_setup_poetry_refuses_a_missing_poetry_with_a_way_to_install_it() -> None:
    recipe = _recipe("setup-poetry")
    assert "command -v $(POETRY)" in recipe, recipe
    assert "uv tool install poetry" in recipe, recipe
