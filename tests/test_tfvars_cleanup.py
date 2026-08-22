"""A rendered tfvars must not survive a failed terraform run.

TOOL-039. The `tf-*` targets render a tfvars from SOPS, run terraform, then
remove the file. With the `rm` on its own recipe line, make's abort-on-first-
failure meant it never ran after a failed plan: `aws.tfvars` -- carrying
`tailscale_authkey` and `headscale_api_key` -- stayed on disk indefinitely with
nothing reporting it. A failing plan is routine, not exotic: expired
credentials, an API not enabled, a provider version bump.

`.gitignore` kept it out of the repository, which is why this was a defect to
fix rather than an incident. The exposure was local disk.

These tests EXECUTE the recipe with stubbed `terraform` and toolkit commands
rather than asserting on Makefile text. A test that grepped for `_exit` would
pass on any line containing it and would not notice the guarantee being lost
some other way -- and the property is behavioural: *terraform fails, the file is
gone anyway, and the failure still reaches the caller*.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
MAKEFILE = REPO / "Makefile"

# target -> the tfvars basename it renders
RENDERING_TARGETS = {
    "tf-aws-plan": "aws.tfvars",
    "tf-aws-apply": "aws.tfvars",
    "tf-aws-destroy": "aws.tfvars",
    "tf-gcp-plan": "gcp.tfvars",
    "tf-gcp-apply": "gcp.tfvars",
    "tf-gcp-destroy": "gcp.tfvars",
    "tf-gcp-bootstrap-plan": "gcp-bootstrap.tfvars",
    "tf-gcp-bootstrap-apply": "gcp-bootstrap.tfvars",
}


def _recipe(target: str) -> str:
    """The target's recipe as shell source, with Make syntax resolved."""
    text = MAKEFILE.read_text(encoding="utf-8")
    m = re.search(rf"^{re.escape(target)}:\n((?:\t.*\n)+)", text, re.M)
    assert m, f"target {target!r} not found in the Makefile, or it has no recipe"

    lines = []
    for raw in m.group(1).splitlines():
        line = raw.lstrip("\t")
        if line.startswith("@"):
            line = line[1:]
        lines.append(line)
    shell = "\n".join(lines)

    # `$$` is Make's escape for a literal shell `$`; protect it, drop every
    # remaining `$(...)` expansion, then restore.
    shell = shell.replace("$$", "\x00")
    while True:
        stripped = re.sub(r"\$\([^()]*\)", "", shell)
        if stripped == shell:
            break
        shell = stripped
    return shell.replace("\x00", "$")


def _logical_lines(shell: str) -> list[str]:
    """Recipe lines as make sees them: backslash continuations are ONE line.

    This is what separates the fixed form from the broken one. `terraform ...; \\
    _exit=$?; rm -f ...` is a single recipe line, so the cleanup shares the
    shell that ran terraform and executes whatever terraform returned. A bare
    `rm` on the next line is a second recipe line, which make never reaches.
    """
    out: list[str] = []
    buf = ""
    for raw in shell.splitlines():
        buf += raw[:-1] + "\n" if raw.endswith("\\") else raw
        if raw.endswith("\\"):
            continue
        if buf.strip():
            out.append(buf)
        buf = ""
    if buf.strip():
        out.append(buf)
    return out


