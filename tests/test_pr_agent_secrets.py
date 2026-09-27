"""TOOL-080 PR 4, AC6: the server's three SOPS keys are catalogued and mapped.

`webhook_secret` and `reviewer_token` were catalogued in PR 3/PR 2; this adds
`nan_api_key` and the K8s Secret that carries all three into the pod. All three
are REQUIRED (`SecretMapping.keys`, never `optional_keys`): unlike n8n's
Slack/Vikunja keys, a pod missing any one of these cannot review anything —
no model key, no signature check, no forge read.

The mapping is derived from the catalog rather than restating env var names, so
a renamed `key_path` breaks this test instead of silently drifting from the
K8s Secret it is supposed to describe.
"""

from __future__ import annotations

from toolkit.features import k8s_secrets as ks
from toolkit.features.k8s_secrets import SECRET_DEFINITIONS, SecretMapping
from toolkit.features.secrets_manager import SECRET_CATALOG, Expiry, SecretKind

PR_AGENT_MAPPING = next(m for m in SECRET_DEFINITIONS if m.name == "pr-agent-secrets")


def _catalog(key_path: str):
    spec = next((s for s in SECRET_CATALOG if s.key_path == key_path), None)
    assert spec is not None, f"{key_path} must be registered in SECRET_CATALOG"
    return spec


def _flattened_env_var(key_path: str) -> str:
    """Mirror `ConfigurationManager._flatten_dict`: dotted path -> UPPER_SNAKE."""
    return key_path.upper().replace(".", "_")


class TestNanApiKeyCatalogEntry:
    def test_is_registered_external_prod_only(self) -> None:
        spec = _catalog("apps.services.automation.pr_agent.nan_api_key")
        assert spec.kind == SecretKind.EXTERNAL
        assert spec.envs == ("prod",)
        assert spec.expiry == Expiry.NEVER

    def test_rotate_note_names_the_exact_recopy_one_liner(self) -> None:
        spec = _catalog("apps.services.automation.pr_agent.nan_api_key")
        one_liner = (
            'dotf secrets run --only NAN_API_KEY -- sh -c \'printf %s "$NAN_API_KEY" | '
            "toolkit secrets set apps.services.automation.pr_agent.nan_api_key --env prod --stdin'"
        )
        assert one_liner in spec.rotate_note


class TestPrAgentSecretMapping:
    def test_all_three_keys_are_required_not_optional(self) -> None:
        assert set(PR_AGENT_MAPPING.keys) == {
            "OPENAI__KEY",
            "GITEA__WEBHOOK_SECRET",
            "GITEA__PERSONAL_ACCESS_TOKEN",
        }
        assert PR_AGENT_MAPPING.optional_keys == {}, "AC6: no key here may be optional"

    def test_each_key_maps_to_its_catalog_entry_s_flattened_path(self) -> None:
        expected = {
            "OPENAI__KEY": "apps.services.automation.pr_agent.nan_api_key",
            "GITEA__WEBHOOK_SECRET": "apps.services.automation.pr_agent.webhook_secret",
            "GITEA__PERSONAL_ACCESS_TOKEN": "apps.services.core.gitea.reviewer_token",
        }
        for k8s_key, catalog_path in expected.items():
            _catalog(catalog_path)  # each source key is itself catalogued
            assert PR_AGENT_MAPPING.keys[k8s_key] == _flattened_env_var(catalog_path)

    def test_scoped_to_prod_like_every_source_key(self) -> None:
        assert PR_AGENT_MAPPING.envs == ("prod",)


class TestApplySecretsRefusesAPartialRender:
    """AC6's other half: `apply-secrets` fails closed when any key is missing."""

    def test_a_missing_required_key_refuses_without_calling_kubectl(self, mocker) -> None:
        run = mocker.patch("toolkit.features.k8s_secrets.subprocess.run")
        env_vars = {
            "APPS_SERVICES_AUTOMATION_PR_AGENT_NAN_API_KEY": "x",
            "APPS_SERVICES_AUTOMATION_PR_AGENT_WEBHOOK_SECRET": "y",
            # GITEA__PERSONAL_ACCESS_TOKEN's source is absent.
        }

        ok = ks._apply_single_secret(PR_AGENT_MAPPING, env_vars, {}, dry_run=False, env="prod")

        assert ok is False
        run.assert_not_called()


class TestApplySecretsEnvScoping:
    """The gap a prod-only mapping opens: `apply-secrets ENV=staging` must not

    even attempt a mapping whose source keys are catalogued for prod only —
    that is absence, not a broken deploy.
    """

    def test_a_prod_only_mapping_is_excluded_from_staging(self) -> None:
        scoped = SecretMapping(name="pr-agent-secrets", keys={"A": "X"}, envs=("prod",))
        unscoped = SecretMapping(name="api-secrets", keys={"B": "Y"})

        assert ks._definitions_for_env("staging", [scoped, unscoped]) == [unscoped]
        assert ks._definitions_for_env("prod", [scoped, unscoped]) == [scoped, unscoped]

    def test_apply_secrets_never_attempts_a_prod_only_mapping_under_staging(self, monkeypatch) -> None:
        class CM:
            def get_env_vars(self):
                # A real staging vault: the pr-agent keys never exist here.
                return {"X": "1"}

        monkeypatch.setattr(ks, "ConfigurationManager", lambda *a, **k: CM())
        # The identity guard (3b) is orthogonal to what this test measures —
        # satisfy it so only the env-scoping behaviour is under test.
        monkeypatch.setattr(ks, "_build_dynamic_literals", lambda cm: {"grafana-admin": {"admin-user": "op"}})
        monkeypatch.setattr(
            ks,
            "SECRET_DEFINITIONS",
            [SecretMapping(name="pr-agent-secrets", keys={"OPENAI__KEY": "MISSING"}, envs=("prod",))],
        )
        monkeypatch.setattr(ks, "delete_retired_secrets", lambda env, dry_run: True)
        monkeypatch.setattr(ks, "restart_consumers", lambda changed, **k: True)
        attempted: list[str] = []
        monkeypatch.setattr(ks, "_apply_single_secret", lambda mapping, *a, **k: attempted.append(mapping.name) or True)

        ok = ks.apply_secrets("staging", None, dry_run=False)

        assert ok is True, "a prod-only mapping must not fail a staging apply"
        assert attempted == [], "and must never even be attempted there"

    def test_apply_secrets_still_attempts_it_under_prod(self, monkeypatch) -> None:
        class CM:
            def get_env_vars(self):
                return {"MISSING": "value"}

        monkeypatch.setattr(ks, "ConfigurationManager", lambda *a, **k: CM())
        monkeypatch.setattr(ks, "_build_dynamic_literals", lambda cm: {"grafana-admin": {"admin-user": "op"}})
        monkeypatch.setattr(
            ks,
            "SECRET_DEFINITIONS",
            [SecretMapping(name="pr-agent-secrets", keys={"OPENAI__KEY": "MISSING"}, envs=("prod",))],
        )
        monkeypatch.setattr(ks, "delete_retired_secrets", lambda env, dry_run: True)
        monkeypatch.setattr(ks, "restart_consumers", lambda changed, **k: True)
        attempted: list[str] = []
        monkeypatch.setattr(ks, "_apply_single_secret", lambda mapping, *a, **k: attempted.append(mapping.name) or True)

        ok = ks.apply_secrets("prod", None, dry_run=False)

        assert ok is True
        assert attempted == ["pr-agent-secrets"]
