"""A repository that lost every ref is empty, whatever Gitea's `empty` flag says (#2144).

Measured on a throwaway `gitea/gitea:1.25.5` (the version prod runs), 2026-10-09:

- Gitea refuses to delete a default branch, through the API (403 `can not delete
  default branch`) and through `git push --delete`. Zero refs is unreachable by
  deletion, which is why the flag looked sufficient.
- Removing every ref ON DISK -- the shape of a partial restore -- leaves
  `GET /repos/{o}/{r}` answering `empty: false` indefinitely: the flag is a database
  column written at push time, not a reading of git. `GET .../git/refs` answers 404,
  which is the truth, and `GET .../commits` answers 500.

So the reconcile reads refs as well as the flag, and the two answer different
questions with different repairs: the flag finds the never-pushed shell
(`unfilled_migrations`, `emptied_native_repos`), the probe finds the repository that
held content and lost it (`lost_content_repos`, restored from R2).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.test_gitea_repo_reconcile import (
    DECLARED,
    DECLARED_SETTINGS,
    N8N_HOOK_ONLY,
    converged_body,
    converged_for,
    hooks_for,
    settings_for,
)
from toolkit.features.gitea_client import GiteaClient, GiteaError
from toolkit.features.gitea_repos import ReconcilePlan, RepoSpec, format_plan, plan_reconcile

# --- the client: `has_refs` --------------------------------------------------


class _Answers(GiteaClient):
    """Answers `_request` with one canned response, or raises one canned error."""

    def __init__(self, answer: Any = None, error: GiteaError | None = None) -> None:
        super().__init__("https://forge.invalid", token="unused")
        self.answer = answer
        self.error = error
        self.requested: list[str] = []

    def _request(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        self.requested.append(f"{method} {endpoint}")
        if self.error:
            raise self.error
        return self.answer


def test_has_refs_reads_git_refs_not_the_flag() -> None:
    client = _Answers(answer=[{"ref": "refs/heads/main"}])
    assert client.has_refs("teledyne", "openkm-brain") is True
    assert client.requested == ["GET /repos/teledyne/openkm-brain/git/refs"]


def test_a_404_from_git_refs_means_no_refs() -> None:
    """What Gitea 1.25.5 answers for a repository with zero refs, pushed-to or not."""
    client = _Answers(error=GiteaError("not found", status_code=404))
    assert client.has_refs("teledyne", "openkm-brain") is False


@pytest.mark.parametrize("answer", [[], None], ids=["empty-list", "null"])
def test_an_empty_listing_means_no_refs(answer: Any) -> None:
    assert _Answers(answer=answer).has_refs("teledyne", "openkm-brain") is False


def test_any_other_failure_raises_rather_than_reading_as_empty() -> None:
    """A 403 or a 500 is "I could not look", never "there is nothing". Reading it as
    empty would page the operator for a restore the repository does not need."""
    client = _Answers(error=GiteaError("forbidden", status_code=403))
    with pytest.raises(GiteaError):
        client.has_refs("teledyne", "openkm-brain")


# --- the planner: refs find what the flag cannot -------------------------------------------------


_NATIVE = {**DECLARED, "personal": [*DECLARED["personal"], RepoSpec("imagesensortool", native=True)]}
_ALL_PRESENT = {
    "teledyne/fae-brain": False,
    "teledyne/openkm-brain": False,
    "personal/resume": False,
    "personal/imagesensortool": False,
}


def _plan(refs: dict[str, bool], empty: dict[str, bool] | None = None) -> ReconcilePlan:
    settings = settings_for(_NATIVE)
    # Every body says `empty: false` unless told otherwise -- the stale flag measured above.
    for full_name in _ALL_PRESENT:
        settings[full_name] = {**converged_body(), "empty": (empty or {}).get(full_name, False)}
    return plan_reconcile(
        _NATIVE,
        existing_orgs=set(_NATIVE),
        existing_repos=_ALL_PRESENT,
        existing_teams=converged_for(_NATIVE),
        existing_repo_settings=settings,
        declared_settings=DECLARED_SETTINGS,
        existing_repo_hooks=hooks_for(_NATIVE),
        declared_webhooks=N8N_HOOK_ONLY,
        existing_repo_refs=refs,
    )


@pytest.mark.parametrize("full_name", ["teledyne/openkm-brain", "personal/imagesensortool"], ids=["migrated", "native"])
def test_a_repository_with_no_refs_is_lost_content_though_the_flag_says_otherwise(full_name: str) -> None:
    """Migrated or native alike: it held content and lost it, and the restore is the
    same. Not `unfilled_migrations`, whose repair (`drop-empty`) refuses a repository
    the flag calls non-empty, and whose re-migration has no source once GitHub's copy
    is retired."""
    plan = _plan({**dict.fromkeys(_ALL_PRESENT, True), full_name: False})
    assert [f"{r.org}/{r.name}" for r in plan.lost_content_repos] == [full_name]
    assert plan.unfilled_migrations == ()
    assert plan.emptied_native_repos == ()
    assert plan.is_noop, "reported, never acted on"


def test_the_plan_names_the_restore_for_a_repository_with_no_refs() -> None:
    printed = format_plan(_plan({**dict.fromkeys(_ALL_PRESENT, True), "teledyne/openkm-brain": False}))
    assert "teledyne/openkm-brain" in printed
    assert "offsite-backup-restore.md" in printed


def test_a_never_filled_shell_is_reported_once_not_twice() -> None:
    """Flag true AND no refs is the shell of #2133: `unfilled_migrations` owns it."""
    settings_empty = {"teledyne/openkm-brain": True}
    plan = _plan({**dict.fromkeys(_ALL_PRESENT, True), "teledyne/openkm-brain": False}, empty=settings_empty)
    assert [f"{r.org}/{r.name}" for r in plan.unfilled_migrations] == ["teledyne/openkm-brain"]
    assert plan.lost_content_repos == ()


