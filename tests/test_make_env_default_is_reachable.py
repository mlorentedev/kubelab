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

Use a filter form instead. Either of these, both already in this Makefile:

    --env $(or $(filter staging prod,$(ENV)),prod)            # backup, gitea-*
    $(eval _ENV := $(if $(filter staging prod,$(ENV)),$(ENV),staging))  # alerts

`filter` yields empty for any value that is not a real target for this command,
which does two things: it lets the default be selected, and it stops a nonsense
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
#: `[^,]+` and not `[a-z ]+`: the filter list is data, and narrowing the pattern
#: to the spellings that happen to exist today is how the literal it replaced got
#: it wrong in the first place. Both match the same 17 sites in the committed
#: Makefile -- measured, so this buys nothing now and costs nothing either. What
#: it buys is that a list containing a digit, a capital or a variable stays
#: visible instead of silently leaving the derived set.
#: TWO spellings, because the Makefile uses two and the `$(or` half alone left
#: `alerts` and `drill-pvc-unbound` invisible -- the latter added the day before
#: this guard, citing #1644 in its own comment, which is as close to a live
#: demonstration as the gap will get.
#:
#: The `$(if` arm insists the "then" branch is `$(ENV)` itself, and that is not
#: decoration. `$(if $(filter hub,$(ENV)),argocd,kubelab)` at Makefile:1596 and
#: :1603 selects a NAMESPACE, not an environment; a pattern loose enough to take
#: it would match a line that resolves nothing of the sort, and would then be
#: right about which targets to check for the wrong reason.
FILTER_FORM = re.compile(
    r"\$\(or\s+\$\(filter\s+[^,]+,\$\(ENV\)\)"
    r"|"
    r"\$\(if\s+\$\(filter\s+[^,]+,\$\(ENV\)\),\$\(ENV\),"
)

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
    # Invisible again until FILTER_FORM learned the `$(if ...)` spelling. The
    # second one is the whole argument for widening it: `drill-pvc-unbound` was
    # written the day before this guard, cites #1644 in its own comment, and was
    # still not covered by it.
    "alerts": ("--env", "prod"),
    "drill-pvc-unbound": ("--env", "staging"),
}

#: Resolves an environment but passes it under no flag at all, so the
#: `(flag, default)` model above cannot express it: `logs` interpolates the env
#: into a kubeconfig filename (`~/.kube/kubelab-$(_ENV)-config`).
#:
#: This is an EXEMPTION from the parametrised checks, and an exemption nothing
#: polices is a silencer. As first written it was exactly that: moving any real
#: target out of `ENV_TARGETS` and into this dict left every test green, because
#: `covers_every_site` unions the two and `@parametrize` binds `sorted(ENV_TARGETS)`
#: at collection time -- so the three expansion checks were simply never
#: generated for it. A target that reintroduced `--env dev` could have been
#: silenced by moving one line. Found in adversarial review, and it is the same
#: class as the defect this file exists to catch, reintroduced by its own fix.
#:
#: `TestTheExemptionCannotBeUsedAsASilencer` below now earns the word "declared":
#: membership here requires that the target genuinely passes no `--env`/`-e`
#: flag, checked against `make -n` rather than taken on trust.
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


