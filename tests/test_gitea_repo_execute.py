"""TOOL-035 (#1076) — the execution half: who calls what, and the team read-back.

The planning half is asserted in `test_gitea_repo_reconcile.py` and is pure. This
file covers the part that talks to Gitea, and it covers exactly two things worth
covering:

1. **The actor split is honoured at the call site**, not merely declared by
   `actor_for_*`. ADR-065 D1 makes "the bot owns nothing" an acceptance
   criterion, and Gitea grants ownership to whoever creates an organization, so a
   test that only checks the declaration would pass for an `execute` that used
   the wrong client.

2. **`ensure_team` refuses a team that does not grant what it asked for**, and
   checks the fields that actually govern rather than the one that looks like it
   does. Three measured refusals, each of which looked like the whole answer:

   - 2026-08-27: `units` + `permission: "write"` -> read back as `none`.
   - 2026-09-02: no `units` -> HTTP 500, `units permission should not be empty`.
   - 2026-09-02: `units_map` alone -> team created, bot still refused with
     `Given user is not allowed to create repository in organization`.

   The resolution is that `permission` is the team's COARSE access mode and reads
   `none` on a *correct* team, while `can_create_org_repo` is what actually
   governs repository creation. The old check asserted the coarse field, so it
   refused correct teams and would have gone on refusing them however the payload
   was rewritten.

   The fake below was the reason this took three tries: it echoed `write` back
   from `create_team`, modelling a forge that does not exist. Every test here
   passed while the real reconcile 500'd. A fake that encodes a wrong belief
   about a system does not fail -- it certifies the belief.

Fakes rather than mocks, because the assertions are about which client received
which call. A `Mock` would let a typo pass as a recorded call.
"""

from __future__ import annotations

from typing import Any

import pytest

from toolkit.features.gitea_repos import (
    TEAM_NAME,
    TEAM_PERMISSION,
    DeclaredRepo,
    ReconcilePlan,
    TeamPermissionError,
    ensure_team,
    execute,
)


class FakeClient:
    """Records calls. One instance per credential, which is what makes the split visible."""

    def __init__(
        self,
        label: str,
        *,
        can_create_org_repo: bool = True,
        code_permission: str | None = TEAM_PERMISSION,
    ) -> None:
        self.label = label
        self.calls: list[tuple[str, Any]] = []
        self._can_create_org_repo = can_create_org_repo
        self._code_permission = code_permission
        self._teams: dict[tuple[str, str], dict[str, Any]] = {}

    def create_org(self, name: str) -> dict[str, Any]:
        self.calls.append(("create_org", name))
        return {"username": name}

    def create_repo(self, org: str, name: str, private: bool = True) -> dict[str, Any]:
        self.calls.append(("create_repo", f"{org}/{name}"))
        return {"name": name}

    def get_team(self, org: str, name: str) -> dict[str, Any] | None:
        return self._teams.get((org, name))

    def create_team(self, org: str, name: str, permission: str) -> dict[str, Any]:
        self.calls.append(("create_team", f"{org}/{name}"))
        # The measured Gitea behaviour: what comes back is not what was asked for.
        # `permission` is HARDCODED to "none" because that is what a correct team
        # reads back as -- the coarse access mode is none whenever the grant lives
        # per unit, which on Gitea 1.25 is always. A fake that echoed "write" here
        # is the fake this file used to have, and it modelled a forge that does
        # not exist: every test built on it passed while the real reconcile 500'd.
        # The two knobs are the fields that actually govern.
        self._teams[(org, name)] = {
            "id": 7,
            "name": name,
            "permission": "none",
            "can_create_org_repo": self._can_create_org_repo,
            "units_map": {"repo.code": self._code_permission},
        }
        return self._teams[(org, name)]

    def add_team_member(self, team_id: int, username: str) -> dict[str, Any]:
        self.calls.append(("add_team_member", f"{team_id}:{username}"))
        return {}

    def kinds(self) -> set[str]:
        return {kind for kind, _ in self.calls}


def _plan() -> ReconcilePlan:
    return ReconcilePlan(
        orgs_to_create=("personal",),
        repos_to_create=(DeclaredRepo(org="personal", name="resume"),),
    )


def _no_failures(*_args: Any, **_kwargs: Any) -> None:
    """Stand-in policy for the happy-path tests, which never reach it."""
    raise AssertionError("no operation should have failed in this fixture")


