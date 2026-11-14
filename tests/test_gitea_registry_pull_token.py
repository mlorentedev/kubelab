"""IDP-053 S2c (AC4) -- a private product's image is pulled with a token that can only read packages.

The cluster pulls a private product's image from the forge's container registry with a
`kubernetes.io/dockerconfigjson` Secret rendered from a token. The reviewer's token must not be
that credential: it can comment on issues, rotating one would rotate the other, and the
cluster's pull Secret lives behind a different trust boundary than PR-Agent's.

D2 (owner, 2026-11-05): a token of its own on the reviewer's account, one token per consumer, as
reviewer, review_notice and issue_reader already are. So everything the issue-reader token has
is mirrored: a grant read from `common.yaml` and pinned by equality, a mint gated on the
recorded secret being absent, a record over stdin, a catalog entry and a rotation entry.

What differs is where the value lives. Both clusters pull with it, so it is stored in
`common.enc.yaml` (like `ghcr.pull_token`) and audited under staging and prod, and it is
rotated through prod's Gitea, the one that minted it. The catalog entry names no
`forge_actions`: that field writes Gitea Actions secrets, and this credential is read by the
cluster, never by CI.
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

from toolkit.features import product_registry
from toolkit.features.gitea_tokens import REGISTRY_PULL_SCOPES, ROTATABLE_TOKENS, rotation_store_env

REPO = pathlib.Path(__file__).resolve().parent.parent
COMMON = REPO / "infra/config/values/common.yaml"
ROLE = REPO / "infra/ansible/roles/beelink_services"
PLAYBOOK = REPO / "infra/ansible/playbooks/provision-bee.yml"

PULL_TOKEN_KEY = "apps.services.core.gitea.registry_pull_token"
MINT_TASK = "Mint the registry-pull token on the reviewer account"
RECORD_TASK = "Record the registry-pull token in SOPS"


def _tasks() -> list[Any]:
    return yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8"))


def _task(name: str) -> dict[str, Any]:
    for task in _tasks():
        if isinstance(task, dict) and task.get("name") == name:
            return task
    raise AssertionError(f"no task named {name!r} in beelink_services/tasks/main.yml")


def test_the_grant_reads_packages_and_nothing_else() -> None:
    """EQUALITY, in both directions: a pull credential that can write is the token this one exists to avoid."""
    declared = yaml.safe_load(COMMON.read_text(encoding="utf-8"))["apps"]["services"]["core"]["gitea"]["token_scopes"]
    grant = {s.strip() for s in declared["registry_pull"].split(",") if s.strip()}

    assert grant == {"read:package"}, f"the registry-pull grant is {sorted(grant)}, the decided scope is read:package"
    assert grant == set(REGISTRY_PULL_SCOPES), "the constant and the declared grant must be one decision"
    assert all(s.startswith("read:") for s in grant), "a pull credential must not hold any write scope"


def test_it_is_rotatable_on_the_reviewer_account_under_its_own_name() -> None:
    pull = ROTATABLE_TOKENS["registry_pull"]
    others = [t for label, t in ROTATABLE_TOKENS.items() if label != "registry_pull"]

    assert pull.identity == ROTATABLE_TOKENS["reviewer"].identity, "D2: the reviewer's account, one token per consumer"
    assert pull.token_name not in {t.token_name for t in others}, "Gitea refuses two tokens of one name on an account"
    assert pull.secret_key == PULL_TOKEN_KEY
    assert pull.secret_key not in {t.secret_key for t in others}, "a shared key would make one rotation clear another"


def test_it_is_stored_in_common_and_rotated_through_prod() -> None:
    """Both clusters read it, so it lives in common.enc.yaml; Gitea is prod's, so prod rotates it."""
    assert ROTATABLE_TOKENS["registry_pull"].store_env == "common"
    assert rotation_store_env("registry_pull", "prod") == "common"
    try:
        rotation_store_env("registry_pull", "common")
    except ValueError:
        pass
    else:  # pragma: no cover - the assertion is the failure
        raise AssertionError("common names no Gitea: a revoke sent there could clear the key and revoke nothing")


def test_the_token_is_catalogued_audited_under_both_clusters_and_delivered_nowhere_by_the_forge() -> None:
    from toolkit.features.secrets_manager import SECRET_CATALOG, Expiry, SecretKind

    spec = next((s for s in SECRET_CATALOG if s.key_path == PULL_TOKEN_KEY), None)
    assert spec is not None, f"{PULL_TOKEN_KEY} is not in SECRET_CATALOG, so no audit can report it absent"
    assert spec.kind is SecretKind.EXTERNAL, "Gitea mints it; a locally generated string would authenticate nothing"
    assert spec.expiry is Expiry.NEVER, "Gitea tokens carry no expiry field; see the bot_token entry"
    assert set(spec.envs) == {"staging", "prod"}, (
        "both clusters pull with it; `envs` is the audit dimension, not the file"
    )
    assert spec.forge_actions == (), "forge_actions writes Gitea Actions secrets; the cluster reads this, CI never does"


