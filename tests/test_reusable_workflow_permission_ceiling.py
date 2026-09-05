"""A called workflow cannot request a permission its caller does not hold.

The caller's `permissions:` block is a CEILING, not a starting point. Declaring
one sets every scope it does not name to `none`, and a nested job that asks for
more is refused — not at run time, but when the run is created:

    Invalid workflow file: .github/workflows/staging-deploy.yml#L46
    Error calling workflow '.../ci-publish.yml@dced2265'. The nested job
    'docker-build-push' is requesting 'security-events: write', but is only
    allowed 'security-events: none'.

That is a `startup_failure`, and a `startup_failure` is the quietest failure
GitHub has. The run creates no job, so the check suite has no check runs, so
there are no annotations on the commit and nothing goes red on a pull request or
in the Actions list beyond one grey cross nobody subscribes to. Measured
2026-09-05 on run 32815342422: `GET /check-suites/88893127233/check-runs` returns
`total_count: 0`, and so does `GET /commits/dced2265/check-runs`. The message
above exists only in the web UI.

Measured on #1666: `staging-deploy.yml` — the whole staging lane for `api` — ran
sixteen times between 2026-06-18 and 2026-08-25 and failed at startup all
sixteen. `apps/api/**` had not reached staging once in ten weeks, and no job, no
check and no alert ever said so.

## Why a test rather than a lint

`actionlint` reports nothing here, and it is right not to: each file is valid on
its own. The defect is a RELATION between two files — what the caller grants
against what the callee's job asks — so a single-file linter is structurally
blind to it. The fix was already in this repository, too: `release.yml` calls the
same `ci-publish.yml` and grants `security-events: write`. It had been correct for
months and never propagated, because nothing asserted the relation.

## What the guard deliberately does not check

A caller that declares no `permissions:` at all inherits the repository's default
token scope, which is a repository setting and not readable from the tree. Those
callers are SKIPPED rather than assumed permissive — inventing a default would
either wave through a real violation or invent one. `ci-pipeline.yml` is such a
caller, and it is exactly why it has always worked while `staging-deploy.yml`
never did: it never declared a ceiling to fall short of.
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = REPO / ".github/workflows"

# GitHub's three levels, ordered. A request is a violation when it exceeds what
# the ceiling grants for the same scope.
LEVELS = {"none": 0, "read": 1, "write": 2}


def _load(path: pathlib.Path) -> dict[str, Any] | None:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _levels(block: Any) -> dict[str, int] | None:
    """Normalise a `permissions:` block to {scope: level}, or None if absent.

    The shorthands matter: `write-all` and `read-all` set every scope at once, so
    they are represented by a wildcard entry that `_granted` reads.
    """
    if block is None:
        return None
    if isinstance(block, str):
        if block in ("write-all", "read-all"):
            return {"*": LEVELS[block.split("-")[0]]}
        # `permissions: none` is not valid YAML-wise as a scalar in the schema,
        # but treat any other scalar as granting nothing rather than guessing.
        return {"*": 0}
    if isinstance(block, dict):
        # An empty mapping is the documented way to say "no permissions at all".
        return {str(k): LEVELS.get(str(v), 0) for k, v in block.items()}
    return None


def _name(level: int) -> str:
    return next(k for k, v in LEVELS.items() if v == level)


def _granted(ceiling: dict[str, int], scope: str) -> int:
    """What the caller actually grants for one scope.

    An explicit mapping that does not name a scope grants `none` for it. That
    single rule is the whole defect: `contents: write, pull-requests: write` reads
    like "generous" and means "and `security-events: none`".
    """
    if "*" in ceiling:
        return ceiling["*"]
    return ceiling.get(scope, 0)


def _local_callee(uses: Any) -> pathlib.Path | None:
    """Resolve `uses: ./.github/workflows/x.yml` to a path.

    A cross-repository call (`org/repo/.github/workflows/x.yml@ref`) is not
    resolvable from this tree and is skipped; there are none today, and one
    appearing is a reason to extend this, not a silent pass.
    """
    if not isinstance(uses, str) or not uses.startswith("./"):
        return None
    return REPO / uses[2:]


def _violations_in(
    workflow: dict[str, Any],
    resolve: Any,
    label: str = "",
) -> list[str]:
    """Every nested request that exceeds its caller's ceiling.

    `resolve` maps a job's `uses:` value to the called workflow dict (or None),
    so the synthetic table below can supply callees without touching the disk.
    """
    found: list[str] = []
    workflow_ceiling = _levels(workflow.get("permissions"))

    for job_name, job in (workflow.get("jobs") or {}).items():
        if not isinstance(job, dict) or "uses" not in job:
            continue
        callee = resolve(job["uses"])
        if callee is None:
            continue

        # A job-level block overrides the workflow-level one entirely.
        ceiling = _levels(job.get("permissions"))
        if ceiling is None:
            ceiling = workflow_ceiling
        if ceiling is None:
            # Undeclared: the repository default applies and is not in the tree.
            continue

        for callee_job_name, callee_job in (callee.get("jobs") or {}).items():
            if not isinstance(callee_job, dict):
                continue
            requested = _levels(callee_job.get("permissions"))
            if not requested:
                continue

            def _report(scope: str, level: int, allowed: int) -> None:
                found.append(
                    f"{label}{job_name} -> {job['uses']}: nested job "
                    f"'{callee_job_name}' requests '{scope}: {_name(level)}', "
                    f"but the caller only allows '{scope}: {_name(allowed)}'"
                )

            if "*" in requested:
                # `write-all` / `read-all` in the CALLEE asks for that level on
                # every scope there is, so it clears a ceiling only when the
                # ceiling is itself a blanket at least as high. Against an
                # explicit mapping it always overreaches: the mapping names a
                # finite set and leaves the rest at `none`. Without this branch
                # a callee could say `write-all` and be waved through, which is
                # the one shape that asks for the most.
                level = requested["*"]
                allowed = ceiling.get("*", 0)
                if level > allowed:
                    _report("every scope", level, allowed)
                continue

            for scope, level in requested.items():
                if level > _granted(ceiling, scope):
                    _report(scope, level, _granted(ceiling, scope))
    return found


def _callers() -> list[tuple[pathlib.Path, dict[str, Any]]]:
    found = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        workflow = _load(path)
        if not workflow:
            continue
        if any(
            isinstance(job, dict) and _local_callee(job.get("uses"))
            for job in (workflow.get("jobs") or {}).values()
        ):
            found.append((path, workflow))
    return found


#: The callers the guard below is known to cover. Named rather than counted:
#: a count is satisfied by any N files, so deleting the one this whole change
#: exists for and adding an unrelated caller keeps it green while the coverage
#: is gone. Membership is asserted; the set is deliberately not exact, because a
#: NEW caller is picked up by the guard automatically and needs no edit here —
#: what must never happen silently is one of these LEAVING.
#:
#: Four, not three, and the difference is why the count was the wrong assertion.
#: `ci-publish.yml` has three callers (`ci-pipeline`, `release`, `staging-deploy`
#: — the set #1666 and lesson-439 are about). This scan is broader: it finds
#: every caller of ANY local reusable workflow, which also catches `ci.yml`
#: calling `ci-pipeline.yml`. A floor of 3 measured against a population of 4
#: had one full unit of slack in it: `staging-deploy.yml` could have vanished
#: today and the assertion would still have passed with three.
KNOWN_CALLERS = {
    "ci-pipeline.yml",
    "ci.yml",
    "release.yml",
    "staging-deploy.yml",
}


def test_the_scan_finds_the_workflows_that_call_a_reusable_one():
    """Without this, a moved directory turns the assertion below into a pass.

    `staging-deploy.yml` is the one #1666 was about, and the reason this asserts
    names instead of a number.
    """
    scanned = {path.name for path, _ in _callers()}
    missing = KNOWN_CALLERS - scanned
    assert not missing, (
        f"{sorted(missing)} no longer scan as callers of a local reusable workflow. "
        f"Found {sorted(scanned) or 'nothing'} under {WORKFLOWS}. Either the file "
        "was removed or renamed — update KNOWN_CALLERS deliberately — or the scan "
        "went blind, in which case the guard below is asserting nothing."
    )


def test_no_nested_job_requests_more_than_its_caller_grants():
    """The guard proper. Red on `staging-deploy.yml` before #1666's fix."""
    offenders: list[str] = []
    for path, workflow in _callers():
        offenders += _violations_in(
            workflow,
            resolve=lambda uses: (
                _load(p) if (p := _local_callee(uses)) and p.exists() else None
            ),
            label=f"{path.name}::",
        )

    assert not offenders, (
        "these reusable-workflow calls are refused by GitHub when the run is "
        "created, which produces a startup_failure — no jobs, no check runs, "
        "nothing red:\n  " + "\n  ".join(offenders) + "\n\nA caller's "
        "`permissions:` block is a ceiling: every scope it does not name is "
        "`none`. Grant the scope in the caller (see release.yml), or stop "
        "requesting it in the called workflow's job."
    )