def _run(
    target: str, tfvars: str, tmp_path: pathlib.Path, *, terraform_fails: bool
) -> tuple[subprocess.CompletedProcess[str], pathlib.Path]:
    """Execute the recipe with stub `terraform` and a stub renderer.

    The stub renderer writes the tfvars the way the real one does, so what is
    under test is whether the recipe removes it -- not whether it was created.
    """
    module_dir = tmp_path / "module"
    module_dir.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    rc = 1 if terraform_fails else 0
    (bin_dir / "terraform").write_text(f'#!/bin/sh\necho "terraform $*" >&2\nexit {rc}\n')
    (bin_dir / "terraform").chmod(0o755)

    shell = _recipe(target)
    # The renderer line becomes a stub that creates the file inside the temp
    # module dir; the `cd` is retargeted there so nothing touches the real repo.
    # Matched on `infra terraform <x>-tfvars`, not on the word "toolkit": the AWS
    # targets spell it `$(POETRY) run toolkit ...` and the GCP ones `$(TOOLKIT)
    # ...`, and stripping Make expansions leaves the second with no "toolkit" in
    # it at all.
    # A FUNCTION as the replacement, never a string: `re.sub` interprets escapes
    # in a string replacement, so a `\n` in the stub became a real newline and
    # split the single logical line into two -- which is the very distinction
    # this harness exists to measure.
    stub = f'echo "secret = live-credential" > "{module_dir}/{tfvars}"'
    shell, subs = re.subn(
        r"^\s*.*infra terraform \S+-tfvars\s*$",
        lambda _m: stub,
        shell,
        count=1,
        flags=re.M,
    )
    assert subs == 1, f"{target}: no tfvars renderer line found; the recipe changed shape"
    shell = re.sub(r"cd infra/terraform/\S+", f'cd "{module_dir}"', shell, count=1)

    # MAKE'S SEMANTICS, NOT THE SHELL'S, and this is the load-bearing part of the
    # harness. Make runs each recipe line in a SEPARATE shell and aborts at the
    # first non-zero exit. A single `sh -c` over the whole recipe does neither: it
    # runs on past a failure, so the `rm` executes anyway and the file-survival
    # assertion passes while the bug is present.
    #
    # Measured: the first version of this harness did exactly that, and reverting
    # a target to the original broken form failed only the exit-code test. A test
    # that cannot fail on the defect it was written for is worse than no test.
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    last = subprocess.CompletedProcess(["sh"], 0, "", "")
    for line in _logical_lines(shell):
        last = subprocess.run(["sh", "-c", line], capture_output=True, text=True, cwd=tmp_path, timeout=30, env=env)
        if last.returncode != 0:
            break
    return last, module_dir / tfvars


@pytest.mark.parametrize("target,tfvars", sorted(RENDERING_TARGETS.items()))
class TestTheRenderedFileNeverOutlivesTheRun:
    def test_removed_even_when_terraform_fails(self, target: str, tfvars: str, tmp_path: pathlib.Path) -> None:
        """The regression itself: make aborts the recipe, the `rm` never runs."""
        _, path = _run(target, tfvars, tmp_path, terraform_fails=True)
        assert not path.exists(), (
            f"{target}: terraform failed and {tfvars} was left on disk. The cleanup "
            "must share a shell line with the terraform call, not sit on its own "
            "recipe line where make's abort-on-failure skips it."
        )

    def test_removed_on_the_happy_path_too(self, target: str, tfvars: str, tmp_path: pathlib.Path) -> None:
        """Without this, a target that never created the file would pass above."""
        _, path = _run(target, tfvars, tmp_path, terraform_fails=False)
        assert not path.exists(), f"{target}: {tfvars} survived a successful run"

    def test_the_failure_still_reaches_the_caller(self, target: str, tfvars: str, tmp_path: pathlib.Path) -> None:
        """Cleaning up must not swallow the exit code.

        The naive fix -- appending `; rm -f ...` -- makes the recipe exit with
        the `rm`'s status, so every failed plan reports success. That is a worse
        defect than the one being fixed: it is silent in the other direction.
        """
        result, _ = _run(target, tfvars, tmp_path, terraform_fails=True)
        assert result.returncode != 0, (
            f"{target}: terraform failed but the recipe exited 0 — the cleanup swallowed the exit code"
        )

    def test_success_is_still_success(self, target: str, tfvars: str, tmp_path: pathlib.Path) -> None:
        result, _ = _run(target, tfvars, tmp_path, terraform_fails=False)
        assert result.returncode == 0, f"{target}: happy path exited {result.returncode}\n{result.stderr}"
