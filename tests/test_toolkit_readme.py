"""`toolkit/README.md` must describe the package that exists (#1751).

The previous README documented a `commands/lib/utils` layout and an
`infra/config/env/` source of truth that never existed, and nothing noticed for
two months. Two checks close that: the command table is compared with a fresh
render of the live command tree (which also covers every group), and every path
the prose names, globs included, must exist.
"""

from __future__ import annotations

import itertools
import re
from pathlib import Path

import pytest

from toolkit.features import cli_reference
from toolkit.main import app

REPO = Path(__file__).resolve().parent.parent
README = REPO / "toolkit" / "README.md"

# A backticked token with a slash and no placeholder is a path the reader will look for.
PATH_TOKEN = re.compile(r"`([\w.\-]+(?:/[\w.\-{},*]*)+/?)`")


def _prose() -> str:
    """The README without the generated block, whose cells cite commands, not files."""
    text = README.read_text(encoding="utf-8")
    head, rest = text.split(cli_reference.START, 1)
    _, tail = rest.split(cli_reference.END, 1)
    return head + tail


def _expand(token: str) -> list[str]:
    """`dir/{a,b}.yaml` -> both files; a token without braces is itself."""
    match = re.search(r"\{([^}]*)\}", token)
    if match is None:
        return [token]
    return list(
        itertools.chain.from_iterable(
            _expand(token[: match.start()] + option + token[match.end() :]) for option in match.group(1).split(",")
        )
    )


def test_the_command_table_matches_the_command_tree() -> None:
    current = README.read_text(encoding="utf-8")
    assert cli_reference.splice(current, cli_reference.render(app)) == current, (
        "toolkit/README.md is stale: run `poetry run toolkit tools cli-reference --write`"
    )


@pytest.mark.parametrize("token", sorted(set(PATH_TOKEN.findall(_prose()))))
def test_every_path_the_prose_names_exists(token: str) -> None:
    # A `*` must match at least one file: a glob over a renamed directory matches none.
    missing = [p for p in _expand(token) if not (REPO / p).exists() and not list(REPO.glob(p))]
    assert not missing, f"toolkit/README.md names paths that do not exist: {missing}"


def test_the_prose_names_at_least_the_ssot_paths() -> None:
    """A parametrized check over zero tokens passes silently; this keeps the scan honest."""
    assert "infra/config/values/common.yaml" in set(PATH_TOKEN.findall(_prose()))


def test_a_glob_token_is_scanned_and_must_match_something() -> None:
    assert PATH_TOKEN.findall("see `infra/config/values/*.yaml` here") == ["infra/config/values/*.yaml"]
    assert list(REPO.glob("infra/config/values/*.yaml"))
    assert not list(REPO.glob("infra/config/valuez/*.yaml"))


def test_the_overlay_files_the_values_bullet_names_exist() -> None:
    """Bare `hub.yaml` has no directory in it, so the path scan cannot see it."""
    bullet = next(line for line in _prose().splitlines() if line.startswith("- **Values**"))
    names = re.findall(r"`([\w.\-]+\.yaml)`", bullet)
    assert names, "the Values bullet no longer names an overlay file"
    missing = [n for n in names if not (REPO / "infra" / "config" / "values" / n).exists()]
    assert not missing, missing
