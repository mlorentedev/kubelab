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
    """One issue's project item, and the single-select values it currently holds."""

    item_id: str
    number: int
    values: dict[str, str]  # field name -> current option name


@dataclass(frozen=True)
class Change:
    field: str
    before: str | None
    after: str

    def __str__(self) -> str:
        return f"{self.field}: {self.before or '(unset)'} -> {self.after}"


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
        return ItemState(item_id=item["id"], number=node["number"], values=values)

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