def test_refs_present_and_flag_false_is_converged() -> None:
    plan = _plan(dict.fromkeys(_ALL_PRESENT, True))
    assert plan.lost_content_repos == ()


def test_a_present_repository_the_caller_did_not_probe_is_a_loud_failure() -> None:
    """Indexed, not `.get`: "not probed" read as "has refs" would be the optional
    comparison that silently stops comparing."""
    with pytest.raises(KeyError):
        _plan({})


# --- the CLI probes every present declared repository --------------------------


def test_the_reconcile_probes_refs_for_every_present_declared_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    """The planner can only use what the CLI reads. Without this, a deleted call site
    leaves the probe defined, tested and never run (the shape of #2143's review)."""
    from typer.testing import CliRunner

    import toolkit.cli.services as cli
    import toolkit.features.gitea_repos as repos

    probed: list[str] = []
    seen: dict[str, Any] = {}

    class _Admin:
        def list_orgs(self) -> set[str]:
            return {"teledyne"}

        def list_repos(self) -> dict[str, bool]:
            return {"teledyne/openkm-brain": True}

        def get_team(self, org: str, name: str) -> None:
            return None

        def get_repo(self, owner: str, name: str) -> dict[str, Any]:
            return {"empty": False}

        def list_hooks(self, owner: str, name: str) -> list[dict[str, Any]]:
            return []

        def has_refs(self, owner: str, name: str) -> bool:
            probed.append(f"{owner}/{name}")
            return False

    class _Config:
        def __init__(self, *_a: object, **_k: object) -> None:
            pass

        def get_merged_config(self) -> dict[str, object]:
            return {"apps": {"auth": {"identities": {}}}}

    def _capture(*a: Any, **k: Any) -> repos.ReconcilePlan:
        seen.update(k)
        return repos.ReconcilePlan()

    monkeypatch.setattr(cli, "_gitea_clients", lambda env: (_Admin(), None, "bot", "https://forge.invalid"))
    monkeypatch.setattr(cli, "ConfigurationManager", _Config)
    monkeypatch.setattr(cli, "_report_machine_ownership", lambda *a, **k: None)
    monkeypatch.setattr(
        repos,
        "load_declaration",
        lambda merged: {
            "teledyne": [RepoSpec("openkm-brain", migrate_from="github:x/openkm-brain"), RepoSpec("absent")]
        },
    )
    monkeypatch.setattr(repos, "load_settings", lambda merged: None)
    monkeypatch.setattr(repos, "load_webhooks", lambda merged: ())
    monkeypatch.setattr(repos, "plan_reconcile", _capture)

    result = CliRunner().invoke(cli.app, ["gitea", "reconcile"])

    assert result.exit_code == 0, result.output
    assert probed == ["teledyne/openkm-brain"], "only repositories the forge holds are probed"
    assert seen.get("existing_repo_refs") == {"teledyne/openkm-brain": False}
