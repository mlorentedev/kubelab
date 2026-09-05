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

from toolkit.features.gitea_client import TEAM_UNITS
from toolkit.features.gitea_repos import (
    TEAM_NAME,
    TEAM_PERMISSION,
    DeclaredRepo,
    ReconcilePlan,
    RepoSettings,
    RepoSettingsError,
    SettingsChange,
    TeamPermissionError,
    WebhookChange,
    WebhookError,
    WebhookSpec,
    ensure_settings,
    ensure_team,
    ensure_webhook,
    execute,
)

#: Live-body keys the declaration does NOT manage, carried by the fake so a
#: comparison that wrongly ranged over the whole repository body instead of over the
#: declared fields would be visible here rather than passing.
GITEA_LIVE_EXTRAS: dict[str, Any] = {"has_actions": True, "default_branch": "main"}

#: The settings every `execute` in this file is handed. A literal rather than the
#: SSOT: these tests are about WHICH CLIENT performs the PATCH and what happens when
#: it does not take, and pinning them to common.yaml would make an unrelated
#: declaration edit fail them for a reason that has nothing to do with what they
#: assert. The SSOT is read in `test_gitea_repo_reconcile.py`, where the declaration
#: is the subject.
DECLARED_SETTINGS = RepoSettings(
    default_merge_style="squash",
    has_pull_requests=True,
    allow_merge_commits=False,
    allow_squash_merge=True,
    allow_rebase=False,
    allow_rebase_explicit=False,
    allow_fast_forward_only_merge=False,
    default_delete_branch_after_merge=True,
    has_wiki=False,
    has_projects=False,
)

#: The webhook every `execute` in this file is handed. A literal for the same reason
#: `DECLARED_SETTINGS` is one: these tests are about which client writes and what
#: happens when the write does not take.
DECLARED_WEBHOOK = WebhookSpec(
    url="https://n8n.example/webhook/multi-forge-sync",
    content_type="json",
    events=("push", "pull_request"),
    active=True,
    branch_filter="*",
    type="gitea",
)

#: The secret every `execute` is handed. Not a real one and not read from SOPS: these
#: tests assert that a secret REACHES the write, never what it contains.
WEBHOOK_SECRET = "test-secret-not-a-real-one"


