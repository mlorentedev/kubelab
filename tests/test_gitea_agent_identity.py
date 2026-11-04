"""AUTH-022 (#2577) -- agents author on the forge as their own machine account, not as the superadmin.

The account (`apps.auth.identities.agent`) is minted like the reviewer's: created by
`gitea-bootstrap.sh`, its token minted by Ansible into SOPS with a grant pinned by
equality, rotatable, catalogued. What differs is how far its write reaches. It is in
no organization team, so `write:repository` reaches only the repositories that list
it under `writers:`, where the reconciler makes it a collaborator at `write`.
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
from toolkit.features.gitea_repos import (
    WRITER_PERMISSION,
    CollaboratorError,
    CollaboratorGrant,
    RepoSpec,
    collaborator_needs_grant,
    ensure_collaborator,
    execute,
    format_plan,
    load_declaration,
    plan_reconcile,
)
from toolkit.features.gitea_tokens import AGENT_SCOPES, ROTATABLE_TOKENS

REPO = pathlib.Path(__file__).resolve().parent.parent
COMMON = REPO / "infra/config/values/common.yaml"
ROLE = REPO / "infra/ansible/roles/beelink_services"
PLAYBOOK = REPO / "infra/ansible/playbooks/provision-bee.yml"
MAKEFILE = REPO / "Makefile"

AGENT_TOKEN_KEY = "apps.services.core.gitea.agent_token"
AGENT = "dedalo"


def _common() -> dict[str, Any]:
    return yaml.safe_load(COMMON.read_text(encoding="utf-8"))


def _tasks() -> list[dict[str, Any]]:
    return [t for t in yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8")) if isinstance(t, dict)]


def _task(name: str) -> dict[str, Any]:
    for task in _tasks():
        if task.get("name") == name:
            return task
    raise AssertionError(f"no task named {name!r} in beelink_services/tasks/main.yml")


# --------------------------------------------------------------------------- the identity and its token


def test_the_agent_is_a_declared_identity_of_its_own() -> None:
    identities = _common()["apps"]["auth"]["identities"]
    assert identities.get("agent"), "apps.auth.identities.agent is not declared"
    others = {v for k, v in identities.items() if k != "agent"}
    assert identities["agent"] not in others, "the agent must not share an account with another identity"


def test_the_grant_is_exactly_issue_and_repository_write() -> None:
    declared = _common()["apps"]["services"]["core"]["gitea"]["token_scopes"]["agent"]
    grant = {s.strip() for s in declared.split(",") if s.strip()}
    assert grant == set(AGENT_SCOPES), f"agent grant {sorted(grant)} != decided {sorted(AGENT_SCOPES)}"
    assert not any(s.endswith(":admin") or s.endswith(":user") or s.endswith(":organization") for s in grant)


def test_it_is_rotatable_on_its_own_account_under_its_own_name() -> None:
    agent = ROTATABLE_TOKENS["agent"]
    others = [t for label, t in ROTATABLE_TOKENS.items() if label != "agent"]
    assert agent.identity == "agent"
    assert agent.secret_key == AGENT_TOKEN_KEY
    assert agent.token_name not in {t.token_name for t in others}


def test_the_token_is_catalogued() -> None:
    from toolkit.features.secrets_manager import SECRET_CATALOG, Expiry, SecretKind

    spec = next((s for s in SECRET_CATALOG if s.key_path == AGENT_TOKEN_KEY), None)
    assert spec is not None, f"{AGENT_TOKEN_KEY} is not in SECRET_CATALOG"
    assert spec.kind is SecretKind.EXTERNAL
    assert spec.expiry is Expiry.NEVER
    assert spec.envs == ("prod",)
    assert "secrets-copy-gitea-agent-token" in spec.rotate_note, "a re-mint must say how the Bitwarden copy follows"


def test_the_playbook_reads_the_grant_and_the_secret_from_the_ssot() -> None:
    playbook = PLAYBOOK.read_text(encoding="utf-8")
    assert "identities.agent" in playbook
    assert "token_scopes.agent" in playbook
    assert "gitea_secrets.apps.services.core.gitea.agent_token" in playbook


def test_the_bootstrap_creates_the_account_and_compose_names_it() -> None:
    script = (ROLE / "files/gitea-bootstrap.sh").read_text(encoding="utf-8")
    compose = (ROLE / "templates/compose.yml.j2").read_text(encoding="utf-8")
    assert 'ensure_machine_account "$GITEA_AGENT_USER" "$GITEA_AGENT_EMAIL"' in script
    assert 'GITEA_AGENT_USER: "{{ gitea_agent_user }}"' in compose


def test_it_is_minted_once_with_the_declared_grant() -> None:
    task = _task("Mint the agent account's scoped token")
    assert task.get("no_log") is True
    assert "agent_token" in str(task.get("when") or ""), "an ungated mint issues a new live token every run"
    command = " ".join(task["command"]["argv"])
    assert "--username {{ gitea_agent_user }}" in command
    assert f"--token-name {ROTATABLE_TOKENS['agent'].token_name}" in command
    assert "--scopes {{ gitea_agent_scopes }}" in command


def test_it_is_recorded_over_stdin_under_its_own_key() -> None:
    task = _task("Record the agent token in SOPS")
    assert task.get("no_log") is True
    assert f"toolkit secrets set {AGENT_TOKEN_KEY}" in task["command"]
    assert "--stdin" in task["command"]


def test_the_orphan_guards_cover_the_agent_token() -> None:
    """#2902: a token minted with no recorder, or orphaned in Gitea, must be caught for this one too."""
    revoke = _task("Revoke a named token that Gitea holds and SOPS does not")
    assert any(item["name"] == ROTATABLE_TOKENS["agent"].token_name for item in revoke["loop"])
    assert "gitea_agent_token" in str(_task("Assert the controller can record a minted token")["when"])