# --- the semantics, pinned on synthetic pairs --------------------------------
# (name, caller, callee, expected violations)

_CALLEE_ASKS_SECURITY_EVENTS = {
    "jobs": {"docker-build-push": {"permissions": {"contents": "read", "security-events": "write"}}}
}

_TABLE: list[tuple[str, dict[str, Any], dict[str, Any], int]] = [
    (
        "the #1666 shape: an explicit ceiling that omits the requested scope",
        {
            "permissions": {"contents": "write", "pull-requests": "write"},
            "jobs": {"build-api": {"uses": "./.github/workflows/ci-publish.yml"}},
        },
        _CALLEE_ASKS_SECURITY_EVENTS,
        1,
    ),
    (
        "release.yml's shape: the ceiling names the scope",
        {
            "permissions": {
                "contents": "write",
                "pull-requests": "write",
                "security-events": "write",
            },
            "jobs": {"publish": {"uses": "./.github/workflows/ci-publish.yml"}},
        },
        _CALLEE_ASKS_SECURITY_EVENTS,
        0,
    ),
    (
        "ci-pipeline.yml's shape: no ceiling declared, so nothing is knowable",
        {"jobs": {"call-publish": {"uses": "./.github/workflows/ci-publish.yml"}}},
        _CALLEE_ASKS_SECURITY_EVENTS,
        0,
    ),
    (
        "read where write is asked for is still short",
        {
            "permissions": {"security-events": "read"},
            "jobs": {"j": {"uses": "./.github/workflows/x.yml"}},
        },
        # One scope, so the count isolates the level comparison rather than
        # also counting the `contents` shortfall the two-scope callee has.
        {"jobs": {"n": {"permissions": {"security-events": "write"}}}},
        1,
    ),
    (
        "write where read is asked for is fine",
        {
            "permissions": {"contents": "write"},
            "jobs": {"j": {"uses": "./.github/workflows/x.yml"}},
        },
        {"jobs": {"n": {"permissions": {"contents": "read"}}}},
        0,
    ),
    (
        "a job-level ceiling overrides the workflow-level one, for better",
        {
            "permissions": {"contents": "read"},
            "jobs": {
                "j": {
                    "uses": "./.github/workflows/x.yml",
                    "permissions": {"security-events": "write"},
                }
            },
        },
        _CALLEE_ASKS_SECURITY_EVENTS,
        # contents:read is gone with the workflow-level block it came from, so
        # the callee's `contents: read` is now the violation instead.
        1,
    ),
    (
        "write-all grants every scope",
        {
            "permissions": "write-all",
            "jobs": {"j": {"uses": "./.github/workflows/x.yml"}},
        },
        _CALLEE_ASKS_SECURITY_EVENTS,
        0,
    ),
    (
        "read-all does not grant write",
        {
            "permissions": "read-all",
            "jobs": {"j": {"uses": "./.github/workflows/x.yml"}},
        },
        _CALLEE_ASKS_SECURITY_EVENTS,
        1,
    ),
    (
        "an empty mapping grants nothing at all",
        {"permissions": {}, "jobs": {"j": {"uses": "./.github/workflows/x.yml"}}},
        _CALLEE_ASKS_SECURITY_EVENTS,
        2,
    ),
    (
        "a callee job that requests nothing inherits, and cannot overreach",
        {
            "permissions": {"contents": "read"},
            "jobs": {"j": {"uses": "./.github/workflows/x.yml"}},
        },
        {"jobs": {"n": {"runs-on": "ubuntu-latest"}}},
        0,
    ),
    (
        "two scopes short in one nested job are two violations",
        {
            "permissions": {"pull-requests": "write"},
            "jobs": {"j": {"uses": "./.github/workflows/x.yml"}},
        },
        _CALLEE_ASKS_SECURITY_EVENTS,
        2,
    ),
    (
        "a callee asking write-all overreaches any explicit ceiling",
        {
            "permissions": {"contents": "write", "security-events": "write"},
            "jobs": {"j": {"uses": "./.github/workflows/x.yml"}},
        },
        {"jobs": {"n": {"permissions": "write-all"}}},
        1,
    ),
    (
        "a callee asking read-all also overreaches an explicit ceiling",
        {
            "permissions": {"contents": "write"},
            "jobs": {"j": {"uses": "./.github/workflows/x.yml"}},
        },
        {"jobs": {"n": {"permissions": "read-all"}}},
        1,
    ),
    (
        "write-all under write-all is fine, and so is read-all under it",
        {"permissions": "write-all", "jobs": {"j": {"uses": "./.github/workflows/x.yml"}}},
        {"jobs": {"n": {"permissions": "write-all"}, "m": {"permissions": "read-all"}}},
        0,
    ),
    (
        "write-all under read-all is not",
        {"permissions": "read-all", "jobs": {"j": {"uses": "./.github/workflows/x.yml"}}},
        {"jobs": {"n": {"permissions": "write-all"}}},
        1,
    ),
    (
        "a step-level `uses:` is not a workflow call",
        {
            "permissions": {},
            "jobs": {"j": {"steps": [{"uses": "actions/checkout@v7"}]}},
        },
        _CALLEE_ASKS_SECURITY_EVENTS,
        0,
    ),
]


@pytest.mark.parametrize("name,caller,callee,expected", _TABLE, ids=[r[0] for r in _TABLE])
def test_the_ceiling_semantics(
    name: str, caller: dict[str, Any], callee: dict[str, Any], expected: int
) -> None:
    """Counts, not just "zero for the clean cases".

    Asserting the number in both directions is what stops a loosened comparison
    from turning the safe rows green for the wrong reason.
    """
    found = _violations_in(caller, resolve=lambda _: callee)
    assert len(found) == expected, f"{name}: expected {expected}, got {found}"


def test_a_cross_repository_call_is_skipped_rather_than_guessed_at() -> None:
    """It cannot be resolved from this tree; there are none today."""
    assert _local_callee("org/repo/.github/workflows/x.yml@main") is None
    assert _local_callee("./.github/workflows/ci-publish.yml") is not None
