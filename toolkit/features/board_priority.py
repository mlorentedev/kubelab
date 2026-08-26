"""Detect and assign Priority on open issues that carry none (GOV-005 AC2, #1417).

`harness/priority-scale.md` writes down what P0-P3 mean here. `missing_priority`
is the check side: it reports which open issues carry no Priority value at
all. `default_priority` is a deliberately narrow, high-precision slice of that
rubric — the two signals cheap enough to read off a label or a title prefix
without re-deriving each issue's judgment call by hand: a `bug` label or a
security nature promotes to `P1`; everything else defaults to `P2`, matching
the rubric's own "absent a concrete urgency cue, prefer P2" guidance. It does
not attempt "unblocks the active arc" or the P3 speculative/parked signals —
those need the judgment a label can't carry, and a first pass that tried to
regex for them badly over-fired on this repo's evidence-driven ticket prose
(nearly every ticket here reads as "X is broken", which is house style, not a
P1 signal). Read as a floor, not the final word: anything this misses is
exactly as unprioritized after this pass as before it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from toolkit.core import gh_graphql

_PRIORITY_FIELD = "Priority"
_SEC_PREFIX = re.compile(r"^SEC-")


class GitHubError(Exception):
    """`gh api graphql` failed or returned errors."""


@dataclass(frozen=True)
class Item:
    item_id: str
    number: int
    title: str
    priority: str | None
    labels: tuple[str, ...]


def missing_priority(items: list[Item]) -> tuple[Item, ...]:
    """Open items that carry no Priority value. Pure; safe to call often."""
    return tuple(item for item in items if item.priority is None)


def default_priority(title: str, labels: tuple[str, ...]) -> str:
    """P1 for a labeled bug or a security nature; P2 otherwise. See module docstring."""
    lowered = {label.lower() for label in labels}
    if "bug" in lowered:
        return "P1"
    if "security" in lowered or _SEC_PREFIX.match(title):
        return "P1"
    return "P2"


@dataclass(frozen=True)
class Assignment:
    item: Item
    priority: str


def plan(items: list[Item]) -> tuple[Assignment, ...]:
    """One assignment per item missing Priority. Pure; safe to call often."""
    return tuple(
        Assignment(item=item, priority=default_priority(item.title, item.labels)) for item in missing_priority(items)
    )


# --- GitHub -------------------------------------------------------------------


def _gh_graphql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return gh_graphql.run(query, variables)
    except gh_graphql.GraphQLError as exc:
        raise GitHubError(str(exc)) from exc


_ITEMS_QUERY = """
query($owner: String!, $number: Int!, $after: String) {
  user(login: $owner) {
    projectV2(number: $number) {
      items(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          content {
            __typename
            ... on Issue {
              number
              title
              state
              repository { nameWithOwner }
              labels(first: 20) { nodes { name } }
            }
          }
          fieldValueByName(name: "Priority") {
            ... on ProjectV2ItemFieldSingleSelectValue { name }
          }
        }
      }
    }
  }
}
"""


def fetch_open_items(owner: str, number: int, repo: str) -> list[Item]:
    """Every OPEN issue of `repo` on the project board, with its Priority and labels."""
    items: list[Item] = []
    after: str | None = None
    while True:
        data = _gh_graphql(_ITEMS_QUERY, {"owner": owner, "number": number, "after": after})
        project = (data.get("user") or {}).get("projectV2")
        if not project:
            raise GitHubError(f"project {owner}/{number} not found")
        page = project["items"]
        for node in page["nodes"]:
            content = node.get("content") or {}
            if content.get("__typename") != "Issue" or content.get("state") != "OPEN":
                continue
            if (content.get("repository") or {}).get("nameWithOwner") != repo:
                continue
            value = node.get("fieldValueByName") or {}
            labels = tuple(label["name"] for label in content["labels"]["nodes"])
            items.append(
                Item(
                    item_id=node["id"],
                    number=int(content["number"]),
                    title=content["title"],
                    priority=value.get("name"),
                    labels=labels,
                )
            )
        if not page["pageInfo"]["hasNextPage"]:
            return items
        after = page["pageInfo"]["endCursor"]


@dataclass(frozen=True)
class FieldInfo:
    field_id: str
    options: dict[str, str]  # option name -> option id


_FIELD_QUERY = """
query($owner: String!, $number: Int!, $after: String) {
  user(login: $owner) {
    projectV2(number: $number) {
      id
      fields(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          ... on ProjectV2SingleSelectField { id name options { id name } }
        }
      }
    }
  }
}
"""


def fetch_priority_field(owner: str, number: int) -> tuple[str, FieldInfo]:
    """The project id and the Priority field's id + options. Walks every field page."""
    after: str | None = None
    project_id: str | None = None
    while True:
        data = _gh_graphql(_FIELD_QUERY, {"owner": owner, "number": number, "after": after})
        project = (data.get("user") or {}).get("projectV2")
        if not project:
            raise GitHubError(f"project {owner}/{number} not found")
        project_id = project["id"]
        for node in project["fields"]["nodes"]:
            if node and node.get("name") == _PRIORITY_FIELD:
                return project_id, FieldInfo(
                    field_id=node["id"], options={opt["name"]: opt["id"] for opt in node["options"]}
                )
        page = project["fields"]["pageInfo"]
        if not page["hasNextPage"]:
            raise GitHubError(f"field {_PRIORITY_FIELD!r} not found on project {owner}/{number}")
        after = page["endCursor"]


def _set_value_mutation(index: int, project_id: str, item_id: str, field_id: str, option_id: str) -> str:
    return (
        f"m{index}: updateProjectV2ItemFieldValue(input: {{"
        f"projectId: {json.dumps(project_id)}, itemId: {json.dumps(item_id)}, "
        f"fieldId: {json.dumps(field_id)}, "
        f"value: {{ singleSelectOptionId: {json.dumps(option_id)} }}"
        f"}}) {{ projectV2Item {{ id }} }}"
    )


def apply(project_id: str, field: FieldInfo, assignments: tuple[Assignment, ...], batch_size: int = 25) -> int:
    """Write every assignment; returns how many were written."""
    written = 0
    for start in range(0, len(assignments), batch_size):
        batch = assignments[start : start + batch_size]
        mutations = [
            _set_value_mutation(i, project_id, a.item.item_id, field.field_id, field.options[a.priority])
            for i, a in enumerate(batch)
        ]
        _gh_graphql("mutation {\n" + "\n".join(mutations) + "\n}")
        written += len(batch)
    return written