def test_organizations_are_created_by_the_admin_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("toolkit.features.gitea_repos._handle_failure", _no_failures)
    admin, bot = FakeClient("admin"), FakeClient("bot")

    execute(_plan(), admin, bot, bot_username="hefesto")

    assert ("create_org", "personal") in admin.calls
    assert "create_org" not in bot.kinds(), (
        "the bot created an organization. Gitea puts the creating account in the org's `Owners` "
        "team, so this is ADR-065 D1 violated at the moment of creation, not a style problem."
    )


def test_repositories_are_created_by_the_bot_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("toolkit.features.gitea_repos._handle_failure", _no_failures)
    admin, bot = FakeClient("admin"), FakeClient("bot")

    execute(_plan(), admin, bot, bot_username="hefesto")

    assert ("create_repo", "personal/resume") in bot.calls
    assert "create_repo" not in admin.kinds(), (
        "the admin created a repository. It would work, and it would quietly put the superadmin "
        "where the machine identity belongs."
    )


def test_the_bot_is_added_to_a_write_team(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("toolkit.features.gitea_repos._handle_failure", _no_failures)
    admin, bot = FakeClient("admin"), FakeClient("bot")

    report = execute(_plan(), admin, bot, bot_username="hefesto")

    assert ("add_team_member", "7:hefesto") in admin.calls
    assert report.teams_ensured == ["personal"]


def test_a_report_is_not_a_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """What was done is recorded separately from what was proposed."""
    monkeypatch.setattr("toolkit.features.gitea_repos._handle_failure", _no_failures)
    admin, bot = FakeClient("admin"), FakeClient("bot")

    report = execute(_plan(), admin, bot, bot_username="hefesto")

    assert report.orgs_created == ["personal"]
    assert report.repos_created == ["personal/resume"]
    assert report.ok


def test_execute_never_deletes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strays travel to the report, never to a call.

    The plan already has no field a deletion could occupy; this asserts the
    execution half does not invent one from the stray lists.
    """
    monkeypatch.setattr("toolkit.features.gitea_repos._handle_failure", _no_failures)
    admin, bot = FakeClient("admin"), FakeClient("bot")
    plan = ReconcilePlan(undeclared_orgs=("legacy",), undeclared_repos=("legacy/old",))

    execute(plan, admin, bot, bot_username="hefesto")

    assert admin.calls == [] and bot.calls == [], (
        "a plan containing only strays produced API calls. Strays are reported, never acted on (#1076 scope)."
    )


# --- the Risk 1 residual, with a measured repro ------------------------------


def test_a_team_that_cannot_create_repositories_is_refused() -> None:
    """Measured 2026-09-02: units_map at write, flag unset -> the bot is still refused.

    `Given user is not allowed to create repository in organization` -- a 403 with
    a body that says nothing about scopes, unlike the other 403 in this area.
    """
    admin = FakeClient("admin", can_create_org_repo=False)

    with pytest.raises(TeamPermissionError) as exc:
        ensure_team(admin, "personal", member="hefesto")

    assert "can_create_org_repo" in str(exc.value)
    assert ("add_team_member", "7:hefesto") not in admin.calls, (
        "the bot was added to a team that cannot create repositories. The later refusal is a 403 "
        "identical in status to a missing token scope, pointing the reader at the wrong layer."
    )


def test_a_team_that_cannot_push_is_refused() -> None:
    """Creating a repository and pushing to it are different grants.

    `can_create_org_repo` covers the first; `units_map["repo.code"]` covers the
    second. A team with the flag and a read-only code unit would create empty
    repositories nobody could fill, which is the worse failure: it looks like it
    worked.
    """
    admin = FakeClient("admin", code_permission="read")

    with pytest.raises(TeamPermissionError) as exc:
        ensure_team(admin, "personal", member="hefesto")

    assert "repo.code" in str(exc.value)


def test_a_team_granting_write_is_accepted() -> None:
    """The control. Without it the guards above pass for a function that always raises.

    Note the assertion deliberately expects `permission == "none"`: that is what a
    CORRECT team reads back as, and asserting it here is what stops someone
    "fixing" the coarse field back into the check.
    """
    admin = FakeClient("admin")

    team = ensure_team(admin, "personal", member="hefesto")

    assert team["permission"] == "none"
    assert team["can_create_org_repo"] is True
    assert team["units_map"]["repo.code"] == TEAM_PERMISSION
    assert ("add_team_member", "7:hefesto") in admin.calls


def test_the_team_is_read_back_rather_than_trusted() -> None:
    """A create response claiming a good grant does not settle it; the re-read does.

    This fake returns a usable team from `create_team` and stores an unusable one,
    which is the disagreement the real forge produced on 2026-08-27. A reconciler
    trusting the response would pass; one that re-reads catches it.
    """

    class LyingClient(FakeClient):
        def create_team(self, org: str, name: str, permission: str) -> dict[str, Any]:
            self.calls.append(("create_team", f"{org}/{name}"))
            self._teams[(org, name)] = {
                "id": 7,
                "name": name,
                "permission": "none",
                "can_create_org_repo": False,
                "units_map": {"repo.code": TEAM_PERMISSION},
            }
            return {
                "id": 7,
                "name": name,
                "permission": "none",
                "can_create_org_repo": True,
                "units_map": {"repo.code": TEAM_PERMISSION},
            }

    with pytest.raises(TeamPermissionError):
        ensure_team(LyingClient("admin"), "personal", member="hefesto")


def test_an_existing_team_is_not_recreated() -> None:
    """Idempotence: a second run finds the team and creates nothing."""
    admin = FakeClient("admin")
    admin._teams[("personal", TEAM_NAME)] = {
        "id": 7,
        "name": TEAM_NAME,
        "permission": "none",
        "can_create_org_repo": True,
        "units_map": {"repo.code": TEAM_PERMISSION},
    }

    ensure_team(admin, "personal", member="hefesto")

    assert "create_team" not in admin.kinds()


# --- the failure policy: collect, do not abort -------------------------------


class BrokenOrgClient(FakeClient):
    """Refuses to create one named organization, succeeds at everything else."""

    def __init__(self, label: str, refuse: str) -> None:
        super().__init__(label)
        self.refuse = refuse

    def create_org(self, name: str) -> dict[str, Any]:
        self.calls.append(("create_org", name))
        if name == self.refuse:
            raise RuntimeError("Gitea API POST /orgs -> 403: required=[write:organization]")
        return {"username": name}


def _two_org_plan() -> ReconcilePlan:
    return ReconcilePlan(
        orgs_to_create=("personal", "teledyne"),
        repos_to_create=(
            DeclaredRepo(org="personal", name="resume"),
            DeclaredRepo(org="teledyne", name="fae-brain"),
        ),
    )


def test_one_failed_org_does_not_stop_the_others() -> None:
    """The whole point of collecting: a first run reports every failure, not the first.

    A token minted without `write:organization` refuses EVERY organization, and a
    run that aborted would report one failure where there are several -- which
    reads as "this org is odd" instead of "this credential is wrong".
    """
    admin, bot = BrokenOrgClient("admin", refuse="personal"), FakeClient("bot")

    report = execute(_two_org_plan(), admin, bot, bot_username="hefesto")

    assert ("create_org", "teledyne") in admin.calls, "a later organization was skipped after an earlier one failed"
    assert report.orgs_created == ["teledyne"]
    assert not report.ok


def test_a_failed_orgs_repositories_are_skipped_not_failed() -> None:
    """The cascade is quarantined, and it is quarantined without inflating the count.

    `personal/resume` cannot be created because its organization does not exist.
    Attempting it would produce a second, derivative failure pointing at the wrong
    thing; recording it as failed would report two problems where there is one.
    """
    admin, bot = BrokenOrgClient("admin", refuse="personal"), FakeClient("bot")

    report = execute(_two_org_plan(), admin, bot, bot_username="hefesto")

    assert ("create_repo", "personal/resume") not in bot.calls
    assert ("create_repo", "teledyne/fae-brain") in bot.calls
    assert report.repos_created == ["teledyne/fae-brain"]
    assert [target for target, _ in report.failures] == ["org personal"]


def test_the_failure_message_keeps_gitea_s_own_diagnostics() -> None:
    """`required=[...]` is what tells a scope problem from a permission problem.

    Both answer 403 -- the trap AUTH-004 AC5 recorded once. Collapsing the message
    to "creation failed" throws away the only text that distinguishes them.
    """
    admin, bot = BrokenOrgClient("admin", refuse="personal"), FakeClient("bot")

    report = execute(_two_org_plan(), admin, bot, bot_username="hefesto")

    _, reason = report.failures[0]
    assert "write:organization" in reason


def test_a_run_with_no_failures_reports_ok() -> None:
    """The control: `ok` must be capable of being True, or the guards above prove nothing."""
    admin, bot = FakeClient("admin"), FakeClient("bot")

    report = execute(_two_org_plan(), admin, bot, bot_username="hefesto")

    assert report.ok and report.failures == []
