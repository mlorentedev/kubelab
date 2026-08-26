"""Detect duplicate ticket IDs among open issues (GOV-004, #1416).

A title prefix like `TOOL-009` is an identifier only while it names one issue.
Measured 2026-08-25: sixteen families, thirty-three open issues, one of them
(`TOOL-009`) shared by three. The cause is mechanical — `/new-ticket` proposes
the next number in a family from what the session remembers, not from a
repository query, so two parallel sessions can propose the same one.

`check()` is the mode a hook or `make` target can run: it exits non-zero while
any open issue shares its full id (prefix + sequence number) with another.
Unlike `board_streams`, there is no registry here — the id is read straight
off the title, and any id borne by more than one open issue is the defect.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from toolkit.core import gh_graphql

#: `ANSIBLE-026`, `IDP-005b`, `OPS-D004`, `PROD-K3S-000e`, `BACKUP-EPIC` — the
#: full id, prefix and sequence number together (unlike board_streams' family-only match).
_FULL_ID = re.compile(r"^\s*([A-Z][A-Z0-9]*(?:-[A-Z][A-Z0-9]*)*?-(?:D?\d{1,4}[a-z]?|EPIC))\b")


class GitHubError(Exception):
    """`gh api graphql` failed or returned errors."""


def full_id(title: str) -> str | None:
    """The complete ticket id a title declares, or None when it declares none."""
    match = _FULL_ID.match(title)
    return match.group(1) if match else None


@dataclass(frozen=True)
class Issue:
    number: int
    title: str


def duplicates(issues: list[Issue]) -> dict[str, tuple[Issue, ...]]:
    """Every id borne by more than one issue, id -> the issues that share it."""
    groups: dict[str, list[Issue]] = {}
    for issue in issues:
        fid = full_id(issue.title)
        if fid is not None:
            groups.setdefault(fid, []).append(issue)
    return {fid: tuple(group) for fid, group in groups.items() if len(group) > 1}


# --- GitHub -------------------------------------------------------------------


def _gh_graphql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return gh_graphql.run(query, variables)
    except gh_graphql.GraphQLError as exc:
        raise GitHubError(str(exc)) from exc


_ISSUES_QUERY = """
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    issues(states: OPEN, first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes { number title }
    }
  }
}
"""


def fetch_open_issues(repo: str) -> list[Issue]:
    """Every open issue in `owner/name`, paginated."""
    owner, name = repo.split("/", 1)
    issues: list[Issue] = []
    after: str | None = None
    while True:
        data = _gh_graphql(_ISSUES_QUERY, {"owner": owner, "name": name, "after": after})
        repository = data.get("repository")
        if not repository:
            raise GitHubError(f"repository {repo} not found")
        page = repository["issues"]
        for node in page["nodes"]:
            issues.append(Issue(number=int(node["number"]), title=node["title"]))
        if not page["pageInfo"]["hasNextPage"]:
            return issues
        after = page["pageInfo"]["endCursor"]
