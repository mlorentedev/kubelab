"""The Stream registry and the classifier behind `toolkit board streams` (GOV-002, #823).

Pure tests: nothing here reaches GitHub. The registry checked in under
`harness/` is loaded for real, so a prefix declared in two streams, or an
override naming a stream that does not exist, fails on every commit rather
than on the next board run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from toolkit.features import board_streams as bs

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = REPO_ROOT / "harness" / "board-streams.yaml"


@pytest.fixture(scope="module")
def registry() -> bs.Registry:
    return bs.load_registry(REGISTRY)


def test_registry_loads_and_names_the_board(registry: bs.Registry) -> None:
    assert registry.owner == "mlorentedev"
    assert registry.number == 1
    assert registry.repo == "mlorentedev/kubelab"
    assert registry.field == "Stream"
    assert 10 <= len(registry.streams) <= 14, "a stream list must fit in one filter dropdown"


def test_registry_has_no_dissolved_families(registry: bs.Registry) -> None:
    # OPS and ADR028 were dissolved issue by issue; a prefix entry would resurrect the grab-bag.
    assert "OPS" not in registry.prefix_to_stream
    assert "ADR028" not in registry.prefix_to_stream


@pytest.mark.parametrize(
    ("title", "prefix"),
    [
        ("OBS-018: the PVC alert has fired since the day it shipped", "OBS"),
        ("IDP-005b: `tk catalog show <service>`", "IDP"),
        ("OPS-D004: Docker image rename", "OPS"),
        ("PROD-K3S-000e: Deploy Headlamp", "PROD-K3S"),
        ("BACKUP-EPIC: make the backup layer real", "BACKUP"),
        ("DASH-DT-003: refactor", "DASH-DT"),
        ("DOCS: Migrate vault 90-lessons.md into repo", "DOCS"),
        ("CI: a review obtained with /review never updates the gate", "CI"),
        ("feat(gateway): implement prompt caching", None),
        ("Repurpose ace2 from LLM compute to dev-node", None),
        ("aws1 (Argo CD hub) Spot instance reclaimed", None),
    ],
)
def test_title_prefix(title: str, prefix: str | None) -> None:
    assert bs.title_prefix(title) == prefix


def _registry(**overrides: str) -> bs.Registry:
    return bs.Registry(
        owner="o",
        number=1,
        repo="o/r",
        field="Stream",
        streams=("A", "B"),
        prefix_to_stream={"OBS": "A", "TOOL": "B"},
        overrides={int(k): v for k, v in overrides.items()},
    )


def test_classify_prefers_override_then_prefix_then_none() -> None:
    reg = _registry(**{"7": "B"})
    assert bs.classify(7, "OBS-001: overridden away from A", reg) == "B"
    assert bs.classify(8, "OBS-002: by prefix", reg) == "A"
    assert bs.classify(9, "no prefix at all", reg) is None
    assert bs.classify(10, "ZZZ-001: unknown family", reg) is None


def test_plan_writes_only_differences_and_reports_unplaced() -> None:
    reg = _registry()
    items = [
        bs.Item("i1", 1, "OBS-001: already right", current="A"),
        bs.Item("i2", 2, "OBS-002: wrong value", current="B"),
        bs.Item("i3", 3, "TOOL-001: unset", current=None),
        bs.Item("i4", 4, "nothing to go on", current=None),
    ]
    plan = bs.plan(items, reg)
    assert plan.unchanged == 1
    assert [(c.item.number, c.desired) for c in plan.changes] == [(2, "A"), (3, "B")]
    assert [i.number for i in plan.unplaced] == [4]
    assert plan.counts() == {"A": 1, "B": 1}
    assert bs.desired_counts(items, reg) == {"A": 2, "B": 1}


def test_loader_refuses_a_prefix_in_two_streams(tmp_path: Path) -> None:
    path = tmp_path / "r.yaml"
    path.write_text(
        "project: {owner: o, number: 1, repo: o/r}\nfield: Stream\n"
        "streams:\n  - {name: A, prefixes: [X]}\n  - {name: B, prefixes: [X]}\n",
        encoding="utf-8",
    )
    with pytest.raises(bs.RegistryError, match="prefix X"):
        bs.load_registry(path)


def test_loader_refuses_an_override_to_an_unknown_stream(tmp_path: Path) -> None:
    path = tmp_path / "r.yaml"
    path.write_text(
        "project: {owner: o, number: 1, repo: o/r}\nfield: Stream\n"
        "streams:\n  - {name: A, prefixes: [X]}\noverrides:\n  12: Nope\n",
        encoding="utf-8",
    )
    with pytest.raises(bs.RegistryError, match="#12"):
        bs.load_registry(path)


def test_ensure_field_refuses_to_rewrite_an_incomplete_option_list() -> None:
    reg = _registry()
    info = bs.ProjectInfo(project_id="p", field_id="f", options={"A": "oa"})
    with pytest.raises(bs.RegistryError, match=r"lacks options: \['B'\]"):
        bs.ensure_field(reg, info)


def test_loader_refuses_a_child_under_two_parents(tmp_path: Path) -> None:
    path = tmp_path / "r.yaml"
    path.write_text(
        "project: {owner: o, number: 1, repo: o/r}\nfield: Stream\n"
        "streams:\n  - {name: A, prefixes: [X]}\nparts:\n  10: [1, 2]\n  20: [2]\n",
        encoding="utf-8",
    )
    with pytest.raises(bs.RegistryError, match="#2 is listed under both #10 and #20"):
        bs.load_registry(path)


def test_registry_parts_are_open_sequencing_tickets(registry: bs.Registry) -> None:
    # Every parent must also be an issue the registry can place; a part under an
    # unplaced parent would be a dependency declared from a ticket nobody can find.
    for parent in registry.parts:
        assert isinstance(parent, int)
        assert registry.parts[parent], f"#{parent} declares no parts"


def test_plan_parts_links_only_orphans_and_reports_conflicts() -> None:
    reg = bs.Registry(
        owner="o",
        number=1,
        repo="o/r",
        field="Stream",
        streams=("A",),
        prefix_to_stream={},
        overrides={},
        parts={100: (1, 2, 3, 4)},
    )
    refs = {
        100: bs.IssueRef(100, "n100", "OPEN", None),
        1: bs.IssueRef(1, "n1", "OPEN", 100),  # already linked
        2: bs.IssueRef(2, "n2", "OPEN", None),  # to link
        3: bs.IssueRef(3, "n3", "CLOSED", 999),  # someone else's child
        # 4 is missing from refs
    }
    plan = bs.plan_parts(reg, refs)
    assert plan.linked == 1
    assert plan.links == (bs.Link(parent=100, child=2),)
    assert plan.conflicts == ((3, 999, 100),)
    assert plan.missing == (4,)


def test_plan_parts_refuses_a_closed_parent() -> None:
    reg = bs.Registry(
        owner="o",
        number=1,
        repo="o/r",
        field="Stream",
        streams=("A",),
        prefix_to_stream={},
        overrides={},
        parts={200: (5,)},
    )
    refs = {
        200: bs.IssueRef(200, "n200", "CLOSED", None),
        5: bs.IssueRef(5, "n5", "OPEN", None),
    }
    plan = bs.plan_parts(reg, refs)
    assert plan.links == ()
    assert plan.closed_parents == (200,)


def test_loader_refuses_a_repo_that_is_not_owner_slash_name(tmp_path: Path) -> None:
    path = tmp_path / "r.yaml"
    path.write_text(
        'project: {owner: o, number: 1, repo: "o/r\\") { evil }"}\nfield: Stream\n'
        "streams:\n  - {name: A, prefixes: [X]}\n",
        encoding="utf-8",
    )
    with pytest.raises(bs.RegistryError, match="owner/name"):
        bs.load_registry(path)


def test_fetch_project_walks_every_page_of_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [
        {
            "user": {
                "projectV2": {
                    "id": "p",
                    "fields": {
                        "pageInfo": {"hasNextPage": True, "endCursor": "c1"},
                        "nodes": [{}, {"id": "f0", "name": "Status", "options": []}],
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
                        "nodes": [{"id": "f1", "name": "Stream", "options": [{"id": "o1", "name": "A"}]}],
                    },
                }
            }
        },
    ]
    seen: list[str | None] = []

    def fake(query: str, variables: dict[str, object] | None = None) -> dict[str, object]:
        seen.append((variables or {}).get("after"))  # type: ignore[arg-type]
        return pages[len(seen) - 1]

    monkeypatch.setattr(bs, "_gh_graphql", fake)
    info = bs.fetch_project(_registry())
    assert seen == [None, "c1"]
    assert info == bs.ProjectInfo(project_id="p", field_id="f1", options={"A": "o1"})


def test_refs_query_aliases_each_number() -> None:
    text = bs._refs_query("o/r", [5, 6])
    assert 'repository(owner: "o", name: "r")' in text
    assert "i5: issue(number: 5)" in text and "i6: issue(number: 6)" in text


def test_batch_mutation_aliases_every_item() -> None:
    text = bs._batch_mutation("p", "f", [("i1", "o1"), ("i2", "o2")])
    assert text.count("updateProjectV2ItemFieldValue") == 2
    assert "m0:" in text and "m1:" in text
    assert '"i2"' in text and '"o2"' in text
