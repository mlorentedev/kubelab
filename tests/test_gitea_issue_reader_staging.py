"""#3267: staging reads Gitea with a token of its own, through a Service with no route.

Staging declares the same Gitea sources as prod, and until this change it had no reader, so a
Gitea read was first exercised in prod (#3246 shipped that way). The reader is a second token on
the reviewer's account, `kubelab-issue-reader-staging`, recorded in staging's SOPS under the same
key the API's Secret maps, so `apply-secrets ENV=staging` delivers it with no new mapping. Prod's
token is not copied: two copies of one credential drift apart on the first rotation.

The token is minted by the Gitea on the Beelink, which is prod's (`gitea_identity_env`), and
stored in staging's file. So the registry records which file holds it (`store_env`), and the
rotation reaches Gitea through prod and clears the key in staging.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from toolkit.features.gitea_tokens import ROTATABLE_TOKENS, format_rotation_plan, plan_rotation, rotation_store_env

REPO = Path(__file__).resolve().parents[1]
TASKS = REPO / "infra/ansible/roles/beelink_services/tasks/main.yml"
PLAYBOOK = REPO / "infra/ansible/playbooks/provision-bee.yml"
VALUES = REPO / "infra/config/values"
STAGING_GITEA = REPO / "infra/k8s/overlays/staging/gitea.yaml"
STAGING_KUSTOMIZATION = REPO / "infra/k8s/overlays/staging/kustomization.yaml"
READER_KEY = "apps.services.core.gitea.issue_reader_token"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class TestRegistry:
    def test_staging_has_its_own_token_on_the_reviewer_account(self) -> None:
        staging = ROTATABLE_TOKENS["issue_reader_staging"]
        prod = ROTATABLE_TOKENS["issue_reader"]

        assert staging.token_name == "kubelab-issue-reader-staging"
        assert staging.token_name != prod.token_name, "Gitea refuses two tokens of one name on an account"
        assert staging.identity == prod.identity == "reviewer"
        assert staging.secret_key == prod.secret_key == READER_KEY, "the API's Secret maps one key per env"

    def test_it_holds_the_same_read_only_grant_as_prod(self) -> None:
        scopes = _load(VALUES / "common.yaml")["apps"]["services"]["core"]["gitea"]["token_scopes"]

        assert scopes["issue_reader_staging"] == scopes["issue_reader"] == "read:issue"

    def test_each_token_is_cleared_in_the_file_that_holds_it(self) -> None:
        assert rotation_store_env("issue_reader_staging", "prod") == "staging"
        assert rotation_store_env("issue_reader", "prod") == "prod"
        assert rotation_store_env("bot", "prod") == "prod"

    def test_the_plan_names_the_file_it_would_clear(self) -> None:
        plan = plan_rotation("issue_reader_staging", {"reviewer": "argos"}, secret_present=True, store_env="staging")

        assert plan.store_env == "staging"
        assert "staging" in format_rotation_plan(plan)


class TestMint:
    def test_the_playbook_reads_the_gate_from_staging_sops(self) -> None:
        playbook = PLAYBOOK.read_text(encoding="utf-8")

        assert "config/secrets/staging.enc.yaml" in playbook, "the gate must read the file the token is stored in"
        assert re.search(r"gitea_issue_reader_staging_token:.*issue_reader_token", playbook)

    def test_the_mint_is_gated_and_recorded_in_staging(self) -> None:
        tasks = TASKS.read_text(encoding="utf-8")

        assert "--token-name kubelab-issue-reader-staging" in tasks
        record = re.search(rf"toolkit secrets set {re.escape(READER_KEY)} --env staging --stdin", tasks)
        assert record, "the staging token must be written to staging's SOPS, not prod's"
        mint = tasks[tasks.index("--token-name kubelab-issue-reader-staging") :]
        assert "not gitea_issue_reader_staging_token" in mint.split("- name:")[1], "an ungated mint issues a new token every run"

    def test_the_revoke_recovery_covers_it(self) -> None:
        tasks = TASKS.read_text(encoding="utf-8")

        assert re.search(r"name: kubelab-issue-reader-staging, user: \"\{\{ gitea_reviewer_user \}\}\"", tasks)


class TestReachingGitea:
    def test_staging_reads_the_in_cluster_service_like_prod(self) -> None:
        staging = _load(VALUES / "staging.yaml")["infra"]["forge"]
        prod = _load(VALUES / "prod.yaml")["infra"]["forge"]

        assert staging["gitea_url"] == prod["gitea_url"] == "http://gitea:3000"

    def test_the_service_points_at_the_beelink_tailnet_address_and_has_no_route(self) -> None:
        tailnet_ip = _load(VALUES / "common.yaml")["networking"]["nodes"]["beelink"]["tailscale_ip"]
        docs = [d for d in yaml.safe_load_all(STAGING_GITEA.read_text(encoding="utf-8")) if d]
        kinds = {d["kind"] for d in docs}

        assert kinds == {"Service", "EndpointSlice"}, "a reader, not a second public door to the singleton"
        endpoint = next(d for d in docs if d["kind"] == "EndpointSlice")
        assert endpoint["endpoints"][0]["addresses"] == [tailnet_ip], "Gitea binds the tailnet address only"
        assert "gitea.yaml" in _load(STAGING_KUSTOMIZATION)["resources"]

    def test_the_catalog_requires_it_in_staging(self) -> None:
        from toolkit.features.secrets_manager import SECRET_CATALOG

        spec = next(s for s in SECRET_CATALOG if s.key_path == READER_KEY)
        assert set(spec.envs) == {"prod", "staging"}
