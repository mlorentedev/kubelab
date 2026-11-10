"""AUTH-024 AC2 (#3148) -- a machine writer reaches the default branch through a pull request.

The agent account is a collaborator at `write` (AUTH-022), and `write` allows a direct
push to the default branch. The reconciler therefore protects the default branch of
every repository that lists `writers:`, with a push whitelist naming the human
operator and nobody else. Merging stays open to the writer by decision (2026-11-09):
the pull request is the record, so there is no merge whitelist and no approval count.

Measured on gitea/gitea:1.27.3 (see the comment on #3148): a site admin does NOT
bypass a protection rule, so the operator has to be NAMED; and every field read back
from `GET /branch_protections/{name}`, so this converges by comparison.
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest
import yaml

from tests.test_gitea_repo_reconcile import (
    ALL_REFS_PRESENT,
    DECLARED_SETTINGS,
    N8N_HOOK_ONLY,
    converged_for,
    hooks_for,
    settings_for,
)
from toolkit.features.gitea_client import GiteaClient, GiteaError
from toolkit.features.gitea_repos import (
    BranchProtection,
    BranchProtectionChange,
    BranchProtectionError,
    ReconcilePlan,
    RepoSpec,
    branch_protection_drift,
    ensure_branch_protection,
    execute,
    format_plan,
    load_branch_protection,
    plan_reconcile,
)

REPO = pathlib.Path(__file__).resolve().parent.parent
COMMON = REPO / "infra/config/values/common.yaml"

AGENT = "dedalo"
OPERATOR = "operator"
SUPERADMIN = "manu"


def _common() -> dict[str, Any]:
    return yaml.safe_load(COMMON.read_text(encoding="utf-8"))


DECLARED = BranchProtection(push_whitelist_usernames=(OPERATOR, SUPERADMIN))


def _live(**overrides: Any) -> dict[str, Any]:
    """A rule as Gitea reads it back once it satisfies DECLARED, plus fields we do not declare."""
    return {
        "rule_name": "main",
        "enable_push": True,
        "enable_push_whitelist": True,
        "push_whitelist_usernames": [OPERATOR, SUPERADMIN],
        "enable_merge_whitelist": False,
        "merge_whitelist_usernames": [],
        "required_approvals": 0,
        "block_admin_merge_override": False,
        "enable_status_check": False,
        **overrides,
    }


# --------------------------------------------------------------------------- the predicate


def test_a_matching_rule_has_no_drift_whatever_the_whitelist_order() -> None:
    assert branch_protection_drift(_live(), DECLARED) == ()


def test_an_absent_rule_drifts_on_every_declared_field() -> None:
    drift = branch_protection_drift(None, DECLARED)
    assert {key for key, _, _ in drift} == set(DECLARED.payload())


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"push_whitelist_usernames": [OPERATOR, SUPERADMIN, AGENT]}, "push_whitelist_usernames"),
        ({"push_whitelist_usernames": [OPERATOR]}, "push_whitelist_usernames"),
        ({"enable_push": False}, "enable_push"),
        ({"enable_push_whitelist": False}, "enable_push_whitelist"),
        ({"enable_merge_whitelist": True}, "enable_merge_whitelist"),
        ({"required_approvals": 1}, "required_approvals"),
    ],
)
def test_each_declared_field_is_drift(override: dict[str, Any], field: str) -> None:
    assert [key for key, _, _ in branch_protection_drift(_live(**override), DECLARED)] == [field]


def test_a_field_we_do_not_declare_is_not_drift() -> None:
    live = _live(block_admin_merge_override=True, enable_status_check=True, merge_whitelist_usernames=[AGENT])
    assert branch_protection_drift(live, DECLARED) == ()


def test_a_missing_field_in_the_live_body_is_drift_not_a_match() -> None:
    live = _live()
    del live["required_approvals"]
    assert [key for key, _, _ in branch_protection_drift(live, DECLARED)] == ["required_approvals"]


# --------------------------------------------------------------------------- the plan

WRITTEN = {"personal": [RepoSpec("tool", native=True, writers=(AGENT,))]}
UNWRITTEN = {"personal": [RepoSpec("tool", native=True)]}


def _plan(
    protections: dict[str, Any] | None,
    *,
    declared: dict[str, list[RepoSpec]] = WRITTEN,
    repos: dict[str, bool] | None = None,
    settings: dict[str, Any] | None = None,
    **kwargs: Any,
) -> ReconcilePlan:
    existing_repos = {"personal/tool": False} if repos is None else repos
    return plan_reconcile(
        declared,
        set(declared),
        existing_repos,
        converged_for(declared),
        settings if settings is not None else (settings_for(declared) if existing_repos else {"personal/tool": None}),
        DECLARED_SETTINGS,
        hooks_for(declared) if existing_repos else {"personal/tool": None},
        N8N_HOOK_ONLY,
        existing_repo_refs=ALL_REFS_PRESENT,
        existing_collaborators={"personal/tool": {AGENT: (True, "write")}} if declared is WRITTEN else {},
        declared_protection=DECLARED,
        existing_branch_protections=protections,
        **kwargs,
    )


def test_a_repository_with_writers_and_no_rule_is_planned_on_its_default_branch() -> None:
    plan = _plan({"personal/tool": None})
    (change,) = plan.branch_protections_to_converge
    assert (change.org, change.name, change.branch, change.rule_present) == ("personal", "tool", "main", False)
    assert not plan.is_noop


def test_the_branch_is_the_one_the_forge_reports_not_a_literal() -> None:
    settings = settings_for(WRITTEN)
    settings["personal/tool"] = {**settings["personal/tool"], "default_branch": "trunk"}  # type: ignore[dict-item]
    (change,) = _plan({"personal/tool": None}, settings=settings).branch_protections_to_converge
    assert change.branch == "trunk"


def test_a_converged_rule_is_a_noop() -> None:
    plan = _plan({"personal/tool": _live()})
    assert plan.branch_protections_to_converge == ()
    assert plan.is_noop


def test_an_extra_whitelisted_account_is_narrowed() -> None:
    plan = _plan({"personal/tool": _live(push_whitelist_usernames=[OPERATOR, SUPERADMIN, AGENT])})
    (change,) = plan.branch_protections_to_converge
    assert change.rule_present is True
    assert [key for key, _, _ in change.changes] == ["push_whitelist_usernames"]


def test_a_repository_without_writers_gets_nothing_even_when_it_has_a_rule() -> None:
    """Not this criterion: no rule is added, and an existing one is not removed."""
    plan = _plan({}, declared=UNWRITTEN)
    assert plan.branch_protections_to_converge == ()


def test_a_repository_missing_from_the_reads_raises() -> None:
    with pytest.raises(KeyError):
        _plan({})


def test_writers_without_the_protection_reads_raise_rather_than_plan_nothing() -> None:
    with pytest.raises(ValueError, match="existing_branch_protections"):
        _plan(None)


def test_a_held_repository_that_reports_no_default_branch_raises() -> None:
    settings = settings_for(WRITTEN)
    settings["personal/tool"] = {k: v for k, v in settings["personal/tool"].items() if k != "default_branch"}  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="default_branch"):
        _plan({"personal/tool": None}, settings=settings)


def test_an_absent_native_repository_gets_no_protection() -> None:
    assert _plan({"personal/tool": None}, repos={}).branch_protections_to_converge == ()


def test_a_repository_created_in_the_same_run_is_planned_with_no_branch_yet() -> None:
    created = {"personal": [RepoSpec("tool", writers=(AGENT,))]}
    plan = plan_reconcile(
        created,
        {"personal"},
        {},
        converged_for(created),
        {"personal/tool": None},
        DECLARED_SETTINGS,
        {"personal/tool": None},
        N8N_HOOK_ONLY,
        existing_repo_refs=ALL_REFS_PRESENT,
        existing_collaborators={"personal/tool": None},
        declared_protection=DECLARED,
        existing_branch_protections={"personal/tool": None},
    )
    (change,) = plan.branch_protections_to_converge
    assert change.branch is None
    assert change.absent is True
    assert {key for key, _, _ in change.changes} == set(DECLARED.payload())


def test_format_plan_names_the_field_and_both_values() -> None:
    text = format_plan(_plan({"personal/tool": _live(push_whitelist_usernames=[OPERATOR, SUPERADMIN, AGENT])}))
    assert "branch protection personal/tool:main" in text
    assert "push_whitelist_usernames" in text
    assert AGENT in text


def test_format_plan_for_a_missing_rule_says_so_once() -> None:
    text = format_plan(_plan({"personal/tool": None}))
    assert text.count("branch protection personal/tool:main") == 1
    assert "new rule" in text


# --------------------------------------------------------------------------- the declaration


def test_the_declaration_resolves_identity_keys_to_logins() -> None:
    protection = load_branch_protection(_common())
    identities = _common()["apps"]["auth"]["identities"]
    declared_keys = _common()["apps"]["services"]["core"]["gitea"]["branch_protection"]["push_exempt"]
    assert protection.push_whitelist_usernames == tuple(str(identities[k]) for k in declared_keys)
    assert protection.push_whitelist_usernames, "an empty whitelist locks the operator out"


def _declaring(exempt: Any, writers: list[str] | None = None) -> dict[str, Any]:
    return {
        "apps": {
            "auth": {
                "identities": {
                    "superadmin": SUPERADMIN,
                    "operator": OPERATOR,
                    "machine": "hefesto",
                    "reviewer": "mentor",
                    "agent": AGENT,
                }
            },
            "services": {
                "core": {
                    "gitea": {
                        "branch_protection": {"push_exempt": exempt},
                        "organizations": {
                            "personal": {"repositories": [{"name": "x", "origin": "native", "writers": writers or []}]}
                        },
                    }
                }
            },
        }
    }


def test_the_loader_resolves_a_valid_exemption() -> None:
    assert load_branch_protection(_declaring(["operator"])).push_whitelist_usernames == (OPERATOR,)


@pytest.mark.parametrize("key", ["agent", "machine", "reviewer"])
def test_a_machine_identity_may_not_be_exempt(key: str) -> None:
    with pytest.raises(ValueError, match=key):
        load_branch_protection(_declaring([key]))


def test_an_unknown_identity_key_raises() -> None:
    with pytest.raises(ValueError, match="nobody"):
        load_branch_protection(_declaring(["nobody"]))


def test_an_exempt_account_that_is_also_a_declared_writer_is_refused() -> None:
    """A writer that bypasses the protection defeats it."""
    with pytest.raises(ValueError, match="writer"):
        load_branch_protection(_declaring(["operator"], writers=["operator"]))


@pytest.mark.parametrize("exempt", [None, [], "operator"])
def test_an_absent_empty_or_malformed_exemption_raises(exempt: Any) -> None:
    with pytest.raises(ValueError, match="push_exempt"):
        load_branch_protection(_declaring(exempt))


def test_an_absent_block_raises() -> None:
    common = _declaring(["operator"])
    del common["apps"]["services"]["core"]["gitea"]["branch_protection"]
    with pytest.raises(ValueError, match="branch_protection"):
        load_branch_protection(common)


# --------------------------------------------------------------------------- the client


class _Recorder(GiteaClient):
    def __init__(self, response: Any = None, status_code: int | None = None) -> None:
        super().__init__("https://forge.invalid", token="unused")
        self.response = response
        self.status_code = status_code
        self.calls: list[tuple[str, str]] = []

    def _request(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        self.calls.append((method, endpoint))
        if self.status_code:
            raise GiteaError("refused", status_code=self.status_code)
        return self.response


def test_a_404_is_an_absent_rule() -> None:
    assert _Recorder(status_code=404).get_branch_protection("personal", "tool", "main") is None


@pytest.mark.parametrize("status_code", [403, 500])
def test_any_other_failure_reading_the_rule_raises(status_code: int) -> None:
    with pytest.raises(GiteaError):
        _Recorder(status_code=status_code).get_branch_protection("personal", "tool", "main")


def test_a_branch_with_a_slash_is_one_path_segment() -> None:
    client = _Recorder(response=_live())
    client.get_branch_protection("personal", "tool", "release/1.0")
    assert client.calls == [("GET", "/repos/personal/tool/branch_protections/release%2F1.0")]


# --------------------------------------------------------------------------- execute


class FakeConfigurator:
    """Holds one rule and applies writes the way the test says the forge does."""

    def __init__(self, stored: dict[str, Any] | None, *, applies: bool = True, default_branch: str = "main") -> None:
        self.stored = stored
        self.applies = applies
        self.default_branch = default_branch
        self.writes: list[tuple[str, str, dict[str, Any]]] = []

    def get_repo(self, owner: str, name: str) -> dict[str, Any]:
        return {"default_branch": self.default_branch}

    def get_branch_protection(self, owner: str, name: str, branch: str) -> dict[str, Any] | None:
        return self.stored

    def create_branch_protection(self, owner: str, name: str, payload: dict[str, Any]) -> None:
        self.writes.append(("POST", payload["rule_name"], payload))
        if self.applies:
            self.stored = _live(**payload)

    def edit_branch_protection(self, owner: str, name: str, branch: str, payload: dict[str, Any]) -> None:
        self.writes.append(("PATCH", branch, payload))
        if self.applies:
            self.stored = _live(**payload)


CHANGE_NEW = BranchProtectionChange(
    "personal", "tool", "main", rule_present=False, changes=(("enable_push", None, True),)
)
CHANGE_EDIT = BranchProtectionChange(
    "personal", "tool", "main", rule_present=True, changes=(("enable_push", False, True),)
)


def test_a_missing_rule_is_created_with_the_declared_fields_and_read_back() -> None:
    configurator = FakeConfigurator(None)
    ensure_branch_protection(configurator, CHANGE_NEW, DECLARED)  # type: ignore[arg-type]
    ((verb, branch, payload),) = configurator.writes
    assert (verb, branch) == ("POST", "main")
    assert payload == {"rule_name": "main", **DECLARED.payload()}


def test_an_existing_rule_is_edited_not_recreated() -> None:
    configurator = FakeConfigurator(_live(enable_push=False))
    ensure_branch_protection(configurator, CHANGE_EDIT, DECLARED)  # type: ignore[arg-type]
    ((verb, branch, payload),) = configurator.writes
    assert (verb, branch, payload) == ("PATCH", "main", DECLARED.payload())


def test_a_write_that_did_not_take_is_an_error() -> None:
    with pytest.raises(BranchProtectionError, match="accepted the request without applying it"):
        ensure_branch_protection(FakeConfigurator(None, applies=False), CHANGE_NEW, DECLARED)  # type: ignore[arg-type]


def test_a_whitelisted_account_the_forge_dropped_is_named_in_the_error() -> None:
    """Gitea keeps a whitelist entry only for an account with write on the repository; it drops the rest silently."""
    configurator = FakeConfigurator(None)
    original = configurator.create_branch_protection

    def dropping(owner: str, name: str, payload: dict[str, Any]) -> None:
        original(owner, name, {**payload, "push_whitelist_usernames": [SUPERADMIN]})

    configurator.create_branch_protection = dropping  # type: ignore[method-assign]
    with pytest.raises(BranchProtectionError, match=OPERATOR):
        ensure_branch_protection(configurator, CHANGE_NEW, DECLARED)  # type: ignore[arg-type]


def test_a_repository_created_this_run_reads_its_branch_from_the_forge_first() -> None:
    configurator = FakeConfigurator(None, default_branch="trunk")
    created = BranchProtectionChange(
        "personal", "tool", None, rule_present=False, changes=(("enable_push", None, True),), absent=True
    )
    ensure_branch_protection(configurator, created, DECLARED)  # type: ignore[arg-type]
    assert configurator.writes[0][:2] == ("POST", "trunk")


def _execute(plan: ReconcilePlan, configurator: Any = None, **kwargs: Any) -> Any:
    return execute(
        plan,
        admin=None,  # type: ignore[arg-type]
        bot=None,  # type: ignore[arg-type]
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhooks=N8N_HOOK_ONLY,
        configurator=configurator,
        **kwargs,
    )


def test_execute_applies_through_the_configurator_and_reports_it() -> None:
    report = _execute(
        ReconcilePlan(branch_protections_to_converge=(CHANGE_NEW,)),
        FakeConfigurator(None),
        declared_protection=DECLARED,
    )
    assert report.ok, report.failures
    assert report.branch_protections_applied == ["personal/tool:main"]


def test_execute_without_a_configurator_reports_the_rule_as_failed() -> None:
    report = _execute(ReconcilePlan(branch_protections_to_converge=(CHANGE_NEW,)), declared_protection=DECLARED)
    assert [target for target, _ in report.failures] == ["branch protection personal/tool"]


def test_execute_without_the_declaration_reports_the_rule_as_failed() -> None:
    report = _execute(ReconcilePlan(branch_protections_to_converge=(CHANGE_NEW,)), FakeConfigurator(None))
    assert [target for target, _ in report.failures] == ["branch protection personal/tool"]


def test_execute_reports_a_rule_that_did_not_take_as_a_failure() -> None:
    report = _execute(
        ReconcilePlan(branch_protections_to_converge=(CHANGE_NEW,)),
        FakeConfigurator(None, applies=False),
        declared_protection=DECLARED,
    )
    assert [target for target, _ in report.failures] == ["branch protection personal/tool"]
    assert report.branch_protections_applied == []


# --------------------------------------------------------------------------- the SSOT as shipped


def test_the_shipped_declaration_protects_the_agents_repository_and_exempts_no_machine() -> None:
    common = _common()
    identities = common["apps"]["auth"]["identities"]
    protection = load_branch_protection(common)
    machines = {str(identities[k]) for k in ("machine", "reviewer", "agent")}
    assert not machines & set(protection.push_whitelist_usernames)
    assert str(identities["superadmin"]) in protection.push_whitelist_usernames


# --------------------------------------------------------------------------- the CLI reads the rule


def test_the_reconcile_reads_the_rule_on_the_branch_the_forge_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """The planner can only use what the CLI reads: without this a deleted call site leaves
    the comparison defined, tested and never fed."""
    from typer.testing import CliRunner

    import toolkit.cli.services as cli
    import toolkit.features.gitea_repos as repos

    read: list[tuple[str, str, str]] = []
    seen: dict[str, Any] = {}

    class _Admin:
        def list_orgs(self) -> set[str]:
            return {"personal"}

        def list_repos(self) -> dict[str, bool]:
            return {"personal/tool": False}

        def get_team(self, org: str, name: str) -> None:
            return None

        def get_repo(self, owner: str, name: str) -> dict[str, Any]:
            return {"empty": False, "default_branch": "trunk"}

        def list_hooks(self, owner: str, name: str) -> list[dict[str, Any]]:
            return []

        def has_refs(self, owner: str, name: str) -> bool:
            return True

        def is_collaborator(self, owner: str, name: str, login: str) -> bool:
            return True

        def get_collaborator_permission(self, owner: str, name: str, login: str) -> str:
            return "write"

        def get_branch_protection(self, owner: str, name: str, branch: str) -> dict[str, Any]:
            read.append((owner, name, branch))
            return _live()

    class _Config:
        def __init__(self, *_a: object, **_k: object) -> None:
            pass

        def get_merged_config(self) -> dict[str, object]:
            return _common()

    def _capture(*a: Any, **k: Any) -> ReconcilePlan:
        seen.update(k)
        return ReconcilePlan()

    monkeypatch.setattr(cli, "_gitea_clients", lambda env: (_Admin(), None, "bot", "https://forge.invalid"))
    monkeypatch.setattr(cli, "ConfigurationManager", _Config)
    monkeypatch.setattr(cli, "_report_machine_ownership", lambda *a, **k: None)
    monkeypatch.setattr(repos, "load_declaration", lambda merged: WRITTEN)
    monkeypatch.setattr(repos, "plan_reconcile", _capture)

    result = CliRunner().invoke(cli.app, ["gitea", "reconcile"])

    assert result.exit_code == 0, result.output
    assert read == [("personal", "tool", "trunk")]
    assert seen["existing_branch_protections"] == {"personal/tool": _live()}
    assert seen["declared_protection"] == load_branch_protection(_common())
