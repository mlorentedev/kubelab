"""The delivery targets dispatch a workflow, and refuse before they dispatch.

`make promote-prod` and `make registry-prune` exist so that promoting a release
and pruning the registry stop being `gh workflow run` lines pasted from a chat
window. The Makefile's own comment at the Ansible section names that habit as
what these targets exist to remove.

`GH` is overridable, which is what makes them testable at all: substituting a
stub proves the argument handling without dispatching anything at a real
repository. Nothing here calls GitHub, and nothing here promotes anything.

The refusals matter more than the happy path. `make promote-prod APP=web
VERSION=v1.12.0` typed by a tired human would otherwise spin up a runner, check
out the repo, install poetry, and only then discover that the registry has no
tag called `v1.12.0`. It is also the case that the refusal must NOT be read as
the guard — promote-prod.yml validates authoritatively, because a dispatch can
arrive from `mlorentedev/web` where this Makefile never ran.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# The stub that replaces every command these recipes can reach. `echo` prints
# the arguments it was given, so a dispatch is observable as text and
# unobservable as an action.
STUB = "echo"

# GH is what the recipes actually use. POETRY and TOOLKIT are neutralised too,
# and that is not belt-and-braces — it is a measured requirement. Mutating the
# dispatch line to `$(TOOLKIT) deployment promote --env prod` while writing this
# file ran the real local promotion and rewrote `infra/config/values/prod.yaml`
# and the prod overlay in the working copy. The suite became an actor because a
# recipe changed under it. Overriding every command variable the Makefile
# defines means a future edit to these targets cannot do that again, whatever it
# changes them into.
STUBBED = ("GH", "POETRY", "TOOLKIT")

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed")


def _make(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["make", *args, *(f"{var}={STUB}" for var in STUBBED)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _dispatched(proc: subprocess.CompletedProcess[str]) -> bool:
    return "workflow run" in proc.stdout


# --- promote-prod -----------------------------------------------------------


def test_a_released_version_dispatches_the_promotion_workflow() -> None:
    proc = _make("promote-prod", "APP=web", "VERSION=1.12.0")
    assert proc.returncode == 0, proc.stderr
    assert (
        "workflow run promote-prod.yml --repo mlorentedev/kubelab "
        "-f app=web -f version=1.12.0"
    ) in proc.stdout, proc.stdout


def test_the_operator_is_told_that_nothing_deploys_yet() -> None:
    """ADR-046's gate is the point, and a target named `promote-prod` reads
    like it deploys. Whoever runs this must know a PR is waiting on them, or
    the promotion sits open exactly as unmerged as it was unremembered."""
    proc = _make("promote-prod", "APP=web", "VERSION=1.12.0")
    assert "until a human merges it" in proc.stdout


@pytest.mark.parametrize(
    "args",
    [
        ("promote-prod",),
        ("promote-prod", "APP=web"),
        ("promote-prod", "VERSION=1.12.0"),
    ],
)
def test_a_missing_argument_refuses_and_says_the_usage(args: tuple[str, ...]) -> None:
    proc = _make(*args)
    assert proc.returncode != 0
    assert "Usage: make promote-prod" in proc.stdout
    assert not _dispatched(proc), "a workflow was dispatched with an argument missing"


@pytest.mark.parametrize(
    "version",
    [
        "v1.12.0",  # the git tag; the registry tag has no `v`
        "latest",  # a mutable alias — prod pins immutable tags (ADR-046)
        "sha-f98a705",  # a staging tag; prod ships released semver
        "1.12",  # not a full triple
        "",  # empty reads as a missing argument, and must not dispatch either
    ],
)
def test_a_version_that_is_not_an_immutable_semver_tag_never_reaches_github(
    version: str,
) -> None:
    proc = _make("promote-prod", "APP=web", f"VERSION={version}")
    assert proc.returncode != 0, f"{version!r} was accepted"
    assert not _dispatched(proc), f"{version!r} was dispatched to a real workflow"


def test_an_app_the_platform_does_not_have_is_refused() -> None:
    """`errors` is a real image in this registry and is NOT promotable this way
    — it ships with the edge, not through the app promotion path. A typo that
    names it would otherwise reach the workflow and fail there."""
    proc = _make("promote-prod", "APP=errors", "VERSION=1.0.0")
    assert proc.returncode != 0
    assert "Unknown APP" in proc.stdout
    assert not _dispatched(proc)


def test_the_target_never_promotes_on_this_machine() -> None:
    """The recipe must dispatch, not run the toolkit locally.

    `toolkit deployment promote --env prod` here would edit the overlay in the
    working copy and stop, leaving a human to branch, commit and push a
    production change by hand — no PR, no required checks, and the ADR-046 gate
    bypassed by an operator who thought they were using the supported path.

    Asserted against what the target RAN, not against the text of the Makefile.
    An earlier version of this test sliced the recipe out with
    `read_text().split("promote-prod:", 1)[1].split("\\n\\n", 1)[0]` and matched
    strings in it, which PR-Agent flagged on `#1596` as brittle — and it was
    worse than brittle. Reformatting the recipe, adding a blank line inside it,
    or moving the local call one target down would all have left the assertion
    passing while the behaviour it names had changed. Every command the recipe
    can reach is stubbed, so its output IS the observation.
    """
    proc = _make("promote-prod", "APP=web", "VERSION=1.12.0")
    assert proc.returncode == 0, proc.stderr
    assert "workflow run promote-prod.yml" in proc.stdout, (
        f"promote-prod did not dispatch the workflow. It ran: {proc.stdout!r}"
    )
    assert "deployment promote" not in proc.stdout, (
        f"promote-prod invoked the toolkit's local promotion, which edits the prod "
        f"overlay in the working copy and opens no PR. It ran: {proc.stdout!r}"
    )


# --- registry-prune ---------------------------------------------------------


def test_prune_dispatches_the_janitor_in_delete_mode_by_default() -> None:
    proc = _make("registry-prune")
    assert proc.returncode == 0, proc.stderr
    assert "workflow run ci-cleanup.yml --repo mlorentedev/kubelab -f dry_run=false" in proc.stdout


def test_prune_passes_the_dry_run_flag_through() -> None:
    """`DRY_RUN=1` must reach the workflow as `true`, not as `1`.

    `ci-cleanup.yml` declares `dry_run` as a boolean; anything but the literal
    `true` is falsey there, so a value that merely looks set would delete tags
    while the operator believed they were listing them.
    """
    proc = _make("registry-prune", "DRY_RUN=1")
    assert proc.returncode == 0, proc.stderr
    assert "-f dry_run=true" in proc.stdout
    assert "(dry run)" in proc.stdout, "the operator is not told which mode this is"


def test_ci_cleanup_triggers_on_promotions_to_staging_and_prod() -> None:
    """The janitor must run on every promotion push to master (ADR-046)."""
    import yaml

    workflow_path = REPO_ROOT / ".github" / "workflows" / "ci-cleanup.yml"
    with open(workflow_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    triggers = data.get("on") or data.get(True) or {}
    assert "push" in triggers
    push = triggers["push"]
    assert push.get("branches") == ["master"]
    assert "infra/config/values/prod.yaml" in push.get("paths", [])
    assert "infra/config/values/staging.yaml" in push.get("paths", [])


# --- discoverability --------------------------------------------------------


def test_both_targets_are_listed_in_make_help() -> None:
    """A target nobody can find is a `gh workflow run` line with extra steps."""
    proc = subprocess.run(  # noqa: S603
        ["make", "help"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0
    assert "make promote-prod APP=x VERSION=y" in proc.stdout
    assert "make registry-prune" in proc.stdout
