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


#: The correct form, whose presence on a recipe line means that line resolves an
#: environment and therefore owes the expansion checks below.
#:
#: A PATTERN rather than a literal, and the difference is not tidiness. As a
#: literal `"$(or $(filter staging prod,$(ENV))"` this matched twelve sites and
#: missed four -- `provision`, `maintain-notify-test`, `benchmark-disk` and
#: `wait-node-ready` all filter `staging prod hub`, one word longer. The derived
#: set and the table below then agreed with each other perfectly while both were
#: blind to the same four targets, so `covers_every_site` asserted something
#: strictly weaker than it appeared to: not "every target that resolves an
#: environment is tested" but "every target spelling the filter exactly this way
#: is tested". Two derivations from one blind literal cannot disagree, which is
#: why the agreement proved nothing.
FILTER_FORM = re.compile(r"\$\(or\s+\$\(filter\s+[a-z ]+,\$\(ENV\)\)")

#: Every target that resolves an environment, with the flag it passes it under
#: and the default it must reach. `-e` is Ansible's; `--env` is the toolkit's.
#: The defaults are NOT all prod -- `maintain` and `validate-sync` legitimately
#: default to staging -- so a table is the only honest form. `covers_every_site`
#: below derives the expected key set from the Makefile, so a new target cannot
#: use the idiom without appearing here.
ENV_TARGETS: dict[str, tuple[str, str]] = {
    # Fixed by #1644: promised prod, ran against dev.
    "gitea-reconcile": ("--env", "prod"),
    "gitea-rotate-token": ("--env", "prod"),
    "gitea-drop-empty": ("--env", "prod"),
    "gitea-git": ("--env", "prod"),
    "backup": ("-e", "prod"),
    "backup-verify-destination": ("--env", "prod"),
    "backup-verify-restic": ("--env", "prod"),
    "backup-coverage": ("--env", "prod"),
    # Already correct before #1644. Included as a regression net: "correct and
    # untested" is exactly the state the eight above were in.
    "maintain": ("-e", "staging"),
    "backup-node": ("-e", "prod"),
    "backup-schedule": ("-e", "prod"),
    "validate-sync": ("--env", "staging"),
    # Invisible to this table until FILTER_FORM stopped being a literal: these
    # four filter `staging prod hub`, so the old exact-match found neither the
    # site nor its absence here.
    "provision": ("-e", "staging"),
    "maintain-notify-test": ("-e", "staging"),
    "benchmark-disk": ("-e", "staging"),
    "wait-node-ready": ("-e", "staging"),
}

#: Resolves an environment but passes it under no flag at all, so the
#: `(flag, default)` model above cannot express it: `logs` interpolates the env
#: into a kubeconfig filename (`~/.kube/kubelab-$(_ENV)-config`). It is checked
#: by `test_logs_reaches_its_default` rather than bent into the table, and it is
#: named here so `covers_every_site` still accounts for every derived site --
#: an exemption that is declared is a different thing from one that is invisible.
NO_FLAG_TARGETS: dict[str, str] = {"logs": "kubelab-staging-config"}


def _targets_resolving_an_env() -> set[str]:
    """Which target owns each recipe line that resolves an environment."""
    found: set[str] = set()
    current: str | None = None
    for line in MAKEFILE.read_text().splitlines():
        m = re.match(r"^([a-zA-Z0-9_-]+):", line)
        if m:
            current = m.group(1)
        elif line.startswith("\t") and FILTER_FORM.search(line) and current:
            found.add(current)
    return found


class TestTheDefaultIsReachedInPractice:
    """Expansion, not inspection. `make -n` prints the recipe without running it,
    so this needs no cluster and no forge -- and it is the only check that would
    have caught the original bug, because the idiom *looks* right."""

    @staticmethod
    def _expand(target: str, *env: str) -> str:
        proc = subprocess.run(
            ["make", "-n", target, *env],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        return proc.stdout

    def test_the_table_covers_every_site(self) -> None:
        """Derived, not hand-maintained. A target that starts resolving an
        environment must gain an entry here, or this fails -- otherwise the
        parametrised checks below silently stop covering it, which is how eight
        sites reached prod-in-name-only in the first place."""
        found = _targets_resolving_an_env()
        assert len(found) >= 12, f"expected the Makefile to resolve envs in >=12 targets, found {found}"
        covered = set(ENV_TARGETS) | set(NO_FLAG_TARGETS)
        assert found == covered, (
            f"ENV_TARGETS is out of step with the Makefile.\n"
            f"  in the Makefile but not tested: {sorted(found - covered)}\n"
            f"  tested but no longer present:   {sorted(covered - found)}"
        )

    def test_logs_reaches_its_default(self) -> None:
        """`logs` needs SVC before its recipe expands at all, which is why it
        gets its own check rather than a row that would need a third column."""
        out = self._expand("logs", "SVC=authelia")
        assert NO_FLAG_TARGETS["logs"] in out, f"logs with no ENV expanded to: {out.strip()[:200]}"
        dev = self._expand("logs", "SVC=authelia", "ENV=dev")
        assert "kubelab-dev-config" not in dev, f"logs passed ENV=dev through: {dev.strip()[:200]}"
        assert NO_FLAG_TARGETS["logs"] in dev
        real = self._expand("logs", "SVC=authelia", "ENV=prod")
        assert "kubelab-prod-config" in real, f"logs ignored ENV=prod: {real.strip()[:200]}"

    @pytest.mark.parametrize("target", sorted(ENV_TARGETS))
    def test_an_unset_env_reaches_the_documented_default(self, target: str) -> None:
        flag, default = ENV_TARGETS[target]
        out = self._expand(target)
        assert f"{flag} {default}" in out, f"{target} with no ENV expanded to: {out.strip()[:200]}"

    @pytest.mark.parametrize("target", sorted(ENV_TARGETS))
    def test_a_nonsense_env_does_not_reach_the_command(self, target: str) -> None:
        """A distinct claim from the one above, and the one that shows `filter`
        is doing work rather than being a longer spelling of `or`: `dev` is not
        a target for any of these commands and must not be passed through."""
        flag, default = ENV_TARGETS[target]
        out = self._expand(target, "ENV=dev")
        assert f"{flag} dev" not in out, f"{target} passed ENV=dev through: {out.strip()[:200]}"
        assert f"{flag} {default}" in out

    @pytest.mark.parametrize("target", sorted(ENV_TARGETS))
    def test_a_real_env_is_honoured(self, target: str) -> None:
        """Without this, a target hardcoded to its default would pass both tests
        above while ignoring the operator entirely."""
        flag, default = ENV_TARGETS[target]
        other = "staging" if default == "prod" else "prod"
        out = self._expand(target, f"ENV={other}")
        assert f"{flag} {other}" in out, f"{target} ignored ENV={other}: {out.strip()[:200]}"
