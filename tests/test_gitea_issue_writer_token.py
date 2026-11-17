"""CONSOLE-004 AC2 (#2570) -- the forge task view writes Gitea issues with a token of its own, in prod only.

ADR-066's amendments of 2026-11-13 and 2026-11-17 decide it: `issue_writer` (`write:issue`) is minted
on the MACHINE account (not the reviewer's, which is the read side and must stay unable to write),
recorded at `apps.services.core.gitea.issue_writer_token` in prod's SOPS, and delivered to the API
through `api-secrets` as `FORGE_GITEA_WRITE_TOKEN`. Staging has no forge writer at all, so the
suite also pins what that means mechanically: no catalog entry for staging, no key in either SOPS
file the staging API merges, no placeholder in staging's overlay, no ConfigMap key anywhere.

What mirrors the issue reader: a grant read from `common.yaml` and pinned by equality, a mint gated
on the recorded secret being absent, a record over stdin, a catalog entry and a rotation entry. What
differs: the account (machine), the grant (a write scope) and the env (prod only).
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

from toolkit.features.gitea_tokens import ISSUE_WRITER_SCOPES, ROTATABLE_TOKENS, plan_rotation, rotation_store_env
from toolkit.features.k8s_secrets import SECRET_DEFINITIONS
from toolkit.features.secrets_manager import SECRET_CATALOG, Expiry, SecretKind

REPO = pathlib.Path(__file__).resolve().parent.parent
COMMON = REPO / "infra/config/values/common.yaml"
ROLE = REPO / "infra/ansible/roles/beelink_services"
PLAYBOOK = REPO / "infra/ansible/playbooks/provision-bee.yml"
SECRETS = REPO / "infra/config/secrets"
OVERLAYS = REPO / "infra/k8s/overlays"

WRITER_KEY = "apps.services.core.gitea.issue_writer_token"
ENV_VAR = "FORGE_GITEA_WRITE_TOKEN"
MINT_TASK = "Mint the issue-writer token on the machine account"
RECORD_TASK = "Record the issue-writer token in SOPS"

API_SECRETS = next(m for m in SECRET_DEFINITIONS if m.name == "api-secrets")


def _task(name: str) -> dict[str, Any]:
    for task in yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8")):
        if isinstance(task, dict) and task.get("name") == name:
            return task
    raise AssertionError(f"no task named {name!r} in beelink_services/tasks/main.yml")


def _declared_scopes() -> dict[str, str]:
    return yaml.safe_load(COMMON.read_text(encoding="utf-8"))["apps"]["services"]["core"]["gitea"]["token_scopes"]


def _flattened(key_path: str) -> str:
    return key_path.upper().replace(".", "_")


def _key_names(node: Any, prefix: str = "") -> set[str]:
    """Every dotted key path in a SOPS file. Key names are plaintext, so this needs no decryption."""
    paths: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.add(path)
            paths |= _key_names(value, path)
    return paths


class TestTheGrant:
    def test_it_writes_issues_and_nothing_else(self) -> None:
        """EQUALITY in both directions: a writer that also reads code or writes repositories is a wider token than decided."""
        grant = {s.strip() for s in _declared_scopes()["issue_writer"].split(",") if s.strip()}

        assert grant == {"write:issue"}, f"the issue-writer grant is {sorted(grant)}, the decided scope is write:issue"
        assert grant == set(ISSUE_WRITER_SCOPES), "the constant and the declared grant must be one decision"

    def test_it_is_not_the_readers_token(self) -> None:
        declared = _declared_scopes()
        assert declared["issue_writer"] != declared["issue_reader"], "A2: read and write are separate credentials"


class TestRotation:
    def test_it_is_a_token_on_the_machine_account_under_its_own_name(self) -> None:
        writer = ROTATABLE_TOKENS["issue_writer"]
        others = [t for label, t in ROTATABLE_TOKENS.items() if label != "issue_writer"]

        assert writer.identity == "machine", "the counterpart of the GitHub App's bot, ADR-066 2026-11-13"
        assert writer.identity != ROTATABLE_TOKENS["issue_reader"].identity, "the reader's account must stay read-only"
        assert writer.token_name not in {t.token_name for t in others}, "Gitea refuses two tokens of one name"
        assert writer.secret_key == WRITER_KEY
        assert writer.secret_key not in {t.secret_key for t in others}, "a shared key would make one rotation clear another"
        assert writer.store_env is None, "Gitea is prod's, and the token is recorded in prod's file"


    def test_a_rotation_plan_names_the_machine_login_and_prods_file(self) -> None:
        """`make gitea-rotate-token TOKEN=issue_writer ENV=prod` resolves through exactly these two calls."""
        identities = {"machine": "hefesto", "reviewer": "mentor"}

        store_env = rotation_store_env("issue_writer", "prod")
        plan = plan_rotation("issue_writer", identities, secret_present=True, store_env=store_env)

        assert plan.username == "hefesto", "the machine account, not the reviewer's"
        assert plan.token_name == "kubelab-issue-writer"
        assert plan.secret_key == WRITER_KEY
        assert plan.store_env == "prod"


class TestCatalog:
    def test_it_is_catalogued_for_prod_only_with_the_api_as_its_consumer(self) -> None:
        spec = next((s for s in SECRET_CATALOG if s.key_path == WRITER_KEY), None)

        assert spec is not None, f"{WRITER_KEY} is not in SECRET_CATALOG, so no audit can report it absent"
        assert spec.kind is SecretKind.EXTERNAL, "Gitea mints it; a locally generated string would authenticate nothing"
        assert spec.expiry is Expiry.NEVER, "Gitea tokens carry no expiry field; see the bot_token entry"
        assert spec.envs == ("prod",), "a staging entry would make the staging audit demand a key no mint fills"
        assert "api" in spec.services and "gitea" in spec.services
        assert "pr-agent" not in spec.services, "the reviewer pod must not consume the writer token"
        assert "gitea-rotate-token TOKEN=issue_writer" in spec.rotate_note


class TestMint:
    def test_it_is_minted_once_with_the_declared_grant_on_the_machine_account(self) -> None:
        task = _task(MINT_TASK)

        assert task.get("no_log") is True
        assert task.get("when") == "not gitea_issue_writer_token", (
            "an ungated mint issues a new live token every run; an inverted one mints nothing"
        )
        command = " ".join(task["command"]["argv"])
        assert "--username {{ gitea_bot_user }}" in command, "the machine account, never the reviewer's"
        assert "gitea_reviewer_user" not in command
        assert f"--token-name {ROTATABLE_TOKENS['issue_writer'].token_name}" in command
        assert "--scopes {{ gitea_issue_writer_scopes }}" in command

    def test_it_is_recorded_in_prods_file_over_stdin(self) -> None:
        task = _task(RECORD_TASK)

        assert task.get("no_log") is True
        assert f"toolkit secrets set {WRITER_KEY} --env {{{{ gitea_identity_env }}}} --stdin" in task["command"]
        assert task.get("when") == "not gitea_issue_writer_token"

    def test_the_playbook_reads_the_grant_and_the_secret_from_the_ssot(self) -> None:
        playbook = PLAYBOOK.read_text(encoding="utf-8")

        assert "token_scopes.issue_writer" in playbook, "the grant must come from common.yaml, not a literal"
        assert f"gitea_secrets.{WRITER_KEY}" in playbook, "the mint gate reads prod's store, where the record writes"

    def test_the_controller_check_and_the_revoke_recovery_cover_it(self) -> None:
        """A token the mint knows and the recovery does not is the #2902 trap: minted, unrecorded, never converging."""
        text = (ROLE / "tasks/main.yml").read_text(encoding="utf-8")

        assert 'name: kubelab-issue-writer, user: "{{ gitea_bot_user }}"' in text
        assert "not gitea_issue_writer_token" in _task("Assert the controller can record a minted token")["when"]


