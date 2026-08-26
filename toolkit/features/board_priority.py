"""Detect open issues with no Priority set (GOV-005 AC2, #1417).

`harness/priority-scale.md` writes down what P0-P3 mean here. This module is
the check side only: it reports which open issues carry no Priority value at
all. Assigning one is a judged, reviewed pass — not something this module
does — so there is no `--apply` here, only detection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from toolkit.core import gh_graphql

_PRIORITY_FIELD = "Priority"


class GitHubError(Exception):
    """`gh api graphql` failed or returned errors."""


@dataclass(frozen=True)
class Item:
    number: int
    title: str
    priority: str | None


def missing_priority(items: list[Item]) -> tuple[Item, ...]:
    """Open items that carry no Priority value. Pure; safe to call often."""
    return tuple(item for item in items if item.priority is None)


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
          content {
            __typename
            ... on Issue { number title state repository { nameWithOwner } }
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
    """Every OPEN issue of `repo` on the project board, with its current Priority."""
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
            items.append(Item(number=int(content["number"]), title=content["title"], priority=value.get("name")))
        if not page["pageInfo"]["hasNextPage"]:
            return items
        after = page["pageInfo"]["endCursor"]