def test_a_product_can_name_it_as_its_pull_credential(tmp_path: pathlib.Path) -> None:
    """The catalog key is what `pull_credential.secret` names, and apply-secrets reads it as the flattened variable."""
    from toolkit.features.k8s_secrets import pull_secret_mappings

    path = tmp_path / "products.yaml"
    path.write_text(
        "products:\n  api:\n    forge: in-tree\n  beta:\n    repository: personal/beta\n    forge: gitea\n"
        "    receiver: generic\n    image_registry: gitea.kubelab.live/personal\n    private: true\n"
        f"    pull_credential: {{username: reviewer, secret: {PULL_TOKEN_KEY}}}\n",
        encoding="utf-8",
        newline="\n",
    )

    (mapping,) = pull_secret_mappings(product_registry.load_registry(path))

    assert list(mapping.keys.values()) == ["APPS_SERVICES_CORE_GITEA_REGISTRY_PULL_TOKEN"]
    assert mapping.envs == ("staging", "prod")


def test_the_variable_the_token_is_recorded_under_is_common() -> None:
    """Both clusters read it from common.enc.yaml (like `ghcr.pull_token`); a prod default would hide it from staging."""
    declared = {
        play["vars"]["gitea_registry_pull_env"]
        for play in yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
        if "gitea_registry_pull_env" in (play.get("vars") or {})
    }

    assert declared == {"common"}


def test_the_playbook_reads_the_grant_and_the_secret_from_the_ssot() -> None:
    playbook = PLAYBOOK.read_text(encoding="utf-8")

    assert "token_scopes.registry_pull" in playbook, "the grant must come from common.yaml, not a literal"
    assert "gitea_registry_pull_secrets.apps.services.core.gitea.registry_pull_token" in playbook, (
        "the gate must read the store the record task writes to (common's file), not `gitea_secrets`"
    )


def test_it_is_minted_once_with_the_declared_grant_on_the_reviewer_account() -> None:
    task = _task(MINT_TASK)
    assert task.get("no_log") is True
    assert "registry_pull_token" in str(task.get("when") or ""), "an ungated mint issues a new live token every run"
    command = " ".join(task["command"]["argv"])
    assert "--username {{ gitea_reviewer_user }}" in command
    assert f"--token-name {ROTATABLE_TOKENS['registry_pull'].token_name}" in command
    assert "--scopes {{ gitea_registry_pull_scopes }}" in command


def test_it_is_recorded_over_stdin_in_commons_file_under_its_own_key() -> None:
    task = _task(RECORD_TASK)
    assert task.get("no_log") is True
    assert f"toolkit secrets set {PULL_TOKEN_KEY} --env {{{{ gitea_registry_pull_env }}}}" in task["command"], (
        "the env is the play variable the gate's store is built from, so write and read cannot drift apart"
    )
    assert "--stdin" in task["command"]
    assert "registry_pull_token" in str(task.get("when") or "")


def test_a_stale_unrecorded_token_is_revoked_so_the_mint_can_reuse_the_name() -> None:
    """Without this entry a half-failed run leaves a live token under the name the mint needs."""
    stale = next(
        t
        for t in _tasks()
        if isinstance(t, dict) and t.get("name") == "Revoke a named token that Gitea holds and SOPS does not"
    )
    named = {item["name"]: item["recorded"] for item in stale["loop"]}

    assert named.get(ROTATABLE_TOKENS["registry_pull"].token_name) == "{{ gitea_registry_pull_token | length > 0 }}"


def test_the_controller_check_covers_the_new_record_task() -> None:
    """The mint must not run on a controller that cannot write the result down (#2902)."""
    check = _task("Assert the controller can record a minted token")
    assert "gitea_registry_pull_token" in str(check["when"])


def test_a_pull_token_minted_wider_than_declared_reads_as_drift() -> None:
    """The live check separates the tokens of one account by NAME, so a pull token that gained a write scope shows."""
    from toolkit.features.gitea_tokens import ScopeVerdict, check_token_scopes

    listing = [
        {"id": 1, "name": ROTATABLE_TOKENS["reviewer"].token_name, "scopes": ["write:issue", "read:repository"]},
        {"id": 3, "name": ROTATABLE_TOKENS["registry_pull"].token_name, "scopes": ["read:package", "write:package"]},
    ]

    result = check_token_scopes("registry_pull", "read:package", listing)

    assert result.verdict is ScopeVerdict.UNDECLARED
    assert result.undeclared == frozenset({"write:package"})
