"""Set a single issue's board fields by name (TOOL-046, #1468).

The board already has bulk governance passes — `board streams`, `board sweep`,
`board priority` — each driven by a registry under `harness/` and each operating
over many issues. None of them covers the operation that happens most often: a
ticket was just filed, give it a Status, a Priority and a Stream.

So it was being done with a raw GraphQL mutation carrying pasted node IDs
(`PVTSSF_lAHOAM7xJs4BZ6GYzhU1dxM`, `224db21f`), which is four standing-order
violations at once: an ad-hoc command where a codified path belongs, hardcoded
values with no SSOT, no idempotence story, and a manual step. The real cost is
that it gets **skipped** — GOV-005 (#1417) had to sweep 28 issues into a correct
Status and assign a priority to 135, because nothing set them at filing time.

Everything here resolves by NAME. The caller writes `P2` and
`Security & Identity`; option ids are looked up from the project itself, which
is also what makes them SSOT rather than pasted — the project is the authority
on its own fields, and a renamed option surfaces as an error listing the valid
ones instead of a silently wrong write.

`plan` is pure and is where idempotence lives: it returns only the fields whose
current value differs from the desired one, so a re-run with the same arguments
produces no mutation at all rather than a write that happens to be a no-op.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from toolkit.core import gh_graphql


class GitHubError(Exception):
    """`gh api graphql` failed or returned errors."""


class UnknownOptionError(Exception):
    """A field value that the project does not define. Carries the valid ones."""


@dataclass(frozen=True)
class FieldInfo:
    field_id: str
    options: dict[str, str]  # option name -> option id


@dataclass(frozen=True)
class ItemState:
    """One issue's project item, its single-select values, and whether it is still open.

    `issue_state` and `closed_at` are read LIVE from the API rather than taken
    from a workflow's event payload, which is the whole of TOOL-053 (#1504). A
    re-run replays the payload as it was when the event fired, so a gate written
    as `if: github.event.issue.state == 'open'` judges the issue as it was, not
    as it is -- and on 2026-08-31 that put #1494 back In Progress 38 minutes
    after it closed.
    """

    item_id: str
    number: int
    values: dict[str, str]  # field name -> current option name
    #: "OPEN", "CLOSED", or whatever the API returns. Defaulted so existing
    #: callers and fixtures keep working; anything not "OPEN" is treated as
    #: closed by `guard_closed`, deliberately.
    issue_state: str = "OPEN"
    closed_at: str | None = None


@dataclass(frozen=True)
class Change:
    field: str
    before: str | None
    after: str

    def __str__(self) -> str:
        return f"{self.field}: {self.before or '(unset)'} -> {self.after}"


#: The one write that must not land on a closed issue. Every other field --
#: Priority, Stream, even Status -> Done -- stays legitimate after closure,
#: because a board you cannot repair once a ticket closes is worse than one that
#: occasionally lies. #1494's own correction was In Progress -> Done, and a guard
#: refusing all writes would have blocked the fix as well as the mistake.
GUARDED_STATUS = "In Progress"

#: What to do when the guard fires. Two callers, two right answers, and the
#: distinction is the reason this is an option rather than a constant.
ON_CLOSED_CHOICES = ("fail", "skip")


@dataclass(frozen=True)
class Guard:
    """A decision about whether a write may proceed, and the sentence explaining it."""

    action: str  # "proceed" | "refuse" | "skip"
    message: str = ""


def guard_closed(state: ItemState, desired: dict[str, str], on_closed: str) -> Guard:
    """Refuse to move a CLOSED issue back to In Progress (TOOL-053, #1504).

    Observed 2026-08-31 on #1494: the workflow's only gate was
    `if: github.event.issue.state == 'open'`, read from the **event payload**. A
    re-run replays the payload as it was when the event fired, so the job at
    02:28 believed an issue closed at 01:50:16Z was still open and wrote
    `In Progress` onto a finished ticket. The board then claimed work that had
    ended 38 minutes earlier.

    Same class as dotfiles' BUG-066. The remedy is not a better guard clause on
    the payload -- it is to read the state live and decide HERE, where a test can
    execute the decision. A gate expressed in workflow YAML is not testable and
    is exactly what failed.

    IT READS THE REQUEST, NOT THE PLAN. `plan()` returns nothing when Status
    already holds In Progress, so a guard derived from planned changes would let
    a re-run sail through on an issue that was moved In Progress while open and
    closed afterwards -- reporting success while doing the wrong thing for the
    right reason.

    FAILS CLOSED ON AN UNKNOWN STATE. Anything the API returns that is not
    "OPEN" counts as closed. The cost of being wrong that way is a refused write
    and a human reading a message; the other way it is a stale board nobody
    trusts, which is the failure this exists to prevent.
    """
    if on_closed not in ON_CLOSED_CHOICES:
        # Validated before anything else so `--on-closed maybe` cannot fall
        # through to the permissive branch on an open issue and look supported.
        raise ValueError(f"on_closed must be one of {', '.join(ON_CLOSED_CHOICES)}, got {on_closed!r}")

    if state.issue_state == "OPEN":
        return Guard(action="proceed")

    if desired.get("Status") != GUARDED_STATUS:
        return Guard(action="proceed")

    closed = f" (closed {state.closed_at})" if state.closed_at else ""
    reason = f"issue #{state.number} is {state.issue_state}{closed}; refusing to set Status to {GUARDED_STATUS}"

    if on_closed == "skip":
        return Guard(action="skip", message=f"{reason} — nothing to do")
    return Guard(action="refuse", message=reason)


def plan(state: ItemState, desired: dict[str, str]) -> tuple[Change, ...]:
    """The changes needed to reach `desired`. Pure — this is the idempotence.

    A field already holding its desired value produces no Change, so a second
    run writes nothing. That is a stronger property than a write that happens
    to be a no-op: no mutation is sent, so a re-run costs one read and cannot
    fail partway.
    """
    return tuple(
        Change(field=name, before=state.values.get(name), after=value)
        for name, value in desired.items()
        if state.values.get(name) != value
    )


def resolve_option(field_name: str, field: FieldInfo, option_name: str) -> str:
    """Option name -> id, or raise listing what the project actually defines.

    Failing loudly here is the point: the alternative to a lookup is a pasted
    id, and a pasted id that has gone stale writes a wrong value silently.
    """
    try:
        return field.options[option_name]
    except KeyError:
        valid = ", ".join(sorted(field.options)) or "(none)"
        raise UnknownOptionError(f"{field_name} has no option {option_name!r}; valid: {valid}") from None


_FIELDS_QUERY = """
query($owner: String!, $number: Int!, $after: String) {
  user(login: $owner) {
    projectV2(number: $number) {
      id
      fields(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes { ... on ProjectV2SingleSelectField { id name options { id name } } }
      }
    }
  }
}
"""

#: Issue -> project item, never project -> items. The reverse direction pages
#: through every item on the board to find one, which burns the GraphQL budget
#: (scored by query complexity, and shared across every session on the account).
_ITEM_QUERY = """
query($owner: String!, $repo: String!, $issue: Int!) {
  repository(owner: $owner, name: $repo) {
    issue(number: $issue) {
      number
      state
      closedAt
      projectItems(first: 10) {
        nodes {
          id
          project { number }
          fieldValues(first: 50) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                field { ... on ProjectV2SingleSelectField { name } }
              }
            }
          }
        }
      }
    }
  }
}
"""


def _graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    try:
        return gh_graphql.run(query, variables)
    except Exception as exc:  # noqa: BLE001 — the transport's error type is not ours to name
        raise GitHubError(str(exc)) from exc


def fetch_fields(owner: str, number: int, wanted: tuple[str, ...]) -> tuple[str, dict[str, FieldInfo]]:
    """Project id plus the named single-select fields. One query for all of them.

    Fetching every wanted field in a single pass rather than one call per field
    is not premature tidiness: the GraphQL budget is scored by complexity and
    shared across sessions, and it was exhausted on this account on 2026-08-26.
    """
    after: str | None = None
    project_id: str | None = None
    found: dict[str, FieldInfo] = {}
    while True:
        data = _graphql(_FIELDS_QUERY, {"owner": owner, "number": number, "after": after})
        project = (data.get("user") or {}).get("projectV2")
        if not project:
            raise GitHubError(f"project {owner}/{number} not found")
        project_id = project["id"]
        for node in project["fields"]["nodes"]:
            if node and node.get("name") in wanted:
                found[node["name"]] = FieldInfo(
                    field_id=node["id"], options={opt["name"]: opt["id"] for opt in node["options"]}
                )
        page = project["fields"]["pageInfo"]
        if not page["hasNextPage"]:
            break
        after = page["endCursor"]

    missing = [name for name in wanted if name not in found]
    if missing:
        raise GitHubError(f"project {owner}/{number} has no single-select field(s): {', '.join(missing)}")
    return project_id, found


def fetch_item(owner: str, repo: str, project_number: int, issue: int) -> ItemState:
    """The issue's item on THIS project, with its current single-select values."""
    data = _graphql(_ITEM_QUERY, {"owner": owner, "repo": repo, "issue": issue})
    node = ((data.get("repository") or {}).get("issue")) or None
    if not node:
        raise GitHubError(f"issue {owner}/{repo}#{issue} not found")

    for item in node["projectItems"]["nodes"]:
        if (item.get("project") or {}).get("number") != project_number:
            continue
        values = {
            fv["field"]["name"]: fv["name"]
            for fv in item["fieldValues"]["nodes"]
            if fv and fv.get("field", {}).get("name") and fv.get("name")
        }
        return ItemState(
            item_id=item["id"],
            number=node["number"],
            values=values,
            # Live from the API, never from an event payload -- see ItemState.
            issue_state=str(node.get("state") or "OPEN"),
            closed_at=node.get("closedAt"),
        )

    raise GitHubError(
        f"issue #{issue} is not on project {project_number} — the add-to-project workflow may not have run yet"
    )


def _mutation(index: int, project_id: str, item_id: str, field_id: str, option_id: str) -> str:
    return (
        f"m{index}: updateProjectV2ItemFieldValue(input: {{"
        f"projectId: {json.dumps(project_id)}, itemId: {json.dumps(item_id)}, "
        f"fieldId: {json.dumps(field_id)}, "
        f"value: {{ singleSelectOptionId: {json.dumps(option_id)} }}"
        f"}}) {{ projectV2Item {{ id }} }}"
    )


def apply(
    project_id: str,
    item_id: str,
    fields: dict[str, FieldInfo],
    changes: tuple[Change, ...],
) -> int:
    """Write every change in one mutation. Returns how many were written.

    No changes means no request — see `plan`. Option names are resolved here
    rather than by the caller so that an unknown one fails before anything is
    written, never halfway through.
    """
    if not changes:
        return 0
    mutations = [
        _mutation(i, project_id, item_id, fields[c.field].field_id, resolve_option(c.field, fields[c.field], c.after))
        for i, c in enumerate(changes)
    ]
    _graphql("mutation {\n" + "\n".join(mutations) + "\n}", {})
    return len(changes)
