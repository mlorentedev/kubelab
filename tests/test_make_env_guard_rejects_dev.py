"""A `make` target that prints a usage line must be able to reach it.

`ENV ?= dev` is set globally, so `$(ENV)` is never empty. `test -n "$(ENV)"`
therefore always succeeds, the usage message beneath it is unreachable, and the
target proceeds against `dev` -- silently, and under a guard that reads as
protection (#1670).

Eighteen targets were in that state, including `deploy`, `deploy-k8s`,
`bootstrap-k8s`, `apply-secrets`, `backup-pvc` and `flush-sessions`.

**The repo already knew, in a place nobody editing those targets could see.**
`config-check-drift` carries a comment spelling out exactly why the idiom cannot
work -- written when #1118 reached CI behind it -- and it was written at the one
site that got fixed. The same shape as #1644, whose explanation lived in a
comment on `alerts` while eight other targets repeated the bug. That is why this
is a test whose failure message carries the reasoning, and not eighteen edits:
the only place this has ever needed to be is in front of the person reintroducing
it, at the moment they do.

Sibling of `test_make_env_default_is_reachable.py`, which guards the `$(or
$(ENV),prod)` half of the same root cause. The two share a shape and will share
helpers once both have landed; they are separate files today only because they
were written on parallel branches.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
MAKEFILE = REPO_ROOT / "Makefile"

#: The dead guard. `$(ENV)` is never empty, so `test -n` cannot fail.
DEAD_GUARD = re.compile(r'test -n "\$\(ENV\)"')

#: The working form: filter first, so a value that is not a real target for this
#: command yields empty and `test -n` finally has something to fail on.
LIVE_GUARD = re.compile(r'test -n "\$\(filter \$\(ENV\),[a-z ]+\)"')

WHY = """
`ENV ?= dev` is set globally, so $(ENV) is never empty and `test -n "$(ENV)"`
can never fail. The usage message under it is unreachable and the target runs
against `dev` while claiming to require an environment.

Filter the value against the environments this target actually accepts:

    @test -n "$(filter $(ENV),staging prod)" || (echo "Usage: ..." && exit 1)

