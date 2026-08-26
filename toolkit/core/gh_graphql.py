"""Run a GraphQL query through `gh api graphql`.

Shared by every board feature that talks to the bitácora project (`board_streams`,
`board_sweep`) so the transport — and its error handling — exists in one place.
Reuses the operator's existing `gh` auth; no token lives in this repository.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any


class GraphQLError(Exception):
    """`gh api graphql` failed to run, returned non-JSON, or the query itself errored."""


def run(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute one GraphQL request. Raises `GraphQLError` on transport or query errors."""
    body = json.dumps({"query": query, "variables": variables or {}})
    try:
        proc = subprocess.run(
            ["gh", "api", "graphql", "-H", "GraphQL-Features: sub_issues", "--input", "-"],
            input=body,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GraphQLError("gh CLI not found") from exc
    if proc.returncode != 0:
        raise GraphQLError(proc.stderr.strip() or proc.stdout.strip() or "gh api graphql failed")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise GraphQLError(f"gh returned non-JSON: {proc.stdout[:200]}") from exc
    if data.get("errors"):
        raise GraphQLError(json.dumps(data["errors"])[:500])
    return data["data"]
