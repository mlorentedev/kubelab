"""TOOL-093 (#1957) -- the token n8n uses to tell a PR its review failed is narrower than the reviewer's.

When PR-Agent cannot review (the model's reply is cut, or the chain is exhausted) it
posts nothing, so the PR looks merely unreviewed. n8n comments on the PR to say so.
That workflow is reachable from the internet and its token must not be the reviewer's
(`write:issue,read:repository`): the owner decided on 2026-10-18 that n8n holds a token
of its own that can write comments and nothing else.

It is a second token on the reviewer's account, not a third account. The comment is
authored by the same identity that would have posted the review, which is what a reader
expects, and an account costs a team membership per organization that a token does not.
So everything the reviewer's token has is mirrored here: a grant read from `common.yaml`
and pinned by equality, a mint gated on the recorded secret being absent, a record over
stdin, a catalog entry and a rotation entry. What differs is the grant and the consumer.

Why `write:issue` alone is enough: measured 2026-09-24 in a local Gitea 1.25.5
(`specs/TOOL-080-forge-pr-reviewer/verification.md`), `POST issues/{n}/comments` answers
201 for a token holding only `write:issue`. It cannot read the PR, which is the point.
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

from toolkit.features.gitea_tokens import REVIEW_NOTICE_SCOPES, REVIEWER_SCOPES, ROTATABLE_TOKENS

REPO = pathlib.Path(__file__).resolve().parent.parent
COMMON = REPO / "infra/config/values/common.yaml"
ROLE = REPO / "infra/ansible/roles/beelink_services"
PLAYBOOK = REPO / "infra/ansible/playbooks/provision-bee.yml"

NOTICE_TOKEN_KEY = "apps.services.core.gitea.review_notice_token"
MINT_TASK = "Mint the review-notice token on the reviewer account"
RECORD_TASK = "Record the review-notice token in SOPS"


def _task(name: str) -> dict[str, Any]:
    for task in yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8")):
        if isinstance(task, dict) and task.get("name") == name:
            return task
    raise AssertionError(f"no task named {name!r} in beelink_services/tasks/main.yml")


def test_the_grant_is_comments_and_nothing_else() -> None:
    """EQUALITY, in both directions, for the reason the reviewer's grant is pinned that way.

    This token sits in a workflow behind a public route. Wider than `write:issue` and a
    leaked value can do more than comment; the `read:repository` the reviewer holds is
    exactly what it must NOT have, since reading the PR is not part of the job.
    """
    declared = yaml.safe_load(COMMON.read_text(encoding="utf-8"))["apps"]["services"]["core"]["gitea"]["token_scopes"]
    grant = {s.strip() for s in declared["review_notice"].split(",") if s.strip()}

    assert grant == set(REVIEW_NOTICE_SCOPES), (
        f"the review-notice grant is {sorted(grant)}, the decided scope is {sorted(REVIEW_NOTICE_SCOPES)}"
    )
    assert REVIEW_NOTICE_SCOPES < REVIEWER_SCOPES, "the notice token must be strictly narrower than the reviewer's"
    assert not any(s.startswith("read:") for s in grant), "a notice that can read what it comments on is too wide"


def test_it_is_rotatable_on_the_reviewer_account_under_its_own_name() -> None:
    notice = ROTATABLE_TOKENS["review_notice"]
    reviewer = ROTATABLE_TOKENS["reviewer"]

    assert notice.identity == reviewer.identity, "one account, two tokens"
    assert notice.token_name != reviewer.token_name, "Gitea refuses two tokens of one name on an account"
    assert notice.secret_key == NOTICE_TOKEN_KEY


def test_the_token_is_catalogued_like_the_reviewers() -> None:
    from toolkit.features.secrets_manager import SECRET_CATALOG, Expiry, SecretKind

    spec = next((s for s in SECRET_CATALOG if s.key_path == NOTICE_TOKEN_KEY), None)
    assert spec is not None, f"{NOTICE_TOKEN_KEY} is not in SECRET_CATALOG, so no audit can report it absent"
    assert spec.kind is SecretKind.EXTERNAL, "Gitea mints it; a locally generated string would authenticate nothing"
    assert spec.expiry is Expiry.NEVER, "Gitea tokens carry no expiry field; see the bot_token entry"
    assert "n8n" in spec.services, "n8n is the consumer; the audit names who breaks when this rotates"
    assert "pr-agent" not in spec.services, "the reviewer pod must not be a consumer of the notice token"


def test_the_playbook_reads_the_grant_and_the_secret_from_the_ssot() -> None:
    playbook = PLAYBOOK.read_text(encoding="utf-8")

    assert "token_scopes.review_notice" in playbook, "the grant must come from common.yaml, not a literal"
    assert "gitea_secrets.apps.services.core.gitea.review_notice_token" in playbook


def test_it_is_minted_once_with_the_declared_grant_on_the_reviewer_account() -> None:
    task = _task(MINT_TASK)
    assert task.get("no_log") is True
    assert "review_notice_token" in str(task.get("when") or ""), "an ungated mint issues a new live token every run"
    command = " ".join(task["command"]["argv"])
    assert "--username {{ gitea_reviewer_user }}" in command
    assert f"--token-name {ROTATABLE_TOKENS['review_notice'].token_name}" in command
    assert "--scopes {{ gitea_review_notice_scopes }}" in command


def test_it_is_recorded_over_stdin_under_its_own_key() -> None:
    task = _task(RECORD_TASK)
    assert task.get("no_log") is True
    assert f"toolkit secrets set {NOTICE_TOKEN_KEY}" in task["command"]
    assert "--stdin" in task["command"]
    assert "review_notice_token" in str(task.get("when") or "")


def test_a_notice_token_minted_wider_than_declared_reads_as_drift() -> None:
    """The live check separates the two tokens of one account by NAME, not by account.

    `GET /users/{u}/tokens` lists both under the reviewer. The two tokens carry
    different extra scopes, so a check that picks the first token or merges both
    reports a different set than the one minted under the notice token's name.
    """
    from toolkit.features.gitea_tokens import ScopeVerdict, check_token_scopes

    listing = [
        {"id": 1, "name": ROTATABLE_TOKENS["reviewer"].token_name, "scopes": ["write:issue", "read:repository"]},
        {"id": 2, "name": ROTATABLE_TOKENS["review_notice"].token_name, "scopes": ["write:issue", "write:repository"]},
    ]

    result = check_token_scopes("review_notice", "write:issue", listing)

    assert result.verdict is ScopeVerdict.UNDECLARED
    assert result.undeclared == frozenset({"write:repository"})