`filter` yields empty for anything else -- including the repo-wide `dev`
default -- so the guard fails and the usage line is reached. See #1670, and
#1644 for the same root cause in `$(or $(ENV),<default>)`.
"""


def _recipe_lines() -> list[tuple[str, int, str]]:
    """(target, line number, text) for lines Make will expand and run.

    Comments are excluded, and that is load-bearing rather than tidy: three
    comments in this Makefile quote the dead guard in order to WARN about it,
    and the first audit for this ticket counted all three as instances --
    attributing one to whichever target happened to precede it. A guard that
    cannot tell a warning from an instance would forbid the repo from
    documenting its own bug, and would also miscount it (lesson-432).
    """
    out: list[tuple[str, int, str]] = []
    target = None
    for n, line in enumerate(MAKEFILE.read_text().splitlines(), start=1):
        m = re.match(r"^([a-zA-Z0-9_-]+):", line)
        if m:
            target = m.group(1)
        elif line.startswith("\t") and not line.lstrip().startswith("#") and target:
            out.append((target, n, line))
    return out


#: Every target whose ENV guard must bite, and one env it does accept.
#: Derived from the Makefile by `test_the_table_covers_every_guarded_target`,
#: so a new guarded target cannot appear without being listed.
GUARDED: dict[str, str] = {
    "unregister-spoke": "staging",
    "rotate-spoke-token": "staging",
    "deploy": "staging",
    "backup-pvc": "prod",
    "sync-oidc-hashes": "staging",
    "sync-vikunja": "staging",
    "provision-postgres-tenant": "staging",
    "configure-oidc": "staging",
    "apply-secrets": "staging",
    "restart-service": "staging",
    "apply-middleware-secrets": "staging",
    "import-n8n": "staging",
    "notify-smoke": "staging",
    "alert-smoke": "staging",
    "flush-sessions": "staging",
    "pods": "staging",
    "deploy-k8s": "staging",
    "bootstrap-k8s": "staging",
}

#: Carries the dead guard and is safe anyway: a second guard,
#: `case "$(ENV)" in staging|prod)`, rejects the value. Named rather than
#: silently excluded -- it is the one site in nineteen that behaves differently
#: from the pattern, and an audit that assumed uniformity would have been wrong
#: about it.
PROTECTED_BY_A_SECOND_GUARD = {"register-spoke"}


class TestTheDeadGuardIsGone:
    def test_the_scan_reads_a_real_makefile(self) -> None:
        """Floor. An empty expectation is not a weak expectation: it matches
        everything, and every assertion below would pass against a file this
        scan failed to parse (lesson-416)."""
        lines = _recipe_lines()
        assert len(lines) >= 200, f"expected a substantial Makefile, parsed {len(lines)} recipe lines"
        assert any("$(TOOLKIT)" in text for _t, _n, text in lines)

    def test_the_scan_would_still_recognise_the_idiom_it_bans(self) -> None:
        """If DEAD_GUARD stopped matching, the assertion below would pass
        vacuously against a Makefile full of the bug."""
        assert DEAD_GUARD.search('\t@test -n "$(ENV)" || (echo "Usage: ..." && exit 1)')
        assert not DEAD_GUARD.search('\t@test -n "$(filter $(ENV),staging prod)" || (echo "Usage" && exit 1)')
        assert not DEAD_GUARD.search('\t@test -n "$(SVC)" || (echo "Usage" && exit 1)')

    def test_a_comment_quoting_the_idiom_is_not_an_instance(self) -> None:
        """The three comments documenting this defect must not be reported as
        occurrences of it -- and the ticket for this work was filed with the
        wrong count for exactly that reason."""
        quoted = [
            n
            for n, line in enumerate(MAKEFILE.read_text().splitlines(), start=1)
            if DEAD_GUARD.search(line) and not line.startswith("\t")
        ]
        assert quoted, "expected the Makefile to still explain this defect in prose somewhere"
        recipe_line_numbers = {n for _t, n, _text in _recipe_lines()}
        assert not set(quoted) & recipe_line_numbers

    def test_no_recipe_line_uses_it(self) -> None:
        offenders = [
            (t, n, text.strip())
            for t, n, text in _recipe_lines()
            if DEAD_GUARD.search(text) and t not in PROTECTED_BY_A_SECOND_GUARD
        ]
        assert not offenders, (
            "Makefile targets guard ENV with a test that cannot fail:\n"
            + "\n".join(f"  {t} (line {n}): {text}" for t, n, text in offenders)
            + "\n"
            + WHY
        )


class TestTheTableTracksTheMakefile:
    def test_the_table_covers_every_guarded_target(self) -> None:
        found = {t for t, _n, text in _recipe_lines() if LIVE_GUARD.search(text)}
        # NAMED floor before the counted one. A count is satisfied by trimming
        # the table to match a scan that has narrowed, which is how the sibling
        # guard in #1647 came to assert less than it appeared to. These three
        # are the ones whose failure would matter most.
        for site in ("deploy", "deploy-k8s", "apply-secrets"):
            assert site in found, f"{site} no longer carries a filtered ENV guard"
        assert len(found) >= 15, f"expected >=15 filtered guards, found {len(found)}: {sorted(found)}"
        assert found == set(GUARDED), (
            "GUARDED is out of step with the Makefile.\n"
            f"  guarded in the Makefile but untested: {sorted(found - set(GUARDED))}\n"
            f"  tested but no longer guarded:         {sorted(set(GUARDED) - found)}"
        )


class TestTheGuardBites:
    """Expansion is not enough here, and the difference matters.

    `make -n` prints a recipe WITHOUT running its guard, so it shows what the
    guard expands to and never whether it fails. Running the target for real
    would prove it and would also run a deploy if the fix were wrong. So the
    expanded guard line is executed on its own: it is
    `test ... || (echo Usage && exit 1)` and nothing else.
    """

    @staticmethod
    def _other_required_vars(target: str) -> list[str]:
        """Variables the target guards besides ENV.

        Several targets carry more than one guard sharing a single usage
        message -- `deploy` guards TARGET and ENV, `restart-service` guards SVC
        and ENV. Without supplying those, this would be running the TARGET
        guard and reading its refusal as a verdict about ENV.
        """
        return [
            var
            for t, _n, text in _recipe_lines()
            if t == target
            for var in re.findall(r'test -n "\$\((\w+)\)"', text)
            if var != "ENV"
        ]

    @classmethod
    def _guards_pass(cls, target: str, *env: str) -> bool:
        extra = [f"{v}=placeholder" for v in cls._other_required_vars(target)]
        out = subprocess.run(
            ["make", "-n", target, *extra, *env],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        ).stdout
        guards = [ln for ln in out.splitlines() if ln.startswith("test ") and f"make {target} " in ln]
        assert guards, f"{target}: no guard line found in its expansion"
        return all(subprocess.run(["sh", "-c", ln], capture_output=True).returncode == 0 for ln in guards)

    @pytest.mark.parametrize("target", sorted(GUARDED))
    def test_a_bare_invocation_is_refused(self, target: str) -> None:
        """The bug itself: no ENV given, `ENV ?= dev` fills it in, and the
        target used to proceed."""
        assert not self._guards_pass(target), f"{target} accepts a bare invocation and will run against dev"

    @pytest.mark.parametrize("target", sorted(GUARDED))
    def test_an_explicit_dev_is_refused(self, target: str) -> None:
        """A distinct claim from the one above: `ENV=dev` is command-line
        origin, so a guard checking provenance rather than value would pass it."""
        assert not self._guards_pass(target, "ENV=dev"), f"{target} accepts ENV=dev"

    @pytest.mark.parametrize("target", sorted(GUARDED))
    def test_its_own_environment_is_still_accepted(self, target: str) -> None:
        """Without this, a guard that refused everything would satisfy both
        tests above while making the target unusable."""
        assert self._guards_pass(target, f"ENV={GUARDED[target]}"), (
            f"{target} refuses {GUARDED[target]!r}, which its own usage line offers"
        )