def test_the_bitwarden_copy_never_puts_the_value_in_argv() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")
    start = makefile.index("secrets-copy-gitea-agent-token:")
    recipe = makefile[start : makefile.index("\n\n", start)]
    assert 'printf %s "$$V" | dotf secrets set GITEA_KUBELAB_AGENT_TOKEN' in recipe
    assert "test -n" in recipe, "an empty read must not overwrite the Bitwarden copy"


# --------------------------------------------------------------------------- the declaration


def test_imagesensortool_declares_the_agent_as_its_writer() -> None:
    declared = load_declaration(_common())
    spec = next(s for s in declared["personal"] if s.name == "imagesensortool")
    assert spec.writers == (_common()["apps"]["auth"]["identities"]["agent"],)
    others = [s for org, specs in declared.items() for s in specs if s.name != "imagesensortool"]
    assert all(not s.writers for s in others), "the agent's write is declared on imagesensortool only"


def _declaring(writers: list[str]) -> dict[str, Any]:
    return {
        "apps": {
            "auth": {"identities": {"superadmin": "manu", "reviewer": "mentor", "agent": AGENT}},
            "services": {"core": {"gitea": {"organizations": {"personal": {"repositories": [
                {"name": "x", "origin": "native", "writers": writers}
            ]}}}}},
        }
    }


@pytest.mark.parametrize("key", ["reviewer", "superadmin", "nobody"])
def test_the_loader_refuses_a_writer_it_must_not_grant(key: str) -> None:
    with pytest.raises(ValueError, match=key):
        load_declaration(_declaring([key]))


def test_the_loader_resolves_keys_to_logins() -> None:
    assert load_declaration(_declaring(["agent"]))["personal"][0].writers == (AGENT,)


# --------------------------------------------------------------------------- the plan

WRITTEN = {"personal": [RepoSpec("tool", native=True, writers=(AGENT,))]}


def _plan(collaborators: dict[str, Any], *, repos: dict[str, bool] | None = None) -> Any:
    existing_repos = {"personal/tool": False} if repos is None else repos
    settings = {k: v for k, v in settings_for(WRITTEN).items()} if existing_repos else {"personal/tool": None}
    return plan_reconcile(
        WRITTEN,
        set(WRITTEN),
        existing_repos,
        converged_for(WRITTEN),
        settings,
        DECLARED_SETTINGS,
        hooks_for(WRITTEN) if existing_repos else {"personal/tool": None},
        N8N_HOOK_ONLY,
        existing_repo_refs=ALL_REFS_PRESENT,
        existing_collaborators=collaborators,
    )


