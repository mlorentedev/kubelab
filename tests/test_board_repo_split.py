"""#1448: a repo that is not `owner/name` fails as the command's own error.

Three board modules split the repo string with no guard, so `toolkit board ids
--repo notarepo` died on a bare `ValueError` stack trace instead of the
`GitHubError` -> exit 2 path every other failure of that command takes. All four
now split through `gh_graphql.split_repo`, before any call to GitHub.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from toolkit.core import gh_graphql
from toolkit.features import board_deps, board_ids, board_streams, board_sweep

BAD = ["notarepo", "owner/", "/name", ""]


@pytest.mark.parametrize("repo", BAD)
def test_split_repo_refuses_and_names_the_value(repo: str) -> None:
    with pytest.raises(ValueError, match="expected owner/name"):
        gh_graphql.split_repo(repo, ValueError)


def test_split_repo_keeps_the_name_whole() -> None:
    assert gh_graphql.split_repo("mlorentedev/kubelab") == ("mlorentedev", "kubelab")


def _no_github(*_args: object, **_kwargs: object) -> dict:
    raise AssertionError("GitHub was called with a repo that is not owner/name")


@pytest.mark.parametrize("repo", BAD)
@pytest.mark.parametrize(
    "module,call",
    [
        (board_ids, lambda repo: board_ids.fetch_open_issues(repo)),
        (board_deps, lambda repo: board_deps.fetch_open_issues(repo)),
        (board_streams, lambda repo: board_streams._refs_query(repo, [1])),
        (board_sweep, lambda repo: board_sweep.fetch_items(SimpleNamespace(repo=repo), [1])),
    ],
    ids=["board_ids", "board_deps", "board_streams", "board_sweep"],
)
def test_every_board_module_raises_its_own_error(
    module: object, call: object, repo: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "_gh_graphql", _no_github)
    with pytest.raises(module.GitHubError, match="expected owner/name"):  # type: ignore[attr-defined]
        call(repo)  # type: ignore[operator]
