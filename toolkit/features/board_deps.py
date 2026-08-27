"""Detect open issues named by a dependency keyword in another open issue's
body — the batch-close guard for GOV-005 AC3 (#1417).

This is the mechanical half of what the 2026-08-25 comment on #1417 did by
hand and called "regenerable from open issue bodies with the same keyword
scan": before any issue is proposed for batch close, check whether another
open issue's body names it as something it blocks on, gates, depends on, or
otherwise needs first. A close candidate that shows up here needs a second
look before it goes on the list.

Tuned for recall, not precision, and deliberately the opposite bias from
`board_priority`'s "deliberately narrow" rubric: there, a false positive
writes a wrong Priority to the board, which is the costly direction. Here, a
false positive costs one extra glance at a row that turns out to be nothing;
a false negative lets a batch-close kill an issue a sequencing ticket was
quietly depending on, which is the exact failure this guard exists to catch.
So the keyword list is generous and matches anywhere in the same paragraph as
a reference, not adjacent to it — except "after", which is ordinary English
in this repo's prose ("after the first push", "removing it afterwards") and
would drown the table at paragraph scope; that one only counts as `after #N`,
a few tokens apart.

Scope: issue bodies only (not comments or titles), references to the same
repository (`#N`) or spelled out (`owner/name#N`), both the referrer and the
referenced issue restricted to the open set fetched here, and an issue never
names itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from toolkit.core import gh_graphql

_KEYWORDS = re.compile(
    r"\b(block(?:s|ed|ing)?|gate(?:s|d)?|depend(?:s|enc(?:y|ies))?|epic"
    r"|sequenc(?:e|es|ed|ing)?|wait(?:s|ed|ing)?|prereq(?:uisite)?)\b",
    re.IGNORECASE,
)
_AFTER_REF = re.compile(r"\bafter\s+(?:(?P<repo>[\w.-]+/[\w.-]+))?#(?P<num>\d+)\b", re.IGNORECASE)
_ISSUE_REF = re.compile(r"(?:(?P<repo>[\w.-]+/[\w.-]+))?#(?P<num>\d+)")
_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n+")


class GitHubError(Exception):
    """`gh api graphql` failed or returned errors."""


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    body: str


def _refs_in(text: str, repo: str) -> set[int]:
    numbers: set[int] = set()
    for match in _ISSUE_REF.finditer(text):
        ref_repo = match.group("repo")
        if ref_repo is not None and ref_repo != repo:
            continue
        numbers.add(int(match.group("num")))
    return numbers


def find_dependencies(referrer: Issue, open_numbers: set[int], repo: str) -> set[int]:
    """Every open issue number `referrer`'s body names via a dependency keyword.

    Pure; safe to call often. `open_numbers` should be every currently-open
    issue's number, so a reference to a closed or unknown issue is dropped.
    """
    found: set[int] = set()

    for match in _AFTER_REF.finditer(referrer.body):
        ref_repo = match.group("repo")
        if ref_repo is not None and ref_repo != repo:
            continue
        found.add(int(match.group("num")))

    for paragraph in _PARAGRAPH_SPLIT.split(referrer.body):
        if not _KEYWORDS.search(paragraph):
            continue
        found |= _refs_in(paragraph, repo)

    found.discard(referrer.number)
    return found & open_numbers


def build_guard(issues: list[Issue], repo: str) -> dict[int, tuple[int, ...]]:
    """Referenced issue number -> sorted tuple of open issues that name it. Pure."""
    open_numbers = {issue.number for issue in issues}
    guard: dict[int, set[int]] = {}
    for issue in issues:
        for target in find_dependencies(issue, open_numbers, repo):
            guard.setdefault(target, set()).add(issue.number)
    return {target: tuple(sorted(referrers)) for target, referrers in guard.items()}


# --- GitHub -------------------------------------------------------------------


def _gh_graphql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return gh_graphql.run(query, variables)
    except gh_graphql.GraphQLError as exc:
        raise GitHubError(str(exc)) from exc


_ISSUES_QUERY = """
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    issues(states: OPEN, first: 50, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes { number title body }
    }
  }
}
"""


def fetch_open_issues(repo: str) -> list[Issue]:
    """Every open issue in `owner/name`, with its body, paginated."""
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
            issues.append(Issue(number=int(node["number"]), title=node["title"], body=node["body"] or ""))
        if not page["pageInfo"]["hasNextPage"]:
            return issues
        after = page["pageInfo"]["endCursor"]