class FakeClient:
    """Records calls. One instance per credential, which is what makes the split visible."""

    def __init__(
        self,
        label: str,
        *,
        can_create_org_repo: bool = True,
        code_permission: str | None = TEAM_PERMISSION,
        includes_all_repositories: bool = True,
    ) -> None:
        self.label = label
        self.calls: list[tuple[str, Any]] = []
        self._can_create_org_repo = can_create_org_repo
        self._code_permission = code_permission
        # Gitea's OWN default is False. It reads back True here because
        # `create_team` now sends it; a team created before it did reads back
        # False forever, which is what the knob models.
        self._includes_all_repositories = includes_all_repositories
        self._teams: dict[tuple[str, str], dict[str, Any]] = {}
        self._repos: dict[tuple[str, str], dict[str, Any]] = {}
        self._hooks: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._next_hook_id = 1

    def create_org(self, name: str) -> dict[str, Any]:
        self.calls.append(("create_org", name))
        return {"username": name}

    def create_repo(self, org: str, name: str, private: bool = True) -> dict[str, Any]:
        self.calls.append(("create_repo", f"{org}/{name}"))
        return {"name": name}

    def migrate_repo(
        self,
        org: str,
        name: str,
        clone_addr: str,
        service: str,
        auth_token: str,
        private: bool = True,
    ) -> dict[str, Any]:
        # The credential is recorded so a test can assert it was PASSED rather than
        # merely accepted -- a migration that silently ran unauthenticated would
        # succeed against a public source and fail against every private one, which
        # is all three of the declared repositories.
        self.calls.append(("migrate_repo", f"{org}/{name}", clone_addr, service, auth_token))
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
            "units_map": self._units_map(),
            "includes_all_repositories": self._includes_all_repositories,
        }
        return self._teams[(org, name)]

    def _units_map(self) -> dict[str, str]:
        """Every unit the real payload sends, not just the one a test cares about.

        This used to be `{"repo.code": self._code_permission}`, which modelled a
        forge no `create_team` call could produce -- the real one sends a mode for
        each of `TEAM_UNITS`. It was harmless while nothing read the other units and
        stopped being harmless the moment a predicate compared the whole grant.

        Same failure mode as the `permission: "write"` echo this file already records: a
        fake narrower than the request it stands for reports a state the forge never
        returns, and every test built on it agrees with the fake rather than with
        Gitea.
        """
        units = {unit: TEAM_PERMISSION for unit in TEAM_UNITS}
        if self._code_permission is None:
            del units["repo.code"]
        else:
            units["repo.code"] = self._code_permission
        return units

    def edit_team(self, team_id: int, name: str, permission: str) -> dict[str, Any]:
        """Applies the whole grant, the way `PATCH /teams/{id}` does.

        THE REAL CALL SENDS EVERY FIELD, not only the one that happened to be
        wrong -- see `GiteaClient.edit_team`. A fake that moved
        `includes_all_repositories` alone modelled a narrower repair than the one
        the code performs, and a test built on it would report a team still
        missing `can_create_org_repo` after a call that in fact sets it.

        `permission` is NOT touched, and that is not an omission: the coarse mode
        reads back `none` on a correct team because the grant lives per unit. A
        fake that echoed `"write"` here is the fake this file used to have.

        Still widens and never narrows -- `TEAM_PERMISSION` is the only mode any
        caller passes, and `GiteaClient.edit_team` has no narrowing path.
        """
        self.calls.append(("edit_team", name))
        for key, team in self._teams.items():
            if team.get("id") == team_id:
                self._teams[key] = {
                    **team,
                    "can_create_org_repo": True,
                    "units_map": {unit: permission for unit in TEAM_UNITS},
                    "includes_all_repositories": True,
                }
                return self._teams[key]
        raise AssertionError(f"edit_team called for unknown team id {team_id}")

    def refuse_widening(self) -> None:
        """Model a forge where the PATCH is accepted and changes nothing.

        THE FIELD CHECKS IN `ensure_team` ARE POST-CONDITIONS, not preconditions:
        convergence runs first and repairs what it can, so a fixture carrying a
        defect `edit_team` would fix never reaches the guard that names it. Without
        this, a test asserting "a team that cannot create repositories is refused"
        silently becomes "a team that cannot create repositories is repaired" — it
        keeps passing for a while and then stops asserting anything.

        It is a state the forge can genuinely be in: Gitea refusing the edit, a
        token that lost `write:organization`, a concurrent change. Naming it is
        what keeps the guards under test.
        """

        def _refuse(team_id: int, name: str, permission: str) -> dict[str, Any]:
            self.calls.append(("edit_team", name))
            for team in self._teams.values():
                if team.get("id") == team_id:
                    return team
            raise AssertionError(f"edit_team called for unknown team id {team_id}")

        self.edit_team = _refuse  # type: ignore[method-assign]

    def add_team_member(self, team_id: int, username: str) -> dict[str, Any]:
        self.calls.append(("add_team_member", f"{team_id}:{username}"))
        return {}

    def edit_repo(self, owner: str, name: str, settings: Any) -> dict[str, Any]:
        """Applies what it was sent, and records it.

        THE RECORDED VALUE IS THE PAYLOAD, not the repository name, because the
        assertion worth making is that the whole declaration went out. A fake that
        recorded only the target would pass for an `execute` that sent one field.
        """
        self.calls.append(("edit_repo", f"{owner}/{name}", dict(settings)))
        self._repos.setdefault((owner, name), dict(GITEA_LIVE_EXTRAS)).update(settings)
        return self._repos[(owner, name)]

    def get_repo(self, owner: str, name: str) -> dict[str, Any] | None:
        self.calls.append(("get_repo", f"{owner}/{name}"))
        return self._repos.get((owner, name))

    def refuse_repo_edit(self) -> None:
        """Model a forge that answers 200 and applies nothing.

        THE SAME REASON `refuse_widening` EXISTS, one object over: the settings
        check in `ensure_settings` is a POST-CONDITION, so on a fake whose PATCH
        works it can never fire, and a test asserting "a PATCH that does not take is
        a failure" would quietly become "a PATCH takes".

        It is a state Gitea can genuinely be in. A 200 from `PATCH /repos/{o}/{r}`
        says the request was accepted, never that every field in it was applied --
        which is the entire reason the code re-reads instead of trusting the
        response.
        """

        def _refuse(owner: str, name: str, settings: Any) -> dict[str, Any]:
            self.calls.append(("edit_repo", f"{owner}/{name}", dict(settings)))
            return self._repos.setdefault((owner, name), dict(GITEA_LIVE_EXTRAS))

        self.edit_repo = _refuse  # type: ignore[method-assign]

    # ── webhooks ──────────────────────────────────────────────────────────────
    #
    # THE FAKE EXPANDS `pull_request` AND REDACTS THE SECRET, because the real forge
    # does both and a fake that does neither certifies a design the forge refuses.
    # This file already carries the scar: `create_team` used to echo `write` back,
    # modelling a Gitea that does not exist, and every test passed while the live
    # reconcile 500'd. Measured on `personal/resume`, 2026-09-04.

    def list_hooks(self, owner: str, name: str) -> list[dict[str, Any]]:
        self.calls.append(("list_hooks", f"{owner}/{name}"))
        return list(self._hooks.get((owner, name), []))

    def create_hook(self, owner: str, name: str, payload: Any) -> dict[str, Any]:
        # The whole payload is recorded, not the target, so a test can assert the
        # SECRET went out. A fake recording only the repository would pass for an
        # `execute` that registered an unsigned endpoint.
        self.calls.append(("create_hook", f"{owner}/{name}", dict(payload)))
        hook = self._store_hook(dict(payload), hook_id=self._next_hook_id)
        self._next_hook_id += 1
        self._hooks.setdefault((owner, name), []).append(hook)
        return hook

    def edit_hook(self, owner: str, name: str, hook_id: int, payload: Any) -> dict[str, Any]:
        self.calls.append(("edit_hook", f"{owner}/{name}", hook_id, dict(payload)))
        for index, existing in enumerate(self._hooks.get((owner, name), [])):
            if existing["id"] == hook_id:
                updated = self._store_hook(dict(payload), hook_id=hook_id)
                self._hooks[(owner, name)][index] = updated
                return updated
        raise AssertionError(f"edit_hook called for unknown hook id {hook_id}")

    def _store_hook(self, payload: dict[str, Any], hook_id: int) -> dict[str, Any]:
        """What Gitea gives BACK for what it was sent -- which is not what it was sent.

        Two divergences, both measured, both load-bearing:

        - `events` comes back EXPANDED. `pull_request` becomes nine entries, so a
          reconciler comparing for equality would never converge.
        - `config.secret` does not come back AT ALL, which is why the post-condition
          can prove the hook's shape and never its signature.
        """
        config = dict(payload.get("config") or {})
        config.pop("secret", None)
        events = set(payload.get("events") or ())
        if "pull_request" in events:
            events |= {
                "pull_request_assign",
                "pull_request_sync",
                "pull_request_label",
                "pull_request_milestone",
                "pull_request_review_request",
                "pull_request_comment",
                "pull_request_review",
            }
        return {
            "id": hook_id,
            "type": payload.get("type"),
            "active": payload.get("active"),
            "branch_filter": payload.get("branch_filter"),
            # Reversed so no assertion can quietly depend on ordering: the live forge
            # returned the POST's list and the GET's list in different orders.
            "events": sorted(events, reverse=True),
            "config": config,
            "authorization_header": "",
        }

    def seed_hook(self, owner: str, name: str, **overrides: Any) -> dict[str, Any]:
        """Put a converged hook on a repository, optionally bent out of shape."""
        hook = self._store_hook(
            {
                "type": DECLARED_WEBHOOK.type,
                "active": DECLARED_WEBHOOK.active,
                "branch_filter": DECLARED_WEBHOOK.branch_filter,
                "events": list(DECLARED_WEBHOOK.events),
                "config": {"url": DECLARED_WEBHOOK.url, "content_type": DECLARED_WEBHOOK.content_type},
            },
            hook_id=self._next_hook_id,
        )
        hook.update(overrides)
        self._next_hook_id += 1
        self._hooks.setdefault((owner, name), []).append(hook)
        return hook

    def refuse_hook_write(self) -> None:
        """Model a forge that accepts the write and stores nothing.

        THE THIRD `refuse_*` IN THIS FILE, and the reason has not changed: the check
        in `ensure_webhook` is a POST-CONDITION, so on a fake whose write works it
        can never fire, and a test asserting "a write that does not take is a
        failure" would quietly become "a write takes".
        """

        def _refuse(owner: str, name: str, payload: Any) -> dict[str, Any]:
            self.calls.append(("create_hook", f"{owner}/{name}", dict(payload)))
            return {}

        self.create_hook = _refuse  # type: ignore[method-assign]

    def kinds(self) -> set[str]:
        return {call[0] for call in self.calls}


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

    execute(
        _plan(),
        admin,
        bot,
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
    )

    assert ("create_org", "personal") in admin.calls
    assert "create_org" not in bot.kinds(), (
        "the bot created an organization. Gitea puts the creating account in the org's `Owners` "
        "team, so this is ADR-065 D1 violated at the moment of creation, not a style problem."
    )


