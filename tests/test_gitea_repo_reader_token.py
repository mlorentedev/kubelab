"""IDP-053 S5c (AC8) -- the product path reads a product's Gitea repository with a token that can only read it.

`GiteaForge` resolves a commit, proves it merged, and fetches `kubelab.yaml` through
`GiteaClient`, and `ForgeAdapter` documents that the token holds `read:repository` and
nothing else. The reviewer's token (`write:issue,read:repository`) could do the reads, and
must not: the receiver runs in GitHub Actions, a different trust boundary than PR-Agent's,
rotating one would rotate the other, and a leaked copy could comment on and edit issues.

D2 (owner, 2026-11-05): a token of its own on the reviewer's account, one token per
consumer, which is the habit of reviewer, review_notice and issue_reader. So everything the
issue-reader token has is mirrored: a grant read from `common.yaml` and pinned by equality, a
mint gated on the recorded secret being absent, a record over stdin, a catalog entry and a
rotation entry. What differs is the grant (`read:repository`) and the consumer: a GitHub
Actions workflow, so the catalog entry names no `forge_actions` target (that field writes
Gitea Actions secrets, and this token must reach Gitea repositories only, never `mlorentedev/kubelab`).
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

from toolkit.features.gitea_tokens import REPO_READER_SCOPES, REVIEWER_SCOPES, ROTATABLE_TOKENS

REPO = pathlib.Path(__file__).resolve().parent.parent
COMMON = REPO / "infra/config/values/common.yaml"
ROLE = REPO / "infra/ansible/roles/beelink_services"
PLAYBOOK = REPO / "infra/ansible/playbooks/provision-bee.yml"

READER_TOKEN_KEY = "apps.services.core.gitea.repo_reader_token"
MINT_TASK = "Mint the repo-reader token on the reviewer account"
RECORD_TASK = "Record the repo-reader token in SOPS"


def _task(name: str) -> dict[str, Any]:
    for task in yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8")):
        if isinstance(task, dict) and task.get("name") == name:
            return task
    raise AssertionError(f"no task named {name!r} in beelink_services/tasks/main.yml")


def test_the_grant_reads_repositories_and_nothing_else() -> None:
    """EQUALITY, in both directions: a repository reader that can write is the token this one exists to avoid."""
    declared = yaml.safe_load(COMMON.read_text(encoding="utf-8"))["apps"]["services"]["core"]["gitea"]["token_scopes"]
    grant = {s.strip() for s in declared["repo_reader"].split(",") if s.strip()}

    assert grant == {"read:repository"}, (
        f"the repo-reader grant is {sorted(grant)}, the decided scope is read:repository"
    )
    assert grant == set(REPO_READER_SCOPES), "the constant and the declared grant must be one decision"
    assert all(s.startswith("read:") for s in grant), "the reader must not hold any write scope"
    assert "write:issue" in REVIEWER_SCOPES and "write:issue" not in grant, "it must not inherit the reviewer's write"


def test_it_is_rotatable_on_the_reviewer_account_under_its_own_name() -> None:
    reader = ROTATABLE_TOKENS["repo_reader"]
    others = [t for label, t in ROTATABLE_TOKENS.items() if label != "repo_reader"]

    assert reader.identity == ROTATABLE_TOKENS["reviewer"].identity, (
        "D2: the reviewer's account, one token per consumer"
    )
    assert reader.token_name not in {t.token_name for t in others}, "Gitea refuses two tokens of one name on an account"
    assert reader.secret_key == READER_TOKEN_KEY
    assert reader.secret_key not in {t.secret_key for t in others}, "a shared key would make one rotation clear another"
    assert reader.store_env is None, "Gitea is prod's, and the receiver's copy is made from prod's file"


def test_the_token_is_catalogued_and_delivered_nowhere_by_the_forge() -> None:
    from toolkit.features.secrets_manager import SECRET_CATALOG, Expiry, SecretKind

    spec = next((s for s in SECRET_CATALOG if s.key_path == READER_TOKEN_KEY), None)
    assert spec is not None, f"{READER_TOKEN_KEY} is not in SECRET_CATALOG, so no audit can report it absent"
    assert spec.kind is SecretKind.EXTERNAL, "Gitea mints it; a locally generated string would authenticate nothing"
    assert spec.expiry is Expiry.NEVER, "Gitea tokens carry no expiry field; see the bot_token entry"
    assert spec.envs == ("prod",), "a staging entry would make the staging audit demand a key no mint fills"
    assert spec.forge_actions == (), (
        "forge_actions writes Gitea Actions secrets; the receiver runs on GitHub, so the owner sets "
        "GITEA_REPO_READER_TOKEN there by hand, and no Gitea repository may hold a copy"
    )
    assert "pr-agent" not in spec.services and "api" not in spec.services, "no cluster workload consumes it"


def test_the_playbook_reads_the_grant_and_the_secret_from_the_ssot() -> None:
    playbook = PLAYBOOK.read_text(encoding="utf-8")

    assert "token_scopes.repo_reader" in playbook, "the grant must come from common.yaml, not a literal"
    assert "gitea_secrets.apps.services.core.gitea.repo_reader_token" in playbook


def test_it_is_minted_once_with_the_declared_grant_on_the_reviewer_account() -> None:
    task = _task(MINT_TASK)
    assert task.get("no_log") is True
    assert task.get("when") == "gitea_reviewer_user | length > 0 and not gitea_repo_reader_token", (
        "an ungated mint issues a new live token every run; an inverted one mints nothing"
    )
    command = " ".join(task["command"]["argv"])
    assert "--username {{ gitea_reviewer_user }}" in command
    assert f"--token-name {ROTATABLE_TOKENS['repo_reader'].token_name}" in command
    assert "--scopes {{ gitea_repo_reader_scopes }}" in command


def test_it_is_recorded_over_stdin_under_its_own_key() -> None:
    task = _task(RECORD_TASK)
    assert task.get("no_log") is True
    assert f"toolkit secrets set {READER_TOKEN_KEY}" in task["command"]
    assert "--stdin" in task["command"]
    assert task.get("when") == "gitea_reviewer_user | length > 0 and not gitea_repo_reader_token", (
        "the record must run exactly when the mint ran"
    )


def test_a_stale_unrecorded_token_is_revoked_so_the_mint_can_reuse_the_name() -> None:
    """Without this entry a half-failed run leaves a live token under the name the mint needs."""
    stale = next(
        t
        for t in yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8"))
        if isinstance(t, dict) and t.get("name") == "Revoke a named token that Gitea holds and SOPS does not"
    )
    named = {item["name"]: item["recorded"] for item in stale["loop"]}

    assert named.get(ROTATABLE_TOKENS["repo_reader"].token_name) == "{{ gitea_repo_reader_token | length > 0 }}"


def test_the_controller_check_covers_the_new_record_task() -> None:
    """The mint must not run on a controller that cannot write the result down (#2902)."""
    check = _task("Assert the controller can record a minted token")
    assert "not gitea_repo_reader_token" in str(check["when"]), "the check must fire when the reader is unrecorded"


def test_a_reader_minted_wider_than_declared_reads_as_drift() -> None:
    """The live check separates the tokens of one account by NAME, so a reader that gained a write scope shows."""
    from toolkit.features.gitea_tokens import ScopeVerdict, check_token_scopes

    listing = [
        {"id": 1, "name": ROTATABLE_TOKENS["reviewer"].token_name, "scopes": ["write:issue", "read:repository"]},
        {
            "id": 3,
            "name": ROTATABLE_TOKENS["repo_reader"].token_name,
            "scopes": ["read:repository", "write:repository"],
        },
    ]

    result = check_token_scopes("repo_reader", "read:repository", listing)

    assert result.verdict is ScopeVerdict.UNDECLARED
    assert result.undeclared == frozenset({"write:repository"})