class TestTheDerivationSeesWhatItClaims:
    """The pattern itself, exercised against lines it will never meet in this
    Makefile. `_targets_resolving_an_env` derives one side of an equality whose
    other side is a hand-written table; when the pattern is too narrow BOTH sides
    shrink together and the equality still holds, which is exactly how twelve
    sites read as complete while five were invisible. Only a direct test of the
    pattern can fail in that situation."""

    @pytest.mark.parametrize(
        "filter_list",
        [
            "staging prod",
            "staging prod hub",  # the four the old literal missed
            "staging prod hub dev",
            "$(DRIFT_ENVS)",  # a variable, not a literal list
            "staging prod gcp1",  # a digit
        ],
    )
    def test_any_filter_list_is_recognised(self, filter_list: str) -> None:
        line = f"\t@$(TOOLKIT) thing --env $(or $(filter {filter_list},$(ENV)),prod)"
        assert FILTER_FORM.search(line), f"a filter list of {filter_list!r} left the derived set"

    def test_the_broken_form_is_not_mistaken_for_the_fixed_one(self) -> None:
        """The floor. A pattern loose enough to match everything would make every
        test above pass while asserting nothing -- `$(or $(ENV),prod)` is the
        idiom this whole file exists to forbid, and it must NOT read as the fix."""
        assert not FILTER_FORM.search("\t@$(TOOLKIT) thing --env $(or $(ENV),prod)")


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
        # A NAMED floor before the counted one, because a count is the weaker
        # claim: trimming the table to match a narrowed pattern satisfies the
        # equality below, and that is not hypothetical -- it is what the blind
        # literal was doing. One site per spelling the pattern must recognise,
        # so a regression in FILTER_FORM fails here whatever the totals say.
        for site, spelling in (
            ("backup-coverage", "$(or $(filter staging prod,...))"),
            ("provision", "$(or $(filter staging prod hub,...))"),
            ("alerts", "$(if $(filter ...),$(ENV),...)"),
        ):
            assert site in found, f"FILTER_FORM no longer recognises {spelling} -- {site} left the derived set"
        # 15, and chosen against a specific regression rather than for headroom:
        # the blind literal derived exactly 12, so a floor of 12 would sit AT the
        # defective value and let a revert to it pass. Above 12, below today's 19.
        assert len(found) >= 15, f"expected the Makefile to resolve envs in >=15 targets, found {found}"
        covered = set(ENV_TARGETS) | set(NO_FLAG_TARGETS)
        assert found == covered, (
            f"ENV_TARGETS is out of step with the Makefile.\n"
            f"  in the Makefile but not tested: {sorted(found - covered)}\n"
            f"  tested but no longer present:   {sorted(covered - found)}"
        )

    def test_logs_reaches_its_default(self) -> None:
        """`logs` passes the resolved env under no flag -- it interpolates it
        into a kubeconfig filename -- so the `(flag, default)` rows cannot
        express it. That shape, and nothing else, is why it sits apart.

        An earlier version of this docstring claimed `logs` "needs SVC before
        its recipe expands at all". It does not: `make -n logs` with no SVC
        prints `test -n "" || (echo Usage...)` AND the kubectl line after it,
        because `make -n` expands a recipe without running its guard. `SVC` is
        passed below only to match how the target is really invoked."""
        out = self._expand("logs", "SVC=authelia")
        assert NO_FLAG_TARGETS["logs"] in out, f"logs with no ENV expanded to: {out.strip()[:200]}"
        dev = self._expand("logs", "SVC=authelia", "ENV=dev")
        assert "kubelab-dev-config" not in dev, f"logs passed ENV=dev through: {dev.strip()[:200]}"
        assert NO_FLAG_TARGETS["logs"] in dev
        real = self._expand("logs", "SVC=authelia", "ENV=prod")
        assert "kubelab-prod-config" in real, f"logs ignored ENV=prod: {real.strip()[:200]}"

    @pytest.mark.parametrize("target", sorted(NO_FLAG_TARGETS))
    def test_the_exemption_cannot_be_used_as_a_silencer(self, target: str) -> None:
        """Membership in NO_FLAG_TARGETS must be EARNED, not asserted.

        The dict exempts a target from the three expansion checks. Before this,
        nothing stopped a real flag-passing target being moved here: the union
        in `covers_every_site` still balanced, `@parametrize` binds
        `sorted(ENV_TARGETS)` at collection time so its checks were never
        generated, and the whole suite stayed green. One line could silence a
        target that had reintroduced `--env dev`.

        So the qualifying property is checked against `make -n`: a target that
        actually passes a flag does not belong here, and saying it does fails.
        """
        out = self._expand(target, "SVC=authelia")
        for flag in ("--env", "-e"):
            for env in ("staging", "prod", "dev", "hub"):
                assert f"{flag} {env}" not in out, (
                    f"{target} is exempted as flagless but passes `{flag} {env}`.\n"
                    f"  It belongs in ENV_TARGETS, where its default is verified.\n"
                    f"  Expanded to: {out.strip()[:200]}"
                )
        assert NO_FLAG_TARGETS[target] in out, (
            f"{target} is listed here but its recorded default "
            f"{NO_FLAG_TARGETS[target]!r} does not appear in its expansion"
        )

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
