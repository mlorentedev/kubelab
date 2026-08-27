"""The dependency-guard scanner behind `toolkit board deps` (GOV-005 AC3, #1417).

Pure tests: nothing here reaches GitHub.
"""

from __future__ import annotations

import pytest

from toolkit.features import board_deps as bd

_REPO = "mlorentedev/kubelab"


def _issue(number, body, title="t"):
    return bd.Issue(number=number, title=title, body=body)


def test_find_dependencies_matches_keyword_and_ref_in_same_paragraph() -> None:
    referrer = _issue(1077, "Sequencing ticket, same role as #977 for the dashboard.\n\nUnrelated #500.")
    found = bd.find_dependencies(referrer, {977, 500, 1077}, _REPO)
    assert found == {977}


def test_find_dependencies_ignores_refs_with_no_keyword_in_the_paragraph() -> None:
    referrer = _issue(1, "See #2 for background, nothing more to say about it.")
    assert bd.find_dependencies(referrer, {1, 2}, _REPO) == set()


def test_find_dependencies_after_requires_tight_adjacency() -> None:
    # "after" alone, far from any #N, must not fire — it's ordinary prose.
    referrer = _issue(1, "Do this after the first push. See #2 for unrelated context.")
    assert bd.find_dependencies(referrer, {1, 2}, _REPO) == set()
    # "after #N" close together does fire, even with no other keyword present.
    referrer2 = _issue(1, "This work starts after #2 lands.")
    assert bd.find_dependencies(referrer2, {1, 2}, _REPO) == {2}


def test_find_dependencies_excludes_self_reference() -> None:
    referrer = _issue(5, "This ticket depends on #5 and #6.")
    assert bd.find_dependencies(referrer, {5, 6}, _REPO) == {6}


def test_find_dependencies_excludes_refs_to_closed_or_unknown_issues() -> None:
    referrer = _issue(1, "Blocked by #2 and #999.")
    assert bd.find_dependencies(referrer, {1, 2}, _REPO) == {2}


def test_find_dependencies_accepts_explicit_owner_repo_ref() -> None:
    referrer = _issue(1, f"Gated on {_REPO}#2.")
    assert bd.find_dependencies(referrer, {1, 2}, _REPO) == {2}


def test_find_dependencies_ignores_cross_repo_ref() -> None:
    referrer = _issue(1, "Gated on other/repo#2.")
    assert bd.find_dependencies(referrer, {1, 2}, _REPO) == set()


def test_build_guard_inverts_referrer_to_referenced() -> None:
    issues = [
        _issue(1, "Depends on #3."),
        _issue(2, "Blocked by #3."),
        _issue(3, "Nothing to report here."),
    ]
    guard = bd.build_guard(issues, _REPO)
    assert guard == {3: (1, 2)}


def test_fetch_open_issues_walks_every_page(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [
        {
            "repository": {
                "issues": {
                    "pageInfo": {"hasNextPage": True, "endCursor": "c1"},
                    "nodes": [{"number": 1, "title": "A", "body": "depends on #2"}],
                }
            }
        },
        {
            "repository": {
                "issues": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [{"number": 2, "title": "B", "body": None}],
                }
            }
        },
    ]
    seen: list[str | None] = []

    def fake(query: str, variables: dict[str, object] | None = None) -> dict[str, object]:
        seen.append((variables or {}).get("after"))  # type: ignore[arg-type]
        return pages[len(seen) - 1]

    monkeypatch.setattr(bd, "_gh_graphql", fake)
    issues = bd.fetch_open_issues(_REPO)
    assert seen == [None, "c1"]
    assert issues == [
        bd.Issue(1, "A", "depends on #2"),
        bd.Issue(2, "B", ""),
    ]


def test_fetch_open_issues_refuses_unknown_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bd, "_gh_graphql", lambda query, variables=None: {"repository": None})
    with pytest.raises(bd.GitHubError, match=f"{_REPO} not found"):
        bd.fetch_open_issues(_REPO)
