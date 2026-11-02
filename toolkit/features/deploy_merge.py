"""Decide which open PRs the deploy merge step merges or closes (DELIVERY-004 AC6, #1619).

This is the merging actor's own condition. It judges and writes decisions; it
never merges. The merge is one line in .github/workflows/deploy-merge.yml, run
only when the switch is on, and tests/test_deploy_shape_widening.py pins that
line and the switch.

A PR is merged only when all of these hold at one head sha:

    the verdict, recomputed here from master's code, is `mechanical`
    every context branch protection requires reports a passing state
    GitHub reports the PR `clean`, or `unstable`: only a context that is not
    required fails there, and the line above already checked every required one
    the head is still that sha at the end of the judging

A PR is closed only when it has no changed files: there is nothing to merge,
and reopening it undoes the close. That is a content rule, so it applies to any
such PR, not only to the receiver's. Drafts are never touched.

Nothing here reads the branch name or the author.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from toolkit.features.branch_protection import load_declared
from toolkit.features.deploy_shape import MECHANICAL, Api, Declaration, evaluate
from toolkit.features.product_registry import Product

MERGE = "merge"
CLOSE = "close"
SKIP = "skip"

# A required context passes on these, as branch protection reads them.
_STATUS_OK = frozenset({"success"})
_CHECK_OK = frozenset({"success", "neutral", "skipped"})

# GitHub's mergeable_state values the merge accepts, as the merge button does.
# `unstable` came in after #2883 waited 6.5h on `add-to-project` hitting a rate
# limit (#1619). tests/test_deploy_shape_widening.py pins this set.
MERGE_STATES_OK = frozenset({"clean", "unstable"})


@dataclass(frozen=True)
class Decision:
    pr: int
    action: str
    reason: str
    head_sha: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def merge_enabled(registry: Path) -> bool:
    """True only when `mechanical.merge` is the boolean true. Any doubt is off."""
    try:
        block = json.loads(registry.read_text(encoding="utf-8")).get("mechanical")
    except (OSError, ValueError, AttributeError):
        return False
    return isinstance(block, dict) and block.get("merge") is True


def required_contexts(common_yaml: Path, repo: str, branch: str) -> tuple[str, ...]:
    """The contexts `ci.branch_protection` requires on `repo`@`branch`. KeyError if undeclared."""
    config = yaml.safe_load(common_yaml.read_text(encoding="utf-8"))
    return load_declared(config)[repo][branch].required_contexts


def _failing_contexts(api: Api, repo: str, sha: str, required: Iterable[str]) -> list[str]:
    """Each required context that is missing or not passing at `sha`, with its state.

    A context may be reported by a commit status, a check-run, or both. Every
    reporter must pass, so a red one is never outvoted by a green one. Of several
    runs of one check, the latest counts, as on the PR page.
    """
    statuses = api.json(f"repos/{repo}/commits/{sha}/status")["statuses"]
    runs = api.json(f"repos/{repo}/commits/{sha}/check-runs?per_page=100")["check_runs"]
    latest: dict[str, dict[str, Any]] = {}
    for r in sorted(runs, key=lambda r: r["id"]):
        latest[r["name"]] = r
    failing = []
    for context in required:
        reported = [s["state"] for s in statuses if s["context"] == context]
        run = latest.get(context)
        if not reported and run is None:
            failing.append(f"{context}: missing")
            continue
        failing += [f"{context}: {state}" for state in reported if state not in _STATUS_OK]
        if run is not None and (run["status"] != "completed" or run["conclusion"] not in _CHECK_OK):
            failing.append(f"{context}: {run['conclusion'] or run['status']}")
    return failing


def judge(
    number: int,
    repo: str,
    api: Api,
    decl: Declaration,
    products: Mapping[str, Product],
    required: Iterable[str],
) -> Decision:
    """Merge, close or skip PR `number`. Any failure to read is a skip."""
    try:
        pr = api.json(f"repos/{repo}/pulls/{number}")
        head = pr["head"]["sha"]
        if pr.get("draft") is not False:
            return Decision(number, SKIP, "a draft", head)
        if pr["base"]["ref"] != pr["base"]["repo"]["default_branch"]:
            return Decision(number, SKIP, "does not target the default branch", head)
        if api.json(f"repos/{repo}/pulls/{number}/files?per_page=100") == []:
            return Decision(number, CLOSE, "no changed files: nothing to merge", head)

        shape = evaluate(number, repo, api, decl, products)
        if shape.verdict != MECHANICAL or shape.head_sha != head:
            return Decision(number, SKIP, f"{shape.verdict}: {shape.reason}", shape.head_sha)
        failing = _failing_contexts(api, repo, head, required)
        if failing:
            return Decision(number, SKIP, f"required contexts not passing: {', '.join(failing)}", head)

        final = api.json(f"repos/{repo}/pulls/{number}")
        if final["head"]["sha"] != head:
            return Decision(number, SKIP, "the head moved while it was being judged", head)
        state = final.get("mergeable_state")
        if state not in MERGE_STATES_OK:
            return Decision(number, SKIP, f"merge state is {state!r}, not one of {sorted(MERGE_STATES_OK)}", head)
    except Exception as exc:  # noqa: BLE001 — a PR that cannot be read is not merged
        return Decision(number, SKIP, f"cannot judge: {exc!r}")
    return Decision(number, MERGE, f"{shape.reason}; every required context passing; {state}", head)
