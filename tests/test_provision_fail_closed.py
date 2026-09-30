"""`make provision` must not run a playbook when inventory generation failed.

TOOL-036. The `provision` target's BOOTSTRAP/TRANSPORT branch regenerates the
inventory, runs the playbook, then restores the mesh inventory. The generate and
the run were joined with `;`, so a failed generate did not stop the run — and
`_exit=$?`, sitting after the run, captured the run's status rather than
generate's, so the failure could not reach the target's exit code either.

Measured before the fix, with `make provision NODE=ace1 TRANSPORT=bogus CHECK=1`:
generate printed `[ERROR] Invalid --transport 'bogus'`, the playbook then ran to
`PLAY RECAP` against the inventory already on disk, and the target exited **0**
reporting `[SUCCESS] Playbook completed successfully`. Off the mesh that wastes a
timeout; on the mesh — the normal case — it silently provisions through a
transport nobody asked for. `verification.md` for TOOL-016 calls the design
"fail-closed on no public jump"; it was, at the toolkit layer, and was not at the
entry point operators actually use.

This test extracts the real recipe from the Makefile and executes it with stub
commands rather than asserting on its text. A test that only grepped for `&&`
would pass on any line containing one and would not notice the guarantee being
lost some other way — and the property under test is behavioural: *a failed
generate produces no run and a non-zero exit, while the restore still happens*.

TOOL-090 (#1941) moved the generate into `toolkit infra ansible run` itself, so
"a failed generate produces no run" is now `run`'s own guarantee, pinned in
`tests/test_ansible_run_generates_inventory.py`. What stays here is the part the
recipe still owns: a failed run exits non-zero, and the restore still happens.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
MAKEFILE = REPO_ROOT / "Makefile"


def _extract_provision_branch() -> str:
    """Return the provision target's BOOTSTRAP/TRANSPORT branch as shell source.

    Reads the recipe out of the Makefile and converts Make syntax to shell:
    `$$` -> `$`, and every `$(...)` expansion dropped, so what runs here is the
    control flow the Makefile actually declares.
    """
    text = MAKEFILE.read_text(encoding="utf-8")
    start = text.index('\t@if [ -n "$(BOOTSTRAP)" ] || [ -n "$(TRANSPORT)" ]; then')
    end = text.index("\n\tfi\n", start) + len("\n\tfi\n")
    block = text[start:end]

    lines = []
    for raw in block.splitlines():
        line = raw.lstrip("\t").lstrip()
        if line.startswith("@"):
            line = line[1:]
        if line.endswith("\\"):
            line = line[:-1].rstrip()
        lines.append(line)

    shell = "\n".join(lines)
    shell = shell.replace("$$", "\x00")  # protect Make-escaped shell dollars
    # Repeatedly, because `$(if $(BOOTSTRAP),...)` nests and one pass would
    # leave the outer call behind as literal text.
    while True:
        stripped = re.sub(r"\$\([^()]*\)", "", shell)
        if stripped == shell:
            break
        shell = stripped
    return shell.replace("\x00", "$")


def _run_branch(
    tmp_path: pathlib.Path, *, run_fails: bool, branch: str = "bootstrap"
) -> subprocess.CompletedProcess[str]:
    """Execute one of the target's two branches with stubbed toolkit commands.

    `branch` selects which side of the `if` runs. A failed `run` stands for any
    failure inside it, a failed inventory generation included.
    """
    shell = _extract_provision_branch()

    # The three toolkit invocations, in the order they appear in the recipe: run
    # and restore inside the BOOTSTRAP/TRANSPORT branch, then the `else` run. Each
    # becomes a stub that records that it happened. Every one is stubbed,
    # including the branch not under test, so a mis-forced branch shows up as an
    # unexpected call rather than as a real command escaping into the test.
    marker = tmp_path / "calls.log"
    run_rc = 1 if run_fails else 0
    stubs = [
        f"sh -c 'echo run >> \"{marker}\"; exit {run_rc}'",
        f"sh -c 'echo restore >> \"{marker}\"; exit 0'",
        f"sh -c 'echo else_run >> \"{marker}\"; exit {run_rc}'",
    ]
    # The trailing `&&` / `;` is part of the control flow under test, so the
    # substitution must preserve it.
    for stub in stubs:
        shell = re.sub(
            r"^\s*infra ansible (?:generate|run).*?(&&|;)?$",
            lambda m, s=stub: f"{s} {m.group(1)}" if m.group(1) else s,
            shell,
            count=1,
            flags=re.M,
        )

    # BOOTSTRAP/TRANSPORT are empty after expansion-stripping, so force the branch.
    condition = "if true; then" if branch == "bootstrap" else "if false; then"
    shell = shell.replace('if [ -n "" ] || [ -n "" ]; then', condition)

    return subprocess.run(["sh", "-c", shell], capture_output=True, text=True, cwd=tmp_path, timeout=30)


def _calls(tmp_path: pathlib.Path) -> list[str]:
    log = tmp_path / "calls.log"
    return log.read_text(encoding="utf-8").split() if log.exists() else []


def test_a_failed_run_exits_non_zero(tmp_path: pathlib.Path) -> None:
    """The half that regressed under TOOL-036: `_exit` must carry the run's status."""
    result = _run_branch(tmp_path, run_fails=True)
    assert result.returncode != 0, "a failed run exited 0: the restore's status replaced the run's"


def test_a_failed_run_still_restores_the_mesh_inventory(tmp_path: pathlib.Path) -> None:
    """Failing the run must not also skip the restore."""
    _run_branch(tmp_path, run_fails=True)
    assert "restore" in _calls(tmp_path), (
        "the mesh inventory was not restored after a failed run; the restore line must stay unconditional"
    )


def test_successful_run_restores_and_exits_zero(tmp_path: pathlib.Path) -> None:
    """The control: without it, a target that never ran anything would satisfy the tests above."""
    result = _run_branch(tmp_path, run_fails=False)
    calls = _calls(tmp_path)

    assert calls == ["run", "restore"], f"unexpected call order: {calls}"
    assert result.returncode == 0, f"happy path exited {result.returncode}"


@pytest.mark.parametrize("run_fails", [True, False])
def test_else_branch_exit_follows_the_run(tmp_path: pathlib.Path, run_fails: bool) -> None:
    """The ordinary path runs once and exits with the run's status."""
    result = _run_branch(tmp_path, run_fails=run_fails, branch="else")

    assert _calls(tmp_path) == ["else_run"], "the else branch was not forced, or it restored"
    assert (result.returncode != 0) == run_fails


def test_extraction_found_all_three_toolkit_calls() -> None:
    """Guard the guard: if the recipe is restructured, this test must not pass vacuously.

    Every assertion above depends on the stubs having replaced real commands. If
    the extraction silently matched nothing, the block would run no commands and
    the assertions would pass for the wrong reason.
    """
    shell = _extract_provision_branch()
    assert len(re.findall(r"^\s*infra ansible (?:generate|run)", shell, flags=re.M)) == 3, (
        "expected exactly three toolkit invocations in the provision recipe "
        "(run and restore, then the else branch's run) -- the recipe changed "
        "shape, so update this test AND check whether the new shape still fails closed"
    )


@pytest.mark.parametrize("marker", ["_exit=$?", "exit $_exit"])
def test_exit_propagation_still_present(marker: str) -> None:
    """The restore runs between the playbook and the exit, so the code is saved and re-raised."""
    assert marker in _extract_provision_branch(), (
        f"{marker!r} is gone from the provision branch — the target no longer propagates the failure past the restore"
    )
