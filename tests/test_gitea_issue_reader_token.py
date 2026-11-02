"""CONSOLE-004 (#2570) -- the forge task view reads Gitea with a token of its own, and it can only read.

The API lists issues and pull requests across the forge. The only token in the fleet that
could already do that is the reviewer's (`write:issue,read:repository`), and it must not:
the API's Secret lives behind a different trust boundary than PR-Agent's, rotating one would
rotate the other, and a leaked copy would be able to comment on and edit issues.

It is a third token on the reviewer's account, not a new account. Reads leave no authorship,
the account already sits in each organization's read team, and an account costs a team
membership per organization that a token does not. So everything the review-notice token has
is mirrored: a grant read from `common.yaml` and pinned by equality, a mint gated on the
recorded secret being absent, a record over stdin, a catalog entry and a rotation entry.
What differs is the grant (read-only) and the consumer (the API).
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

from toolkit.features.gitea_tokens import ISSUE_READER_SCOPES, REVIEWER_SCOPES, ROTATABLE_TOKENS

REPO = pathlib.Path(__file__).resolve().parent.parent
COMMON = REPO / "infra/config/values/common.yaml"
ROLE = REPO / "infra/ansible/roles/beelink_services"
PLAYBOOK = REPO / "infra/ansible/playbooks/provision-bee.yml"

READER_TOKEN_KEY = "apps.services.core.gitea.issue_reader_token"
MINT_TASK = "Mint the issue-reader token on the reviewer account"
RECORD_TASK = "Record the issue-reader token in SOPS"


def _task(name: str) -> dict[str, Any]:
    for task in yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8")):
        if isinstance(task, dict) and task.get("name") == name:
            return task
    raise AssertionError(f"no task named {name!r} in beelink_services/tasks/main.yml")


def test_the_grant_reads_issues_and_nothing_else() -> None:
    """EQUALITY, in both directions: a reader that can write is the token this one exists to avoid."""
    declared = yaml.safe_load(COMMON.read_text(encoding="utf-8"))["apps"]["services"]["core"]["gitea"]["token_scopes"]
    grant = {s.strip() for s in declared["issue_reader"].split(",") if s.strip()}

    assert grant == set(ISSUE_READER_SCOPES), (
        f"the issue-reader grant is {sorted(grant)}, the decided scope is {sorted(ISSUE_READER_SCOPES)}"
    )
    assert all(s.startswith("read:") for s in grant), "the reader must not hold any write scope"
    assert not grant & set(REVIEWER_SCOPES) - {"read:repository"}, "it must not inherit the reviewer's write scope"


def test_it_is_rotatable_on_the_reviewer_account_under_its_own_name() -> None:
    reader = ROTATABLE_TOKENS["issue_reader"]
    others = [t for label, t in ROTATABLE_TOKENS.items() if label != "issue_reader"]

    assert reader.identity == ROTATABLE_TOKENS["reviewer"].identity, "one account, several tokens"
    assert reader.token_name not in {t.token_name for t in others}, "Gitea refuses two tokens of one name on an account"
    assert reader.secret_key == READER_TOKEN_KEY


def test_the_token_is_catalogued_with_the_api_as_its_consumer() -> None:
    from toolkit.features.secrets_manager import SECRET_CATALOG, Expiry, SecretKind

    spec = next((s for s in SECRET_CATALOG if s.key_path == READER_TOKEN_KEY), None)
    assert spec is not None, f"{READER_TOKEN_KEY} is not in SECRET_CATALOG, so no audit can report it absent"
    assert spec.kind is SecretKind.EXTERNAL, "Gitea mints it; a locally generated string would authenticate nothing"
    assert spec.expiry is Expiry.NEVER, "Gitea tokens carry no expiry field; see the bot_token entry"
    assert "api" in spec.services, "the API is the consumer; the audit names who breaks when this rotates"
    assert "pr-agent" not in spec.services, "the reviewer pod must not be a consumer of the reader token"


def test_the_playbook_reads_the_grant_and_the_secret_from_the_ssot() -> None:
    playbook = PLAYBOOK.read_text(encoding="utf-8")

    assert "token_scopes.issue_reader" in playbook, "the grant must come from common.yaml, not a literal"
    assert "gitea_secrets.apps.services.core.gitea.issue_reader_token" in playbook


def test_it_is_minted_once_with_the_declared_grant_on_the_reviewer_account() -> None:
    task = _task(MINT_TASK)
    assert task.get("no_log") is True
    assert "issue_reader_token" in str(task.get("when") or ""), "an ungated mint issues a new live token every run"
    command = " ".join(task["command"]["argv"])
    assert "--username {{ gitea_reviewer_user }}" in command
    assert f"--token-name {ROTATABLE_TOKENS['issue_reader'].token_name}" in command
    assert "--scopes {{ gitea_issue_reader_scopes }}" in command


def test_it_is_recorded_over_stdin_under_its_own_key() -> None:
    task = _task(RECORD_TASK)
    assert task.get("no_log") is True
    assert f"toolkit secrets set {READER_TOKEN_KEY}" in task["command"]
    assert "--stdin" in task["command"]
    assert "issue_reader_token" in str(task.get("when") or "")


def test_a_reader_minted_wider_than_declared_reads_as_drift() -> None:
    """The live check separates the tokens of one account by NAME, so a reader that gained a write scope shows."""
    from toolkit.features.gitea_tokens import ScopeVerdict, check_token_scopes

    listing = [
        {"id": 1, "name": ROTATABLE_TOKENS["reviewer"].token_name, "scopes": ["write:issue", "read:repository"]},
        {"id": 3, "name": ROTATABLE_TOKENS["issue_reader"].token_name, "scopes": ["read:issue", "write:issue"]},
    ]

    result = check_token_scopes("issue_reader", "read:issue", listing)

    assert result.verdict is ScopeVerdict.UNDECLARED
    assert result.undeclared == frozenset({"write:issue"})
