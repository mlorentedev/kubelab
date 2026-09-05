"""A `make` target that documents a prod default must actually reach it.

`ENV ?= dev` is set globally in the Makefile, so `ENV` always has a value by the
time any recipe expands. `$(or $(ENV),prod)` therefore never sees an empty first
argument and its `prod` branch is dead code: eight targets promised prod in their
usage lines and ran against dev (#1644).

The three that mattered were `backup-coverage`, `backup verify-restic` and
`backup verify-destination` -- verifications answering for `dev` while being read
as statements about prod.

**The repo already knew.** A comment on the `alerts` target spells out exactly
why `$(or ...)` cannot work and shows the `$(filter)` form that does. It was
written at the one site that did not need it, so nobody editing `backup-coverage`
had any path to it. That is why the fix here is a test rather than eight edits,
and why its failure message carries the whole explanation: the only place this
reasoning has ever needed to be is in front of the person reintroducing the idiom,
at the moment they do it.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
MAKEFILE = REPO_ROOT / "Makefile"

#: The form that cannot work: `$(ENV)` as `or`'s first argument. Deliberately
#: NOT a ban on `$(or ...)` in general -- `$(or $(filter staging prod,$(ENV)),prod)`
#: is correct and is the fix, because `filter` yields empty for anything that is
#: not a real target and `or` finally has something to fall back from.
UNREACHABLE = re.compile(r"\$\(or\s+\$\(ENV\)\s*,")

WHY = """
`ENV ?= dev` is set globally, so $(ENV) is never empty and the fallback in
`$(or $(ENV),<default>)` can never be selected. The target will run against
`dev` while its usage line promises something else.

Use the filter form instead, which is what `alerts` and `logs` already do:

    --env $(or $(filter staging prod,$(ENV)),prod)

`filter` yields empty for any value that is not a real target for this command,
which does two things: it lets `or` reach its default, and it stops a nonsense
`ENV` from being passed through to the command. See #1644.
"""


def _recipe_lines() -> list[tuple[int, str]]:
    """Lines that are part of a recipe -- i.e. that Make will expand and run.

    Comments are excluded on purpose: the `alerts` target carries a comment that
    quotes the broken form in order to warn about it, and a guard that cannot
    tell a warning from an instance would forbid the repo from documenting its
    own bug.
    """
    return [
        (n, line)
        for n, line in enumerate(MAKEFILE.read_text().splitlines(), start=1)
        if line.startswith("\t")
    ]


class TestNoTargetUsesTheUnreachableDefault:
    def test_the_guard_reads_a_real_makefile(self) -> None:
        """Floor. An empty expectation is not a weak expectation: it matches
        everything, and every assertion below would pass against a file this
        guard failed to parse (lesson-416)."""
        lines = _recipe_lines()
        assert len(lines) >= 200, f"expected a substantial Makefile, parsed {len(lines)} recipe lines"
        assert any("$(TOOLKIT)" in line for _n, line in lines), "parsed lines do not look like this repo's recipes"

    def test_the_guard_would_still_recognise_the_idiom_it_bans(self) -> None:
        """Mutation-proof for the regex itself: if UNREACHABLE stopped matching,
        every assertion here would pass vacuously against a broken Makefile."""
        assert UNREACHABLE.search("\t@$(TOOLKIT) backup coverage --env $(or $(ENV),prod)")
        assert UNREACHABLE.search("\t@x -e $(or $(ENV) ,prod)")
        assert not UNREACHABLE.search("\t@x --env $(or $(filter staging prod,$(ENV)),prod)")
        assert not UNREACHABLE.search("\t@x --token $(or $(TOKEN),bot)")

    def test_no_recipe_line_uses_it(self) -> None:
        offenders = [(n, line.strip()) for n, line in _recipe_lines() if UNREACHABLE.search(line)]
        assert not offenders, (
            "Makefile targets use an unreachable environment default:\n"
            + "\n".join(f"  line {n}: {line}" for n, line in offenders)
            + "\n"
            + WHY
        )


class TestTheDefaultIsReachedInPractice:
    """Expansion, not inspection. `make -n` prints the recipe without running it,
    which needs no cluster and no forge -- and it is the only check that would
    have caught the original bug, since the idiom *looks* right."""

    @staticmethod
    def _expand(target: str, *env: str) -> str:
        proc = subprocess.run(
            ["make", "-n", target, *env],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        return proc.stdout

    @pytest.mark.parametrize("target", ["backup-coverage", "backup-verify-restic"])
    def test_an_unset_env_reaches_prod(self, target: str) -> None:
        out = self._expand(target)
        assert "--env prod" in out, f"{target} with no ENV expanded to: {out.strip()[:200]}"

    @pytest.mark.parametrize("target", ["backup-coverage", "backup-verify-restic"])
    def test_a_nonsense_env_does_not_reach_the_command(self, target: str) -> None:
        """A distinct claim from the one above, and the one that shows `filter`
        is doing work rather than being a longer spelling of `or`: `dev` is not
        a target for these commands and must not be passed through."""
        out = self._expand(target, "ENV=dev")
        assert "--env dev" not in out, f"{target} passed ENV=dev through: {out.strip()[:200]}"
        assert "--env prod" in out

    @pytest.mark.parametrize("target", ["backup-coverage", "backup-verify-restic"])
    def test_a_real_env_is_honoured(self, target: str) -> None:
        """Without this, a target hardcoded to `prod` would pass both tests above."""
        out = self._expand(target, "ENV=staging")
        assert "--env staging" in out, f"{target} ignored ENV=staging: {out.strip()[:200]}"