class TestDelivery:
    def test_the_api_receives_it_as_an_optional_key_mapped_from_the_catalog_entry(self) -> None:
        assert API_SECRETS.optional_keys[ENV_VAR] == _flattened(WRITER_KEY)
        assert ENV_VAR not in API_SECRETS.keys, "required would fail apply-secrets before the Beelink has minted it"

    def test_prods_overlay_has_a_placeholder_for_it(self) -> None:
        docs = yaml.safe_load_all((OVERLAYS / "prod/secrets.yaml").read_text(encoding="utf-8"))
        api = next(d for d in docs if d and d["metadata"]["name"] == "api-secrets")
        assert ENV_VAR in api["stringData"]


class TestStagingHasNoForgeWriter:
    """ADR-066 2026-11-17: nothing the staging API could read may carry a Gitea write credential."""

    def test_the_staging_overlay_has_no_placeholder_for_it(self) -> None:
        docs = yaml.safe_load_all((OVERLAYS / "staging/secrets.yaml").read_text(encoding="utf-8"))
        api = next(d for d in docs if d and d["metadata"]["name"] == "api-secrets")
        assert ENV_VAR not in api["stringData"]

    def test_neither_sops_file_the_staging_api_merges_holds_the_key(self) -> None:
        """`_secret_data` delivers an optional key whenever the env's merged SOPS holds it, and staging merges common."""
        for name in ("staging", "common"):
            paths = _key_names(yaml.safe_load((SECRETS / f"{name}.enc.yaml").read_text(encoding="utf-8")))
            # A walker that sees nothing would pass this test forever, so staging's file must show its reader.
            assert name != "staging" or "apps.services.core.gitea.issue_reader_token" in paths, "the key walker is blind"
            assert WRITER_KEY not in paths, f"{name}.enc.yaml holds {WRITER_KEY}: staging would deliver a forge writer"

    def test_no_configmap_carries_it(self) -> None:
        for env in ("staging", "prod"):
            path = OVERLAYS / env / "generated/configmaps.yaml"
            for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
                names = set((doc or {}).get("data") or {})
                assert ENV_VAR not in names and _flattened(WRITER_KEY) not in names, f"{env}: a ConfigMap holds the token"
