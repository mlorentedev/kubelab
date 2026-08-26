"""The missing-priority detector and default-assignment planner behind
`toolkit board priority` (GOV-005 AC2, #1417).

Pure tests: nothing here reaches GitHub.
"""

from __future__ import annotations

import pytest

from toolkit.features import board_priority as bp


def _item(number, title, priority=None, labels=()):
    return bp.Item(item_id=f"i{number}", number=number, title=title, priority=priority, labels=tuple(labels))


def test_missing_priority_filters_only_unset() -> None:
    items = [
        _item(1, "has P2", "P2"),
        _item(2, "no priority"),
        _item(3, "has P1", "P1"),
        _item(4, "also no priority"),
    ]
    missing = bp.missing_priority(items)
    assert [i.number for i in missing] == [2, 4]


def test_missing_priority_empty_when_all_set() -> None:
    items = [_item(1, "a", "P2"), _item(2, "b", "P3")]
    assert bp.missing_priority(items) == ()


@pytest.mark.parametrize(
    ("title", "labels", "expected"),
    [
        ("OBS-024: LokiClient's default base_url is stale", ("bug",), "P1"),
        ("SEC-014: Grafana trusts the Remote-User header", (), "P1"),
        ("ANSIBLE-054: something", ("security",), "P1"),
        ("CONTENT-001: write posts", ("chore",), "P2"),
        ("TOOL-040: refactor the CLI output", (), "P2"),
        ("SECRETARY-001: unrelated prefix that merely starts with SEC letters", (), "P2"),
    ],
)
def test_default_priority(title, labels, expected) -> None:
    assert bp.default_priority(title, labels) == expected


def test_plan_covers_only_missing_and_uses_default_priority() -> None:
    items = [
        _item(1, "already P3", "P3"),
        _item(2, "bug, no priority", labels=("bug",)),
        _item(3, "plain, no priority"),
    ]
    plan = bp.plan(items)
    assert {(a.item.number, a.priority) for a in plan} == {(2, "P1"), (3, "P2")}


def test_fetch_open_items_reads_labels_and_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    page = {
        "user": {
            "projectV2": {
                "items": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [
                        {
                            "id": "pi1",
                            "content": {
                                "__typename": "Issue",
                                "number": 1,
                                "title": "kept",
                                "state": "OPEN",
                                "repository": {"nameWithOwner": "o/r"},
                                "labels": {"nodes": [{"name": "bug"}]},
                            },
                            "fieldValueByName": None,
                        },
                        {
                            "id": "pi2",
                            "content": {
                                "__typename": "Issue",
                                "number": 2,
                                "title": "dropped: closed",
                                "state": "CLOSED",
                                "repository": {"nameWithOwner": "o/r"},
                                "labels": {"nodes": []},
                            },
                            "fieldValueByName": None,
                        },
                    ],
                }
            }
        }
    }
    monkeypatch.setattr(bp, "_gh_graphql", lambda query, variables=None: page)
    items = bp.fetch_open_items("o", 1, "o/r")
    assert [i.number for i in items] == [1]
    assert items[0].labels == ("bug",)
    assert items[0].item_id == "pi1"


def test_fetch_priority_field_walks_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [
        {
            "user": {
                "projectV2": {
                    "id": "p",
                    "fields": {
                        "pageInfo": {"hasNextPage": True, "endCursor": "c1"},
                        "nodes": [{"id": "fs", "name": "Status", "options": []}],
                    },
                }
            }
        },
        {
            "user": {
                "projectV2": {
                    "id": "p",
                    "fields": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [{"id": "fp", "name": "Priority", "options": [{"id": "o1", "name": "P1"}]}],
                    },
                }
            }
        },
    ]
    seen = []

    def fake(query, variables=None):
        seen.append((variables or {}).get("after"))
        return pages[len(seen) - 1]

    monkeypatch.setattr(bp, "_gh_graphql", fake)
    project_id, field = bp.fetch_priority_field("o", 1)
    assert seen == [None, "c1"]
    assert project_id == "p"
    assert field == bp.FieldInfo(field_id="fp", options={"P1": "o1"})


def test_apply_batches_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(bp, "_gh_graphql", lambda query, variables=None: calls.append(query))
    field = bp.FieldInfo(field_id="fp", options={"P1": "o1", "P2": "o2"})
    assignments = (
        bp.Assignment(item=_item(1, "a"), priority="P1"),
        bp.Assignment(item=_item(2, "b"), priority="P2"),
    )
    written = bp.apply("p", field, assignments, batch_size=1)
    assert written == 2
    assert len(calls) == 2
