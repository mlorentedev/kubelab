"""The missing-priority detector behind `toolkit board priority` (GOV-005 AC2, #1417).

Pure tests: nothing here reaches GitHub.
"""

from __future__ import annotations

import pytest

from toolkit.features import board_priority as bp


def test_missing_priority_filters_only_unset() -> None:
    items = [
        bp.Item(1, "has P2", "P2"),
        bp.Item(2, "no priority", None),
        bp.Item(3, "has P1", "P1"),
        bp.Item(4, "also no priority", None),
    ]
    missing = bp.missing_priority(items)
    assert [i.number for i in missing] == [2, 4]


def test_missing_priority_empty_when_all_set() -> None:
    items = [bp.Item(1, "a", "P2"), bp.Item(2, "b", "P3")]
    assert bp.missing_priority(items) == ()


def test_fetch_open_items_filters_state_and_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [
        {
            "user": {
                "projectV2": {
                    "items": {
                        "pageInfo": {"hasNextPage": True, "endCursor": "c1"},
                        "nodes": [
                            {
                                "content": {
                                    "__typename": "Issue",
                                    "number": 1,
                                    "title": "kept: open, right repo, no priority",
                                    "state": "OPEN",
                                    "repository": {"nameWithOwner": "o/r"},
                                },
                                "fieldValueByName": None,
                            },
                            {
                                "content": {
                                    "__typename": "Issue",
                                    "number": 2,
                                    "title": "dropped: closed",
                                    "state": "CLOSED",
                                    "repository": {"nameWithOwner": "o/r"},
                                },
                                "fieldValueByName": None,
                            },
                            {
                                "content": {
                                    "__typename": "Issue",
                                    "number": 3,
                                    "title": "dropped: other repo",
                                    "state": "OPEN",
                                    "repository": {"nameWithOwner": "o/other"},
                                },
                                "fieldValueByName": None,
                            },
                        ],
                    }
                }
            }
        },
        {
            "user": {
                "projectV2": {
                    "items": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {
                                "content": {
                                    "__typename": "Issue",
                                    "number": 4,
                                    "title": "kept: has priority",
                                    "state": "OPEN",
                                    "repository": {"nameWithOwner": "o/r"},
                                },
                                "fieldValueByName": {"name": "P1"},
                            },
                        ],
                    }
                }
            }
        },
    ]
    seen: list[str | None] = []

    def fake(query: str, variables: dict[str, object] | None = None) -> dict[str, object]:
        seen.append((variables or {}).get("after"))  # type: ignore[arg-type]
        return pages[len(seen) - 1]

    monkeypatch.setattr(bp, "_gh_graphql", fake)
    items = bp.fetch_open_items("o", 1, "o/r")
    assert seen == [None, "c1"]
    assert [i.number for i in items] == [1, 4]
    assert bp.missing_priority(items) == (bp.Item(1, "kept: open, right repo, no priority", None),)


def test_fetch_open_items_refuses_unknown_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bp, "_gh_graphql", lambda query, variables=None: {"user": {"projectV2": None}})
    with pytest.raises(bp.GitHubError, match="o/1 not found"):
        bp.fetch_open_items("o", 1, "o/r")