def test_a_writer_that_is_not_a_collaborator_is_planned_even_when_its_mode_reads_read() -> None:
    """Measured: the permission endpoint answers `read` on a public repository for an account with no grant."""
    plan = _plan({"personal/tool": {AGENT: (False, "read")}})
    assert plan.collaborators_to_grant == (CollaboratorGrant("personal", "tool", AGENT, None),)
    assert not plan.is_noop


def test_a_converged_writer_is_a_noop() -> None:
    assert _plan({"personal/tool": {AGENT: (True, WRITER_PERMISSION)}}).is_noop


def test_an_admin_collaborator_is_narrowed_to_write() -> None:
    plan = _plan({"personal/tool": {AGENT: (True, "admin")}})
    assert plan.collaborators_to_grant == (CollaboratorGrant("personal", "tool", AGENT, "admin"),)
    assert "dedalo: admin -> write" in format_plan(plan)


def test_a_repository_missing_from_the_reads_raises() -> None:
    with pytest.raises(KeyError):
        _plan({})


def test_an_absent_native_repository_gets_no_grant() -> None:
    """Nothing creates it, so there is nothing to grant on (ADR-065 D5)."""
    plan = _plan({"personal/tool": None}, repos={})
    assert plan.collaborators_to_grant == ()


def test_the_predicate_needs_the_collaborator_row_and_the_mode() -> None:
    assert collaborator_needs_grant(None)
    assert collaborator_needs_grant((False, "write"))
    assert collaborator_needs_grant((True, "read"))
    assert not collaborator_needs_grant((True, "write"))


# --------------------------------------------------------------------------- execute


class FakeConfigurator:
    def __init__(self, reads_back: tuple[bool, str]) -> None:
        self.reads_back = reads_back
        self.puts: list[tuple[str, str, str, str]] = []

    def add_collaborator(self, owner: str, name: str, username: str, permission: str) -> None:
        self.puts.append((owner, name, username, permission))

    def is_collaborator(self, owner: str, name: str, username: str) -> bool:
        return self.reads_back[0]

    def get_collaborator_permission(self, owner: str, name: str, username: str) -> str:
        return self.reads_back[1]


GRANT = CollaboratorGrant("personal", "tool", AGENT, None)


def test_ensure_collaborator_puts_write_and_reads_it_back() -> None:
    configurator = FakeConfigurator((True, "write"))
    ensure_collaborator(configurator, GRANT)  # type: ignore[arg-type]
    assert configurator.puts == [("personal", "tool", AGENT, "write")]


def test_a_put_that_did_not_take_is_an_error() -> None:
    with pytest.raises(CollaboratorError, match="accepted the request without applying it"):
        ensure_collaborator(FakeConfigurator((False, "read")), GRANT)  # type: ignore[arg-type]


def test_execute_grants_through_the_configurator_and_reports_it() -> None:
    from toolkit.features.gitea_repos import ReconcilePlan

    configurator = FakeConfigurator((True, "write"))
    report = execute(
        ReconcilePlan(collaborators_to_grant=(GRANT,)),
        admin=None,  # type: ignore[arg-type]
        bot=None,  # type: ignore[arg-type]
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhooks=N8N_HOOK_ONLY,
        configurator=configurator,  # type: ignore[arg-type]
    )
    assert report.ok, report.failures
    assert report.collaborators_granted == [("personal/tool", AGENT)]


def test_execute_without_a_configurator_reports_the_grant_as_failed() -> None:
    from toolkit.features.gitea_repos import ReconcilePlan

    report = execute(
        ReconcilePlan(collaborators_to_grant=(GRANT,)),
        admin=None,  # type: ignore[arg-type]
        bot=None,  # type: ignore[arg-type]
        bot_username="hefesto",
        declared_settings=DECLARED_SETTINGS,
        declared_webhooks=N8N_HOOK_ONLY,
    )
    assert [target for target, _ in report.failures] == ["collaborator personal/tool"]
