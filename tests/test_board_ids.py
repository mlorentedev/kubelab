"""The duplicate-id detector behind `toolkit board ids` (GOV-004, #1416).

Pure tests: nothing here reaches GitHub.
"""

from __future__ import annotations

import pytest

from toolkit.features import board_ids as bi


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("ANSIBLE-026: baseline node hygiene assertions", "ANSIBLE-026"),
        ("IDP-005b: `tk catalog show <service>`", "IDP-005b"),
        ("OPS-D004: Docker image rename", "OPS-D004"),
        ("PROD-K3S-000e: Deploy Headlamp", "PROD-K3S-000e"),
        ("BACKUP-EPIC: make the backup layer real", "BACKUP-EPIC"),
        ("DOCS: Migrate vault 90-lessons.md into repo", None),  # no sequence number, not a colliding id
        ("feat(gateway): implement prompt caching", None),
        ("Repurpose ace2 from LLM compute to dev-node", None),
    ],
)
def test_full_id(title: str, expected: str | None) -> None:
    assert bi.full_id(title) == expected


def test_duplicates_groups_by_full_id_not_family() -> None:
    issues = [
        bi.Issue(536, "TOOL-009: cleanup ansible-lint violations"),
        bi.Issue(680, "TOOL-009 follow-up: drift detection"),
        bi.Issue(694, "TOOL-009 follow-up: renovate bumps"),
        bi.Issue(839, "TOOL-022: machine-readable CLI output"),
        bi.Issue(1168, "TOOL-022: the gate records a review happened"),
        bi.Issue(1, "no id here at all"),
    ]
    dupes = bi.duplicates(issues)
    assert set(dupes) == {"TOOL-009", "TOOL-022"}
    assert {i.number for i in dupes["TOOL-009"]} == {536, 680, 694}
    assert {i.number for i in dupes["TOOL-022"]} == {839, 1168}


def test_duplicates_ignores_titles_with_no_id_and_unique_ids() -> None:
    issues = [
        bi.Issue(1, "OBS-001: unique, no collision"),
        bi.Issue(2, "nothing to go on"),
    ]
    assert bi.duplicates(issues) == {}


def test_fetch_open_issues_walks_every_page(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [
        {
            "repository": {
                "issues": {
                    "pageInfo": {"hasNextPage": True, "endCursor": "c1"},
                    "nodes": [{"number": 1, "title": "A"}],
                }
            }
        },
        {
            "repository": {
                "issues": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [{"number": 2, "title": "B"}],
                }
            }
        },
    ]
    seen: list[str | None] = []

    def fake(query: str, variables: dict[str, object] | None = None) -> dict[str, object]:
        seen.append((variables or {}).get("after"))  # type: ignore[arg-type]
        return pages[len(seen) - 1]

    monkeypatch.setattr(bi, "_gh_graphql", fake)
    issues = bi.fetch_open_issues("o/r")
    assert seen == [None, "c1"]
    assert issues == [bi.Issue(1, "A"), bi.Issue(2, "B")]


def test_fetch_open_issues_refuses_unknown_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bi, "_gh_graphql", lambda query, variables=None: {"repository": None})
    with pytest.raises(bi.GitHubError, match="o/r not found"):
        bi.fetch_open_issues("o/r")