def test_repositories_are_created_by_the_bot_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("toolkit.features.gitea_repos._handle_failure", _no_failures)
    admin, bot = FakeClient("admin"), FakeClient("bot")

    execute(
        _plan(),
        admin,
        bot,
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
    )

    assert ("create_repo", "personal/resume") in bot.calls
    assert "create_repo" not in admin.kinds(), (
        "the admin created a repository. It would work, and it would quietly put the superadmin "
        "where the machine identity belongs."
    )


def test_the_bot_is_added_to_a_write_team(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("toolkit.features.gitea_repos._handle_failure", _no_failures)
    admin, bot = FakeClient("admin"), FakeClient("bot")

    report = execute(
        _plan(),
        admin,
        bot,
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
    )

    assert ("add_team_member", "7:hefesto") in admin.calls
    assert report.teams_ensured == ["personal"]


def test_a_report_is_not_a_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """What was done is recorded separately from what was proposed."""
    monkeypatch.setattr("toolkit.features.gitea_repos._handle_failure", _no_failures)
    admin, bot = FakeClient("admin"), FakeClient("bot")

    report = execute(
        _plan(),
        admin,
        bot,
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
    )

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

    execute(
        plan, admin, bot, bot_username="hefesto", declared_settings=DECLARED_SETTINGS, declared_webhook=DECLARED_WEBHOOK
    )

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
    admin.refuse_widening()

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
    admin.refuse_widening()

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

    lying = LyingClient("admin")
    lying.refuse_widening()

    with pytest.raises(TeamPermissionError):
        ensure_team(lying, "personal", member="hefesto")


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

    report = execute(
        _two_org_plan(),
        admin,
        bot,
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
    )

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

    report = execute(
        _two_org_plan(),
        admin,
        bot,
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
    )

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

    report = execute(
        _two_org_plan(),
        admin,
        bot,
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
    )

    _, reason = report.failures[0]
    assert "write:organization" in reason


def test_a_run_with_no_failures_reports_ok() -> None:
    """The control: `ok` must be capable of being True, or the guards above prove nothing."""
    admin, bot = FakeClient("admin"), FakeClient("bot")

    report = execute(
        _two_org_plan(),
        admin,
        bot,
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
    )

    assert report.ok and report.failures == []


# =============================================================================
# Migration (PR2, AC3) -- the path that replaces "create it empty"
# =============================================================================


def test_a_migration_is_performed_by_the_migrator_never_by_a_token_client():
    """NO TOKEN MAY MIGRATE, and that is measured rather than assumed.

    Asking each credential to migrate an already-existing repository discriminates
    cleanly, because 409 means "you may, the target merely exists" while 403 means
    "you may not". Against live prod, 2026-09-02:

        bot token             -> 403 "Given user is not owner of organization."
        admin token           -> 403 required=[write:repository]
        superadmin basic auth -> 409 "The repository with the same name already exists."

    Two different walls. The bot is stopped by ORGANIZATION OWNERSHIP, which
    ADR-065 D1 requires it never to have -- so the bot cannot be fixed by widening
    a scope, only by violating D1. The admin token is stopped by SCOPE, and adding
    `write:repository` to it would hand the reconciler a standing delete capability
    (see `test_the_superadmin_token_is_never_granted_repository_writes`).

    So migration goes through the basic-auth session, exactly as `drop-empty` does,
    and this test pins the actor down: the migrator performs it, neither token
    client is asked, and the source credential reaches the call.
    """
    admin, bot, migrator = FakeClient("admin"), FakeClient("bot"), FakeClient("migrator")
    plan = ReconcilePlan(
        repos_to_migrate=(DeclaredRepo(org="personal", name="resume", migrate_from="github:mlorentedev/resume"),)
    )

    report = execute(
        plan,
        admin,
        bot,
        bot_username="hefesto",
        migration_token="TOKEN",
        migrator=migrator,
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
    )

    assert report.repos_migrated == ["personal/resume"]
    assert report.ok
    assert (
        "migrate_repo",
        "personal/resume",
        "https://github.com/mlorentedev/resume.git",
        "github",
        "TOKEN",
    ) in migrator.calls
    assert not [c for c in bot.calls if c[0] == "migrate_repo"], "the bot is refused by Gitea; do not ask it"
    assert not [c for c in admin.calls if c[0] == "migrate_repo"], "the admin token lacks write:repository"


def test_a_migration_without_a_migrator_is_refused_rather_than_attempted_with_a_token():
    """The tempting fallback is the one Gitea refuses; make it impossible to reach by accident."""
    admin, bot = FakeClient("admin"), FakeClient("bot")
    plan = ReconcilePlan(
        repos_to_migrate=(DeclaredRepo(org="personal", name="resume", migrate_from="github:mlorentedev/resume"),)
    )

    report = execute(
        plan,
        admin,
        bot,
        bot_username="hefesto",
        migration_token="TOKEN",
        migrator=None,
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
    )

    assert not report.ok
    assert report.repos_migrated == []
    assert not [c for c in bot.calls if c[0] == "migrate_repo"]
    assert "no migrator client" in report.failures[0][1]


def test_a_migration_without_a_credential_fails_loudly_rather_than_running_open():
    """No token means refused, never attempted.

    Attempting anyway would 404 against a private source -- GitHub does not confirm
    existence to an unauthorised caller -- and "the repository is gone" is exactly
    the wrong lesson to draw from that, as this spec's own AC5 measurement records.
    """
    admin, bot = FakeClient("admin"), FakeClient("bot")
    plan = ReconcilePlan(
        repos_to_migrate=(DeclaredRepo(org="personal", name="resume", migrate_from="github:mlorentedev/resume"),)
    )

    report = execute(
        plan,
        admin,
        bot,
        bot_username="hefesto",
        migration_token=None,
        migrator=FakeClient("m"),
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
    )

    assert not report.ok
    assert report.repos_migrated == []
    assert not [c for c in bot.calls if c[0] == "migrate_repo"]
    assert "migration credential" in report.failures[0][1]


def test_an_organization_receiving_only_a_migration_still_gets_the_write_team():
    """The bot needs the team to create a repository, and a migration creates one.

    Team preparation used to iterate `repos_to_create` alone. An organization whose
    only declared repository is a migration would then have been skipped, and the
    migration refused with the same "not allowed to create repository in
    organization" 403 that Risk 1 spent a session diagnosing.
    """
    admin, bot = FakeClient("admin"), FakeClient("bot")
    plan = ReconcilePlan(
        repos_to_migrate=(DeclaredRepo(org="personal", name="resume", migrate_from="github:mlorentedev/resume"),)
    )

    report = execute(
        plan,
        admin,
        bot,
        bot_username="hefesto",
        migration_token="TOKEN",
        migrator=FakeClient("m"),
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
    )

    assert report.teams_ensured == ["personal"]


def test_an_unknown_migration_service_is_refused_before_the_call():
    """Gitea falls back to a plain git clone on an unrecognised `service`.

    That drops issues, pull requests, labels, milestones and releases while
    reporting success -- so AC3 would be false and nothing would say so. Refused
    here instead, and the repository is reported as failed rather than migrated.
    """
    admin, bot = FakeClient("admin"), FakeClient("bot")
    plan = ReconcilePlan(
        repos_to_migrate=(DeclaredRepo(org="personal", name="resume", migrate_from="bitbucket:someone/resume"),)
    )

    report = execute(
        plan,
        admin,
        bot,
        bot_username="hefesto",
        migration_token="TOKEN",
        migrator=FakeClient("m"),
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
    )

    assert not report.ok
    assert report.repos_migrated == []
    assert not [c for c in bot.calls if c[0] == "migrate_repo"]
    assert "unknown migration service" in report.failures[0][1]


def test_the_migration_body_never_carries_the_credential_in_the_clone_address():
    """`auth_token` is a body field, not part of the URL.

    A credential inside `clone_addr` persists in Gitea's stored remote and surfaces
    in any error that echoes the address back -- and `GiteaError` echoes response
    bodies verbatim by design.
    """
    from toolkit.features.gitea_repos import parse_migration_source

    service, clone_addr = parse_migration_source("github:mlorentedev/resume")
    assert service == "github"
    assert clone_addr == "https://github.com/mlorentedev/resume.git"
    assert "@" not in clone_addr and "token" not in clone_addr.lower()


def test_a_team_whose_units_cover_no_repository_is_refused():
    """The scope half of a grant, which every other check here takes for granted.

    Measured on prod 2026-09-03: both live `reconcilers` teams read back
    `repo.code -> write` and `can_create_org_repo -> True` while covering zero
    repositories, so the bot could read the migrated repositories and push to
    none of them. Every assertion in `ensure_team` passed.

    Lesson-416 on a permission: an empty scope is not a weak grant, it is a grant
    over nothing, and it is indistinguishable from a correct one in every
    field-level check.
    """
    admin = FakeClient("admin", includes_all_repositories=False)
    admin._teams[("personal", TEAM_NAME)] = {
        "id": 7,
        "name": TEAM_NAME,
        "permission": "none",
        "can_create_org_repo": True,
        "units_map": {"repo.code": TEAM_PERMISSION},
        "includes_all_repositories": False,
    }
    # Model a forge that refuses to widen, so the guard is what raises rather
    # than the convergence quietly repairing the fixture out from under it.
    admin.refuse_widening()

    with pytest.raises(TeamPermissionError, match="includes_all_repositories"):
        ensure_team(admin, "personal")


def test_a_pre_existing_narrow_team_is_widened_rather_than_refused():
    """Both live teams were born before the flag was sent, so refusing is useless.

    `ensure_team` only ever created. A team that predates the current payload
    keeps what it was born with and no amount of re-running fixes it — raising
    would fail every reconcile until someone edited the forge by hand, which is
    the manual step this feature exists to remove.
    """
    admin = FakeClient("admin", includes_all_repositories=False)
    admin._teams[("personal", TEAM_NAME)] = {
        "id": 7,
        "name": TEAM_NAME,
        "permission": "none",
        "can_create_org_repo": True,
        "units_map": {"repo.code": TEAM_PERMISSION},
        "includes_all_repositories": False,
    }

    team = ensure_team(admin, "personal")

    assert ("edit_team", TEAM_NAME) in admin.calls, "a narrow team must be widened, not left alone"
    assert team["includes_all_repositories"] is True


def test_widening_is_not_attempted_on_a_team_that_already_covers_everything():
    """Idempotence, AC1's property, on the path that would otherwise write every run.

    A reconcile that PATCHed the team on every pass would report work forever on a
    converged forge — the same failure `plan_reconcile` avoids by treating presence
    as presence.
    """
    admin = FakeClient("admin")
    admin.create_team("personal", TEAM_NAME, TEAM_PERMISSION)
    admin.calls.clear()

    ensure_team(admin, "personal")

    assert not [c for c in admin.calls if c[0] == "edit_team"], "converged team was widened again"


def test_a_freshly_created_team_covers_the_organization():
    """The create path and the converge path must agree on the end state.

    If `create_team` stopped sending the flag, only the pre-existing-team test
    above would fail — and someone reading it could reasonably conclude the
    convergence covers the gap. It does not: it runs after creation on the same
    pass, so a create that omits the flag is repaired invisibly rather than
    caught. This asserts the end state of the create path on its own.
    """
    admin = FakeClient("admin")

    team = ensure_team(admin, "personal")

    assert team["includes_all_repositories"] is True
    assert ("create_team", f"personal/{TEAM_NAME}") in admin.calls


def test_a_team_repair_runs_on_an_organization_receiving_nothing() -> None:
    """The reachability half. Without it the repair is correct, tested, and never called.

    Measured on prod 2026-09-03, after `create_team` learned to send
    `includes_all_repositories` and the PR merged green: both live teams still
    covered zero repositories. `execute` iterated only the organizations RECEIVING a
    new repository, and every declared repository already existed.

    So the plan below is the production state: nothing to create, one team to
    repair. If `execute` goes back to iterating `receiving` alone, `edit_team` is
    never reached and this fails.
    """
    admin = FakeClient("admin", includes_all_repositories=False)
    admin._teams[("personal", TEAM_NAME)] = {
        "id": 7,
        "name": TEAM_NAME,
        "permission": "none",
        "can_create_org_repo": True,
        "units_map": {unit: TEAM_PERMISSION for unit in TEAM_UNITS},
        "includes_all_repositories": False,
    }
    bot = FakeClient("bot")

    report = execute(
        ReconcilePlan(teams_to_converge=("personal",)),
        admin,
        bot,
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
    )

    assert report.ok, f"the repair failed: {report.failures}"
    assert ("edit_team", TEAM_NAME) in admin.calls, (
        "an organization with a team to repair and no repository to create was never visited"
    )
    assert report.teams_ensured == ["personal"]
    assert bot.calls == [], "the bot has no part in a team repair; the grant is the superadmin's to give"


def test_a_team_repair_is_skipped_when_its_organization_could_not_be_created() -> None:
    """`failed_orgs` still quarantines the cascade after the union.

    An organization whose creation failed has no team to widen, and attempting one
    turns a single root cause into two reported failures.
    """

    class RefusingAdmin(FakeClient):
        def create_org(self, name: str) -> dict[str, Any]:
            self.calls.append(("create_org", name))
            raise RuntimeError("no")

    admin = RefusingAdmin("admin")
    bot = FakeClient("bot")

    report = execute(
        ReconcilePlan(orgs_to_create=("personal",), teams_to_converge=("personal",)),
        admin,
        bot,
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
    )

    assert not report.ok
    assert [target for target, _ in report.failures] == ["org personal"]
    assert "create_team" not in admin.kinds() and "edit_team" not in admin.kinds()


# ---------------------------------------------------------------------------
# Repository settings (TOOL-063, #1633)
#
# The same two questions the rest of this file asks, on the second operation no
# token may perform: which credential performs it, and does the code believe the
# response or read the state back.
# ---------------------------------------------------------------------------


def _settings_plan() -> ReconcilePlan:
    return ReconcilePlan(
        repos_to_configure=(
            SettingsChange(
                org="personal",
                name="resume",
                changes=(("default_merge_style", "merge", "squash"),),
            ),
        )
    )


def test_settings_are_applied_by_the_configurator_never_by_a_token_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Measured 2026-09-04: no token may do this, and one of them must never be able to.

    `admin_token` is refused at the scope layer (`required=[write:repository]`), a
    scope this line of work keeps off it because it is a standing DELETE capability.
    The bot is refused by repo permission on every repository it did not itself
    create. So the call belongs to the superadmin's basic-auth client, and asserting
    that HERE is what stops a later edit from routing it through the token clients
    already in scope -- which would work in a test with a permissive fake and fail
    against the forge.
    """
    monkeypatch.setattr("toolkit.features.gitea_repos._handle_failure", _no_failures)
    admin, bot, configurator = FakeClient("admin"), FakeClient("bot"), FakeClient("configurator")

    report = execute(
        _settings_plan(),
        admin,
        bot,
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
        configurator=configurator,
    )

    assert report.repos_configured == ["personal/resume"]
    assert "edit_repo" not in admin.kinds(), "the admin token is refused by scope; it must not be tried"
    assert "edit_repo" not in bot.kinds(), "the bot is only repo-admin where it created the repository"
    assert ("edit_repo", "personal/resume", DECLARED_SETTINGS.to_api_payload()) in configurator.calls


def test_the_whole_declaration_is_sent_not_only_the_fields_that_drifted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The plan carries a diff; the PATCH carries the declaration.

    Sending only the drifted fields would be defensible right up to the first
    concurrent change, and it would make the post-condition weaker than the
    declaration: a field that had drifted between the read and the write would go
    unsent and unchecked. The plan's diff exists to make the printed plan
    reviewable, not to narrow what is applied.
    """
    monkeypatch.setattr("toolkit.features.gitea_repos._handle_failure", _no_failures)
    configurator = FakeClient("configurator")

    execute(
        _settings_plan(),
        FakeClient("admin"),
        FakeClient("bot"),
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
        configurator=configurator,
    )

    sent = next(call[2] for call in configurator.calls if call[0] == "edit_repo")
    assert sent == DECLARED_SETTINGS.to_api_payload()
    assert len(sent) > 1, "only the drifted field was sent; the plan's diff is not the payload"


def test_settings_without_a_configurator_are_refused_rather_than_attempted_with_a_token() -> None:
    """Fail loudly, and say which credential is needed.

    The alternative -- falling back to a token client -- is what the measurement
    forbids, and it would fail with a 403 whose text points at scopes rather than at
    the missing argument.
    """
    report = execute(
        _settings_plan(),
        FakeClient("admin"),
        FakeClient("bot"),
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
        configurator=None,
    )

    assert not report.ok
    assert [target for target, _ in report.failures] == ["settings personal/resume"]
    assert "GiteaBasicAuthClient" in report.failures[0][1]
    assert report.repos_configured == []


def test_a_patch_that_is_accepted_and_does_nothing_is_a_failure() -> None:
    """The whole reason `ensure_settings` re-reads instead of trusting the 200.

    Gitea answers 200 to a PATCH whose fields it did not apply. Without the
    read-back the run would report a converged forge that still merges with merge
    commits -- and the NEXT run would find the same drift and report success again,
    forever. That is not a failing reconciler, it is one that cannot fail.
    """
    configurator = FakeClient("configurator")
    configurator.refuse_repo_edit()

    report = execute(
        _settings_plan(),
        FakeClient("admin"),
        FakeClient("bot"),
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
        configurator=configurator,
    )

    assert not report.ok
    assert report.repos_configured == [], "a repository that did not converge must not be reported as configured"
    reason = report.failures[0][1]
    assert "did not converge" in reason
    assert "default_merge_style" in reason, "the failure must name the fields, not just the repository"


def test_ensure_settings_raises_its_own_category() -> None:
    """A distinct exception, for the same reason `TeamPermissionError` is one.

    The failure is silent by nature -- a successful request that changed nothing --
    so it must not arrive as a generic error indistinguishable from a network fault.
    """
    configurator = FakeClient("configurator")
    configurator.refuse_repo_edit()

    with pytest.raises(RepoSettingsError):
        ensure_settings(
            configurator,  # type: ignore[arg-type]
            SettingsChange(org="personal", name="resume"),
            DECLARED_SETTINGS,
        )


def test_a_repository_whose_migration_failed_is_not_configured() -> None:
    """One root cause, one reported failure.

    A repository whose migration failed does not exist, so PATCHing it would add a
    second failure naming a symptom -- `404` -- while the cause sits above it in the
    same report. Same quarantine as `failed_orgs`, one level down.
    """

    class RefusingMigrator(FakeClient):
        def migrate_repo(self, org: str, name: str, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("migrate_repo", f"{org}/{name}"))
            raise RuntimeError("migration refused")

    migrator = RefusingMigrator("migrator")
    configurator = FakeClient("configurator")
    repo = DeclaredRepo(org="personal", name="resume", migrate_from="github:mlorentedev/resume")

    report = execute(
        ReconcilePlan(
            repos_to_migrate=(repo,),
            repos_to_configure=(SettingsChange(org="personal", name="resume", absent=True),),
        ),
        FakeClient("admin"),
        FakeClient("bot"),
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
        migration_token="TOKEN",
        migrator=migrator,
        configurator=configurator,
    )

    assert [target for target, _ in report.failures] == ["repo personal/resume"]
    assert "edit_repo" not in configurator.kinds()


def test_a_repository_created_by_this_run_is_configured_by_this_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Settings run AFTER the creates, and reach what the same run brought into being.

    A repository arrives with Gitea's permissive defaults however it got there, so
    scoping this step to repositories that already existed would leave every new one
    unconfigured until the next run -- lesson-424's shape read backwards. The
    ordering is what makes it work: PATCHing before the create would 404.
    """
    monkeypatch.setattr("toolkit.features.gitea_repos._handle_failure", _no_failures)
    bot = FakeClient("bot")
    configurator = FakeClient("configurator")

    report = execute(
        ReconcilePlan(
            repos_to_create=(DeclaredRepo(org="personal", name="brand-new"),),
            repos_to_configure=(SettingsChange(org="personal", name="brand-new", absent=True),),
        ),
        FakeClient("admin"),
        bot,
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
        configurator=configurator,
    )

    assert report.repos_created == ["personal/brand-new"]
    assert report.repos_configured == ["personal/brand-new"]


def test_the_report_distinguishes_configured_from_created() -> None:
    """`ExecutionReport` is an observation, and the two are different observations.

    A run whose only work was a settings repair produces no created repository and
    no created organization; collapsing the fields would make it indistinguishable
    from a run that did nothing at all.
    """
    configurator = FakeClient("configurator")

    report = execute(
        _settings_plan(),
        FakeClient("admin"),
        FakeClient("bot"),
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
        configurator=configurator,
    )

    assert report.repos_configured == ["personal/resume"]
    assert report.repos_created == [] and report.orgs_created == [] and report.repos_migrated == []
    assert report.ok


# ── webhooks (#503) ───────────────────────────────────────────────────────────
#
# The third write this module performs and the one with the quietest failure. A
# hook that exists but is signed wrong delivers successfully, gets HTTP 200 from
# n8n's `multi-forge-sync`, and is dropped without a trace -- so the forge's
# delivery log, the surface anyone would check, stays green over an integration
# processing nothing. Everything below is written against that.


def _hook_plan(absent: bool = True, hook_id: int | None = None) -> ReconcilePlan:
    return ReconcilePlan(
        repos_to_hook=(
            WebhookChange(
                org="personal",
                name="resume",
                hook_id=hook_id,
                changes=(("url", None, DECLARED_WEBHOOK.url),),
                absent=absent,
                url=DECLARED_WEBHOOK.url,
            ),
        ),
    )


def test_a_webhook_is_written_by_the_configurator_never_by_a_token_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Measured 2026-09-04, both repositories, so the answer is not one repo's provenance.

    admin token 403 required=[write:repository]; bot token 403 "owner or a
    collaborator with admin write"; superadmin basic auth 201.
    """
    monkeypatch.setattr("toolkit.features.gitea_repos._handle_failure", _no_failures)
    admin, bot, configurator = FakeClient("admin"), FakeClient("bot"), FakeClient("configurator")

    execute(
        _hook_plan(),
        admin,
        bot,
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
        webhook_secret=WEBHOOK_SECRET,
        configurator=configurator,
    )

    assert "create_hook" in configurator.kinds()
    assert "create_hook" not in admin.kinds() and "create_hook" not in bot.kinds()


def test_the_secret_reaches_the_write(monkeypatch: pytest.MonkeyPatch) -> None:
    """The one field the post-condition can never verify, so the test verifies the REQUEST.

    Gitea does not return `config.secret`, which means a hook written without one
    converges perfectly and processes nothing. The only place the secret is
    observable is on its way out (lesson-423: assert what leaves the process).
    """
    monkeypatch.setattr("toolkit.features.gitea_repos._handle_failure", _no_failures)
    admin, bot, configurator = FakeClient("admin"), FakeClient("bot"), FakeClient("configurator")

    execute(
        _hook_plan(),
        admin,
        bot,
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
        webhook_secret=WEBHOOK_SECRET,
        configurator=configurator,
    )

    payload = next(call[2] for call in configurator.calls if call[0] == "create_hook")
    assert payload["config"]["secret"] == WEBHOOK_SECRET
    assert payload["config"]["url"] == DECLARED_WEBHOOK.url
    assert payload["config"]["content_type"] == DECLARED_WEBHOOK.content_type


def test_a_webhook_without_a_secret_is_refused_rather_than_written_unsigned() -> None:
    """A missing secret must STOP the write, never degrade it.

    An unsigned hook is worse than no hook: it delivers, n8n rejects the signature,
    and n8n's rejection path answers 200 and drops the event. The forge would then
    record a successful delivery for every event it failed to deliver -- a broken
    integration that looks healthier than a missing one.
    """
    admin, bot, configurator = FakeClient("admin"), FakeClient("bot"), FakeClient("configurator")

    report = execute(
        _hook_plan(),
        admin,
        bot,
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
        webhook_secret=None,
        configurator=configurator,
    )

    assert "create_hook" not in configurator.kinds()
    assert not report.ok
    assert any("secret" in message for _target, message in report.failures)


def test_a_webhook_without_a_configurator_is_refused_rather_than_attempted_with_a_token() -> None:
    admin, bot = FakeClient("admin"), FakeClient("bot")

    report = execute(
        _hook_plan(),
        admin,
        bot,
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
        webhook_secret=WEBHOOK_SECRET,
        configurator=None,
    )

    assert "create_hook" not in admin.kinds() and "create_hook" not in bot.kinds()
    assert not report.ok


def test_an_existing_hook_is_patched_in_place_rather_than_recreated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The id carries the delivery history, which is the only record of what was sent.

    On an integration whose failure mode is a silent drop, that history is the
    evidence a future debugging session will want -- so a drifted hook is updated,
    never deleted and remade.
    """
    monkeypatch.setattr("toolkit.features.gitea_repos._handle_failure", _no_failures)
    admin, bot, configurator = FakeClient("admin"), FakeClient("bot"), FakeClient("configurator")
    seeded = configurator.seed_hook("personal", "resume", active=False)

    execute(
        _hook_plan(absent=False, hook_id=seeded["id"]),
        admin,
        bot,
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
        webhook_secret=WEBHOOK_SECRET,
        configurator=configurator,
    )

    assert "edit_hook" in configurator.kinds()
    assert "create_hook" not in configurator.kinds()
    assert [hook["id"] for hook in configurator._hooks[("personal", "resume")]] == [seeded["id"]]


def test_the_full_config_is_sent_on_an_update_not_only_the_field_that_drifted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whether a partial `config` clears the omitted keys is UNMEASURED, so it is avoided.

    If omitting `secret` cleared it, an update that fixed `active` would silently
    unsign the hook -- and the resulting breakage is invisible on both sides.
    """
    monkeypatch.setattr("toolkit.features.gitea_repos._handle_failure", _no_failures)
    admin, bot, configurator = FakeClient("admin"), FakeClient("bot"), FakeClient("configurator")
    seeded = configurator.seed_hook("personal", "resume", active=False)

    execute(
        _hook_plan(absent=False, hook_id=seeded["id"]),
        admin,
        bot,
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
        webhook_secret=WEBHOOK_SECRET,
        configurator=configurator,
    )

    payload = next(call[3] for call in configurator.calls if call[0] == "edit_hook")
    assert payload["config"]["secret"] == WEBHOOK_SECRET, "an update that omits the secret may unsign the hook"
    assert set(payload["config"]) == {"url", "content_type", "secret"}


def test_a_write_that_is_accepted_and_stores_nothing_is_a_failure() -> None:
    """The post-condition, and the reason `ensure_webhook` re-reads instead of trusting.

    A 2xx says the request was accepted, never that the hook exists afterwards.
    """
    admin, bot, configurator = FakeClient("admin"), FakeClient("bot"), FakeClient("configurator")
    configurator.refuse_hook_write()

    report = execute(
        _hook_plan(),
        admin,
        bot,
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
        webhook_secret=WEBHOOK_SECRET,
        configurator=configurator,
    )

    assert not report.ok
    assert report.repos_hooked == []


def test_gitea_s_event_expansion_is_not_read_as_a_failed_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression this whole design exists for, asserted end to end.

    The fake expands `pull_request` into nine and returns them in a different order,
    exactly as the forge does. Under an equality post-condition every `--apply` would
    fail on a hook it had just written correctly -- not churn, a hard red run.
    """
    monkeypatch.setattr("toolkit.features.gitea_repos._handle_failure", _no_failures)
    admin, bot, configurator = FakeClient("admin"), FakeClient("bot"), FakeClient("configurator")

    report = execute(
        _hook_plan(),
        admin,
        bot,
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
        webhook_secret=WEBHOOK_SECRET,
        configurator=configurator,
    )

    stored = configurator._hooks[("personal", "resume")][0]["events"]
    assert len(stored) > len(DECLARED_WEBHOOK.events), "the fake must expand, or this asserts nothing"
    assert report.repos_hooked == ["personal/resume"]
    assert report.ok


def test_a_hook_that_lost_a_declared_event_is_a_failure() -> None:
    """The floor is a floor in both directions: a SHORTFALL must still be caught.

    A superset comparison that accepted anything would be the vacuous version of
    this design -- passing for a hook subscribed to nothing at all.
    """
    configurator = FakeClient("configurator")
    change = WebhookChange(org="personal", name="resume", url=DECLARED_WEBHOOK.url)
    configurator.seed_hook("personal", "resume", events=["pull_request"])

    def _keep_as_seeded(owner: str, name: str, payload: Any) -> dict[str, Any]:
        configurator.calls.append(("create_hook", f"{owner}/{name}", dict(payload)))
        return configurator._hooks[(owner, name)][0]

    configurator.create_hook = _keep_as_seeded  # type: ignore[method-assign]

    with pytest.raises(WebhookError) as exc:
        ensure_webhook(configurator, change, DECLARED_WEBHOOK, WEBHOOK_SECRET)

    assert "push" in str(exc.value), "the failure must name the event that is missing"


def test_a_repository_whose_migration_failed_gets_no_webhook() -> None:
    """One reported failure, not two, and the second naming a symptom.

    A repository that did not arrive has no hooks endpoint to POST to.
    """
    admin, bot, configurator = FakeClient("admin"), FakeClient("bot"), FakeClient("configurator")
    plan = ReconcilePlan(
        repos_to_migrate=(DeclaredRepo(org="personal", name="resume", migrate_from="github:mlorentedev/resume"),),
        repos_to_hook=(WebhookChange(org="personal", name="resume", url=DECLARED_WEBHOOK.url, absent=True),),
    )

    report = execute(
        plan,
        admin,
        bot,
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
        webhook_secret=WEBHOOK_SECRET,
        migration_token=None,
        migrator=None,
        configurator=configurator,
    )

    assert "create_hook" not in configurator.kinds()
    assert [target for target, _ in report.failures] == ["repo personal/resume"]


def test_the_report_distinguishes_hooked_from_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """A report is an observation, not a plan replayed back."""
    monkeypatch.setattr("toolkit.features.gitea_repos._handle_failure", _no_failures)
    admin, bot, configurator = FakeClient("admin"), FakeClient("bot"), FakeClient("configurator")

    report = execute(
        _hook_plan(),
        admin,
        bot,
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhook=DECLARED_WEBHOOK,
        webhook_secret=WEBHOOK_SECRET,
        configurator=configurator,
    )

    assert report.repos_hooked == ["personal/resume"]
    assert report.repos_configured == [] and report.repos_created == []
