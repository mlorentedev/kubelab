"""The In Progress sweep registry and planner behind `toolkit board sweep` (GOV-005, #1417).

Pure tests: nothing here reaches GitHub. The registry checked in under
`harness/` is loaded for real, so an issue accidentally listed under both
`stays` and `parked` fails on every commit rather than on the next sweep run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from toolkit.features import board_sweep as sw

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = REPO_ROOT / "harness" / "board-inprogress-sweep.yaml"


@pytest.fixture(scope="module")
def registry() -> sw.Registry:
    return sw.load_registry(REGISTRY)


def test_registry_loads_and_names_the_board(registry: sw.Registry) -> None:
    assert registry.owner == "mlorentedev"
    assert registry.number == 1
    assert registry.repo == "mlorentedev/kubelab"
    assert registry.status_field == "Status"
    assert registry.priority_field == "Priority"


def test_registry_has_no_overlap_between_stays_and_parked(registry: sw.Registry) -> None:
    assert set(registry.stays).isdisjoint(registry.parked)


def test_registry_covers_the_measured_28(registry: sw.Registry) -> None:
    assert len(registry.stays) + len(registry.parked) == 28
    assert 678 in registry.parked, "the flagship 68-day-idle example must be parked"
    assert 823 in registry.stays, "the sweep's own governing ticket stays"


def _registry(**kwargs: object) -> sw.Registry:
    base = {
        "owner": "o",
        "number": 1,
        "repo": "o/r",
        "status_field": "Status",
        "priority_field": "Priority",
        "stays": {1: "P1", 2: None},
        "parked": (3, 4),
    }
    base.update(kwargs)
    return sw.Registry(**base)  # type: ignore[arg-type]


def test_plan_stays_writes_status_only_when_wrong() -> None:
    reg = _registry()
    items = {
        1: sw.Item(item_id="i1", number=1, status="In Progress", priority=None),  # priority missing
        2: sw.Item(item_id="i2", number=2, status="Backlog", priority="P2"),  # status wrong
        3: sw.Item(item_id="i3", number=3, status="Backlog", priority=None),  # parked, already right
        4: sw.Item(item_id="i4", number=4, status="In Progress", priority=None),  # parked, wrong
    }
    plan = sw.plan(items, reg)
    by_number = {c.item.number: c for c in plan.changes}

    assert by_number[1].status is None
    assert by_number[1].priority == "P1"

    assert by_number[2].status == "In Progress"
    assert by_number[2].priority is None

    assert 3 not in by_number, "already Backlog — nothing to write"

    assert by_number[4].status == "Backlog"
    assert plan.unchanged == 1  # #3 only


def test_plan_leaves_priority_alone_when_already_set() -> None:
    reg = _registry(stays={10: "P1"})
    items = {10: sw.Item(item_id="i10", number=10, status="In Progress", priority="P3")}
    plan = sw.plan(items, reg)
    assert plan.changes == ()
    assert plan.unchanged == 1


def test_plan_reports_unchanged_when_everything_matches() -> None:
    reg = _registry(stays={1: None}, parked=(3,))
    items = {
        1: sw.Item(item_id="i1", number=1, status="In Progress", priority="P2"),
        3: sw.Item(item_id="i3", number=3, status="Backlog", priority=None),
    }
    plan = sw.plan(items, reg)
    assert plan.changes == ()
    assert plan.unchanged == 2
    assert plan.missing == ()


def test_plan_reports_missing_issues() -> None:
    reg = _registry(stays={1: "P1"}, parked=(99,))
    items = {1: sw.Item(item_id="i1", number=1, status="Backlog", priority=None)}
    plan = sw.plan(items, reg)
    assert plan.missing == (99,)
    assert [c.item.number for c in plan.changes] == [1]


def test_loader_refuses_overlap(tmp_path: Path) -> None:
    path = tmp_path / "r.yaml"
    path.write_text(
        "project: {owner: o, number: 1, repo: o/r}\n"
        "status_field: Status\npriority_field: Priority\n"
        "stays:\n  7:\n    priority: P1\n"
        "parked:\n  - 7\n",
        encoding="utf-8",
    )
    with pytest.raises(sw.RegistryError, match=r"both stays and parked: \[7\]"):
        sw.load_registry(path)


def test_loader_requires_status_and_priority_field_names(tmp_path: Path) -> None:
    path = tmp_path / "r.yaml"
    path.write_text("project: {owner: o, number: 1, repo: o/r}\n", encoding="utf-8")
    with pytest.raises(sw.RegistryError, match="status_field"):
        sw.load_registry(path)


def test_fetch_fields_walks_every_page_and_requires_both(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [
        {
            "user": {
                "projectV2": {
                    "id": "p",
                    "fields": {
                        "pageInfo": {"hasNextPage": True, "endCursor": "c1"},
                        "nodes": [{"id": "fs", "name": "Status", "options": [{"id": "os1", "name": "Backlog"}]}],
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
                        "nodes": [{"id": "fp", "name": "Priority", "options": [{"id": "op1", "name": "P1"}]}],
                    },
                }
            }
        },
    ]
    seen: list[str | None] = []

    def fake(query: str, variables: dict[str, object] | None = None) -> dict[str, object]:
        seen.append((variables or {}).get("after"))  # type: ignore[arg-type]
        return pages[len(seen) - 1]

    monkeypatch.setattr(sw, "_gh_graphql", fake)
    project_id, fields = sw.fetch_fields(_registry())
    assert seen == [None, "c1"]
    assert project_id == "p"
    assert fields["Status"].options == {"Backlog": "os1"}
    assert fields["Priority"].options == {"P1": "op1"}


def test_apply_batches_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake(query: str, variables: dict | None = None) -> dict:
        calls.append(query)
        return {}

    monkeypatch.setattr(sw, "_gh_graphql", fake)
    reg = _registry()
    fields = {
        "Status": sw.FieldInfo(field_id="fs", options={"Backlog": "ob", "In Progress": "oi"}),
        "Priority": sw.FieldInfo(field_id="fp", options={"P1": "op1"}),
    }
    changes = (
        sw.Change(item=sw.Item("i1", 1, "Backlog", None), status="In Progress", priority="P1"),
        sw.Change(item=sw.Item("i3", 3, "In Progress", None), status="Backlog", priority=None),
    )
    written = sw.apply("p", fields, reg, changes, batch_size=1)
    assert written == 3  # 2 writes for #1 (status+priority), 1 write for #3
    assert len(calls) == 3
