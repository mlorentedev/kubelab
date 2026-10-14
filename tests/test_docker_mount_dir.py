"""TOOL-113 (#2244): a directory bind-mounted into a container lives under $HOME.

On macOS pytest's `tmp_path` sits under `/private/var/folders`, which Colima (like
Docker Desktop) does not share with its VM. The mount then arrives empty, and a
mounted file arrives as a directory, so a test that passes in Linux CI fails on
the Mac for a reason that has nothing to do with what it checks.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def test_the_mount_dir_is_under_home(docker_mount_dir: Path) -> None:
    assert docker_mount_dir.is_dir()
    # Resolved on both sides: a `~/.cache` symlinked off $HOME is lexically under it and
    # still unshared, because the VM follows the link to a place it cannot see.
    assert docker_mount_dir.resolve().is_relative_to(Path.home().resolve()), (
        "Colima and Docker Desktop share $HOME only"
    )


def _starts_docker(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.List)
        and bool(node.elts)
        and isinstance(node.elts[0], ast.Constant)
        and node.elts[0].value == "docker"
    )


def _calls_subprocess(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
    )


def _mounting_functions() -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Functions that run `docker ... -v ...` through subprocess, in every module under tests/."""
    found = []
    for path in sorted(TESTS.rglob("*.py")):
        for fn in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            nodes = list(ast.walk(fn))
            mounts = any(isinstance(n, ast.Constant) and n.value == "-v" for n in nodes)
            if mounts and any(_starts_docker(n) for n in nodes) and any(_calls_subprocess(n) for n in nodes):
                found.append((f"{path.relative_to(TESTS)}::{fn.name}", fn))
    return found


def test_the_guard_finds_the_mounting_tests() -> None:
    """A floor: a rule that matched nothing would pass every file below."""
    names = {name for name, _ in _mounting_functions()}
    assert "test_oauth_tokens_not_logged.py::test_vector_redacts_every_token_kind_and_nothing_else" in names
    assert "test_access_review.py::test_argo_cd_rbac_lets_users_operate_and_never_administer" in names


def test_no_test_mounts_pytests_tmp_path_into_a_container() -> None:
    """A function that runs `docker ... -v` never touches `tmp_path`; use `docker_mount_dir`.

    Read per function rather than per mount argument, so a path derived from
    `tmp_path` and mounted through another name (`tests = tmp_path / ...`, then
    `-v f"{tests}:..."`) counts too.
    """
    offenders = [
        name
        for name, fn in _mounting_functions()
        if any(isinstance(n, ast.Name) and n.id == "tmp_path" for n in ast.walk(fn))
        or any(a.arg == "tmp_path" for a in fn.args.args)
    ]
    assert not offenders, offenders
