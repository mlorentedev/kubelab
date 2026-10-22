"""Report a delivery workflow whose latest run never started (#1682, #1666's AC3).

A `startup_failure` creates no job. No job means no check run, which means no
annotation and nothing red on any commit or pull request. `staging-deploy.yml`
failed that way sixteen times out of sixteen between 2026-06-18 and 2026-08-25
and `apps/api/**` reached staging exactly never in those ten weeks, while every
pipeline anyone looked at was green. Measured on run `32815342422`:

    check-suites/88893127233/check-runs  -> total_count 0
    commits/dced2265/check-runs          -> length 0

GitHub's explanation of the failure exists only in the web UI and is not
reachable from the API at all. What *is* reachable is the verdict, on
`GET /actions/workflows/<file>/runs`. Nothing read it. This module does.

**Deliberately not "alert on any failed run."** An ordinary red run already
reports itself through checks and needs no second channel. The entire value here
is the one conclusion that reports itself nowhere.

Scope, derived rather than listed
---------------------------------
A workflow is watched when it is **unattended** — *no* path into it is gated by a
pull request — **and** it reaches `ci-publish.yml` or `toolkit deployment
promote` through an executable step.

The first half is a "no", not a "some": a workflow triggered by both `push` and
`pull_request` is attended, because a `startup_failure` there leaves a pull
request without its required contexts and branch protection refuses it. The
question is always *does anything else already report this*, never *does it touch
delivery*.

Both halves were arrived at by measurement, and both exclude something a simpler
rule got wrong:

* A `workflow_call`-only file has **no runs of its own**. Measured 2026-09-06:
  `ci-publish.yml` and `ci-pipeline.yml` both report `total_count: 0`, because a
  reusable workflow's jobs appear under its caller's run. #1682's AC1 originally
  listed `ci-publish.yml`; watching it would report "never ran" forever. It is
  also unnecessary — a reusable workflow cannot `startup_failure` on its own, it
  fails as *the caller's* `startup_failure`. That is exactly #1666, where
  `staging-deploy.yml` was refused over what `ci-publish.yml`'s job requested.
  Watching the callers is therefore both necessary and sufficient.

* Reading the file as text matches prose. A grep for `deployment promote`
  matched `pr-agent.yml`, where the string sits in a comment. Steps are read
  from the parsed document, and `uses:` is resolved to the called file.

`ci.yml` publishes transitively and runs on push, and is still **excluded**: it
produces the required `Validate` and `Detect Changes` contexts, so a
`startup_failure` there blocks the very next pull request. Its silence is bounded
by one PR rather than by ten weeks, which is the same reason
`review-attestation.yml` is out. The cut is "does anything else already make this
loud", not "does it touch delivery".

The watcher watches itself
--------------------------
`SELF` is in the watched set by name, because the predicate cannot reach it: a
checker that only reads other workflows is silent about its own
`startup_failure`, which would reproduce the defect it closes one level up. This
is the one hand-written entry and it is deliberate; `tests/` pins the reason so
it is not "tidied away" as an inconsistency later.

The verifier of delivery is named too
-------------------------------------
`deploy-verify.yml` (GITOPS-003) turns Argo CD's commit status into a red run on
master. It runs only on `status`, `schedule` and `workflow_dispatch`, so nothing
gated by a pull request ever runs it, and it publishes and promotes nothing, so
the predicate cannot reach it either. It is the compensating control for
unattended staging merges (#1619): if it stops starting, those merges go
unverified and nothing says so (#2614). `VERIFIERS` names it. Widening the
predicate to "verifies delivery" was rejected: no workflow declares that, so the
derivation would be a name match in disguise.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping

#: Triggers whose presence means a failure to start is ALREADY reported.
#: `workflow_call` produces no run at all — its jobs belong to the caller's run,
#: measured as `total_count: 0` on `ci-publish.yml` — so there is nothing to
#: read. A `pull_request` path is gated by branch protection, so a startup
#: failure surfaces as a pull request missing required contexts. One of these
#: anywhere in `on:` takes the workflow out of scope; see `is_unattended`.
ATTENDED_TRIGGERS = frozenset({"workflow_call", "pull_request", "pull_request_target"})

#: The reusable publisher. A workflow that reaches it can change what is
#: published, however many hops away.
PUBLISHER = "ci-publish.yml"

#: The command that changes what an environment runs.
PROMOTE = "deployment promote"

#: This checker's own workflow file. See the module docstring: the predicate
#: cannot derive it, and leaving it out would make the watcher the one delivery
#: workflow nothing watches.
SELF = "delivery-health.yml"

#: Workflows that verify delivery rather than perform it. See the module
#: docstring: unattended, reaching neither the publisher nor `promote`.
VERIFIERS = frozenset({"deploy-verify.yml"})

#: A run still executing reports `conclusion: null`. Measured on `ci.yml`. It is
#: not a verdict and must never be read as one.
IN_PROGRESS = None


class WorkflowError(Exception):
    """A workflow tree that could not be read well enough to answer."""


@dataclass(frozen=True)
class Verdict:
    """What the latest run of one workflow says about whether it starts."""

    workflow: str
    state: str
    detail: str

    @property
    def ok(self) -> bool:
        return self.state in {"healthy", "in_progress"}


def triggers(workflow: Mapping[Any, Any]) -> set[str]:
    """The `on:` keys of a parsed workflow.

    PyYAML resolves the unquoted key `on` to the boolean `True` (YAML 1.1), so a
    plain `workflow.get("on")` returns nothing for most real files. Getting this
    wrong makes every workflow look attended and the watched set empty — a
    check that passes by measuring nothing.

    The parameter is `Mapping[Any, Any]` rather than `dict[str, Any]` for that
    reason and no other: a parsed workflow genuinely has a non-string key, and
    mypy is right to refuse `dict[str, Any].get(True)`. Widening the annotation
    states the fact; a `# type: ignore` would have hidden the one surprise in
    this function.
    """
    raw = workflow.get("on", workflow.get(True))
    if raw is None:
        return set()
    if isinstance(raw, str):
        return {raw}
    if isinstance(raw, dict):
        return {str(k) for k in raw}
    return {str(k) for k in raw}


def is_unattended(workflow: dict[str, Any]) -> bool:
    """True when NO path into this workflow is gated by a pull request.

    Note the shape: it is not "has some trigger that isn't a pull request", it
    is "has *no* pull-request trigger at all". A workflow that runs on both
    `push` and `pull_request` cannot fail silently — a `startup_failure` there
    produces a pull request missing its required contexts, which branch
    protection then refuses to merge. Its silence is bounded by the next PR
    rather than by ten weeks.

    That distinction is the whole cut. `ci.yml` publishes transitively and runs
    on push, so the looser rule watches it; but it also runs on `pull_request`
    and produces the required `Validate` and `Detect Changes` contexts, so
    something already makes its failure loud. The question this module asks is
    "does anything else report this", never "does it touch delivery".
    """
    declared = triggers(workflow)
    return bool(declared) and not (declared & ATTENDED_TRIGGERS)


def _steps(workflow: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for job in (workflow.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        if "uses" in job:
            yield {"uses": job["uses"]}
        for step in job.get("steps") or []:
            if isinstance(step, dict):
                yield step


def _normalise(uses: str) -> str:
    """One key per referenced file, whatever the reference looked like.

    `./a/b.yml`, `a/b.yml` and `./a/./b.yml` are the same file to Actions but
    three different strings to a set.
    """
    return str(PurePosixPath(uses.split("@")[0]))


def reaches_delivery(
    workflow: dict[str, Any],
    resolve: Callable[[str], dict[str, Any] | None],
    _seen: frozenset[str] = frozenset(),
) -> bool:
    """Whether this workflow can publish an image or promote a deployment.

    Follows local `uses:` chains, so a caller two hops from the publisher still
    counts. `_seen` guards a cycle: workflows calling each other would otherwise
    recurse forever, and a delivery tree is not obviously acyclic.

    Reads the parsed document, never the file text — a text search matched
    `pr-agent.yml`, where `deployment promote` appears inside a comment
    explaining the delivery model.

    The cycle key is the NORMALISED path, not the raw `uses:` string. Every local
    reference in this repository carries the `./` prefix Actions requires, so two
    spellings of one file is theoretical here — but a guard keyed on spelling
    fails silently and recurses, and normalising costs one call.
    """
    for step in _steps(workflow):
        uses = step.get("uses")
        if isinstance(uses, str):
            if PUBLISHER in uses:
                return True
            key = _normalise(uses)
            if key in _seen:
                continue
            callee = resolve(uses)
            if callee is not None and reaches_delivery(callee, resolve, _seen | {key}):
                return True
        run = step.get("run")
        if isinstance(run, str) and PROMOTE in run:
            return True
    return False


def watched(
    load: Callable[[Path], dict[str, Any] | None],
    paths: Iterable[Path],
    resolve: Callable[[str], dict[str, Any] | None],
) -> list[str]:
    """The workflow filenames this check reads, derived from the tree.

    Sorted, and always including `SELF` and `VERIFIERS` — see the module docstring.
    """
    found = {SELF, *VERIFIERS}
    for path in paths:
        workflow = load(path)
        if not workflow:
            continue
        if is_unattended(workflow) and reaches_delivery(workflow, resolve):
            found.add(path.name)
    return sorted(found)


def classify(workflow: str, runs: list[dict[str, Any]]) -> Verdict:
    """Read the newest run's conclusion.

    `runs` is the `workflow_runs` array, newest first, already filtered to the
    window the caller asked about.
    """
    if not runs:
        return Verdict(
            workflow,
            "never_ran",
            "no run on record. Absence of a run is not evidence of health: the "
            "#1666 lane looked exactly like this for its first weeks.",
        )

    latest = runs[0]
    conclusion = latest.get("conclusion", IN_PROGRESS)
    url = latest.get("html_url", "")

    if conclusion == IN_PROGRESS:
        return Verdict(workflow, "in_progress", f"newest run is still executing. {url}")
    if conclusion == "startup_failure":
        return Verdict(
            workflow,
            "startup_failure",
            "the newest run never started, so it produced no job, no check run "
            f"and nothing red anywhere. The reason is in the web UI only: {url}",
        )
    return Verdict(workflow, "healthy", f"newest run concluded `{conclusion}`. {url}")


def fetch_runs(repo: str, workflow: str, before: str | None = None) -> list[dict[str, Any]]:
    """The runs of one workflow, newest first, through `gh api`.

    REST rather than GraphQL, deliberately: they are separate rate-limit buckets,
    and this repository has already had CI broken by an exhausted GraphQL quota
    (#1651). `created:<...` is GitHub's own filter, so `--before` narrows the
    query at the server instead of fetching everything and slicing — which is
    what makes AC4 answerable against history that has since been fixed.

    Raises `WorkflowError` on any transport failure. Never returns `[]` for a
    failed call: an empty list means "no runs", and this module reports that as a
    refusal, so conflating the two would turn an outage into a false alarm.
    """
    path = f"repos/{repo}/actions/workflows/{workflow}/runs?per_page=20"
    if before:
        path += f"&created=%3C{before}"
    try:
        proc = subprocess.run(["gh", "api", path], capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:  # pragma: no cover - environment
        raise WorkflowError("gh CLI not found") from exc
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        # A 404 is an ANSWER, not a transport failure: GitHub holds no record of
        # this workflow, so it has never run — which is exactly the state AC3
        # asks to be reported distinctly. Raising here instead would collapse
        # "the answer is none" into "I could not ask", and this module exists
        # because those two were already confused once.
        #
        # It is also how this file bootstraps: before it is merged, the remote
        # does not know it, so it reports itself as never having run. True, and
        # self-resolving on the first execution.
        if "404" in stderr or "Not Found" in stderr:
            return []
        raise WorkflowError(f"{workflow}: {stderr or proc.stdout.strip() or 'gh api failed'}")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"{workflow}: gh returned non-JSON: {proc.stdout[:200]}") from exc
    runs = payload.get("workflow_runs")
    if runs is None:
        raise WorkflowError(f"{workflow}: response has no `workflow_runs`")
    return runs


def worst(verdicts: list[Verdict]) -> int:
    """The exit code for a set of verdicts: 0 fine, 1 refused, 2 unanswerable.

    An empty set is **2**, not 0. A derivation that found nothing to watch has
    not established that everything is well — it has failed to ask, which is the
    shape of failure this whole ticket is about.
    """
    if not verdicts:
        return 2
    return 0 if all(v.ok for v in verdicts) else 1
