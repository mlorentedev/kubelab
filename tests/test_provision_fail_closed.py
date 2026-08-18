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


def _run_branch(tmp_path: pathlib.Path, *, generate_fails: bool) -> subprocess.CompletedProcess[str]:
    """Execute the extracted branch with stubbed toolkit commands."""
    shell = _extract_provision_branch()

    # The four toolkit invocations, in the order they appear: generate, run and
    # restore inside the branch under test, then the plain run in the `else`.
    # Each becomes a stub that records that it happened. The `else` one is
    # stubbed too, so that a mis-forced branch shows up as an unexpected call
    # rather than as a real command escaping into the test.
    marker = tmp_path / "calls.log"
    generate_rc = 1 if generate_fails else 0
    stubs = [
        f'sh -c \'echo generate >> "{marker}"; exit {generate_rc}\'',
        f'sh -c \'echo run >> "{marker}"; exit 0\'',
        f'sh -c \'echo restore >> "{marker}"; exit 0\'',
        f'sh -c \'echo else_run >> "{marker}"; exit 0\'',
    ]
    # The trailing `&&` / `;` is the thing under test, so the substitution must
    # preserve it. Swallowing it with `.*$` would leave the stubs as separate
    # commands and the test would report a failure the Makefile does not have.
    for stub in stubs:
        shell = re.sub(
            r"^\s*infra ansible (?:generate|run).*?(&&|;)?$",
            lambda m, s=stub: f"{s} {m.group(1)}" if m.group(1) else s,
            shell,
            count=1,
            flags=re.M,
        )

    # BOOTSTRAP/TRANSPORT are empty after expansion-stripping, so force the branch.
    shell = shell.replace('if [ -n "" ] || [ -n "" ]; then', "if true; then")

    return subprocess.run(
        ["sh", "-c", shell], capture_output=True, text=True, cwd=tmp_path, timeout=30
    )


def _calls(tmp_path: pathlib.Path) -> list[str]:
    log = tmp_path / "calls.log"
    return log.read_text(encoding="utf-8").split() if log.exists() else []


def test_failed_generate_does_not_run_the_playbook(tmp_path: pathlib.Path) -> None:
    """The half that regressed: generate fails, so no run and a non-zero exit."""
    result = _run_branch(tmp_path, generate_fails=True)
    calls = _calls(tmp_path)

    assert "run" not in calls, (
        f"inventory generation failed and the playbook ran anyway: {calls}. "
        "The generate and the run must be joined with `&&`, not `;`."
    )
    assert result.returncode != 0, (
        "a failed generate exited 0 — `_exit` is capturing the run's status "
        "instead of generate's"
    )


def test_failed_generate_still_restores_the_mesh_inventory(tmp_path: pathlib.Path) -> None:
    """Short-circuiting the run must not also skip the restore."""
    _run_branch(tmp_path, generate_fails=True)
    assert "restore" in _calls(tmp_path), (
        "the mesh inventory was not restored after a failed generate; the "
        "restore line must stay unconditional"
    )


def test_successful_generate_still_runs_the_playbook(tmp_path: pathlib.Path) -> None:
    """The negative side: the guard must not break the happy path.

    Without this, a target that never ran anything would satisfy the test above.
    """
    result = _run_branch(tmp_path, generate_fails=False)
    calls = _calls(tmp_path)

    assert calls == ["generate", "run", "restore"], f"unexpected call order: {calls}"
    assert "else_run" not in calls, "the else branch ran; the test forced the wrong path"
    assert result.returncode == 0, f"happy path exited {result.returncode}"


def test_extraction_found_all_three_toolkit_calls() -> None:
    """Guard the guard: if the recipe is restructured, this test must not pass vacuously.

    Every assertion above depends on the stubs having replaced real commands. If
    the extraction silently matched nothing, the block would run no commands and
    the "no run happened" assertion would pass for the wrong reason.
    """
    shell = _extract_provision_branch()
    assert len(re.findall(r"^\s*infra ansible (?:generate|run)", shell, flags=re.M)) == 4, (
        "expected exactly four toolkit invocations in the provision recipe "
        "(generate, run, restore, and the else-branch run) — the recipe changed "
        "shape, so update this test"
    )


@pytest.mark.parametrize("marker", ["_exit=$?", "exit $_exit"])
def test_exit_propagation_still_present(marker: str) -> None:
    """The restore runs between the playbook and the exit, so the code is saved and re-raised."""
    assert marker in _extract_provision_branch(), (
        f"{marker!r} is gone from the provision branch — the target no longer "
        "propagates the failure past the restore"
    )
