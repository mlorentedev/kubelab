"""Tests for k8s_secrets._apply_single_secret — fail-closed on partial mappings (TOOL-018).

A K8s Secret manifest is rendered in-process and applied via `kubectl apply -f -`
(stdin) — one subprocess call, no secret in argv (SEC-SECRETS-001). `apply` REPLACES
the entire Secret. If only a subset of a mapping's source values resolve (e.g. an
env-specific SOPS key not yet synced), applying that subset would shrink the live
Secret and silently drop the missing keys on the next pod restart.

The contract these tests pin (audit finding C2): a partial mapping must fail closed —
return False WITHOUT ever calling kubectl — so the live Secret is never shrunk and
`apply_secrets` reports the failure.
"""

from __future__ import annotations

import pytest

from toolkit.features.k8s_secrets import SecretMapping, _apply_single_secret


class TestApplySingleSecretFailsClosed:
    def test_partial_mapping_fails_closed_without_calling_kubectl(self, mocker: "pytest.MonkeyPatch") -> None:
        run = mocker.patch("toolkit.features.k8s_secrets.subprocess.run")
        mapping = SecretMapping(name="api-secrets", keys={"A": "ENV_A", "B": "ENV_B"})
        # ENV_B is missing → only 1 of 2 keys resolves.
        env_vars = {"ENV_A": "value-a"}

        ok = _apply_single_secret(mapping, env_vars, {}, dry_run=False, env="staging")

        assert ok is False, "a partial mapping must fail, not apply a shrunken Secret"
        run.assert_not_called()  # must never reach kubectl create/apply

    def test_all_missing_fails_closed_without_calling_kubectl(self, mocker: "pytest.MonkeyPatch") -> None:
        run = mocker.patch("toolkit.features.k8s_secrets.subprocess.run")
        mapping = SecretMapping(name="api-secrets", keys={"A": "ENV_A", "B": "ENV_B"})

        ok = _apply_single_secret(mapping, {}, {}, dry_run=False, env="staging")

        assert ok is False
        run.assert_not_called()

    def test_fully_resolved_mapping_applies(self, mocker: "pytest.MonkeyPatch") -> None:
        run = mocker.patch("toolkit.features.k8s_secrets.subprocess.run")
        run.return_value = mocker.Mock(stdout="secret/api-secrets configured", returncode=0)
        mapping = SecretMapping(name="api-secrets", keys={"A": "ENV_A", "B": "ENV_B"})
        env_vars = {"ENV_A": "value-a", "ENV_B": "value-b"}

        ok = _apply_single_secret(mapping, env_vars, {}, dry_run=False, env="staging")

        assert ok is True
        assert run.call_count == 1  # single `apply -f -` via stdin (no `create` subprocess)

    def test_dynamic_only_secret_with_extra_literals_applies(self, mocker: "pytest.MonkeyPatch") -> None:
        # authelia-users / apprise-secrets style: keys={} and the value comes from a builder.
        run = mocker.patch("toolkit.features.k8s_secrets.subprocess.run")
        run.return_value = mocker.Mock(stdout="secret/authelia-users configured", returncode=0)
        mapping = SecretMapping(name="authelia-users", keys={})

        ok = _apply_single_secret(mapping, {}, {"users_database.yml": "users: {}"}, dry_run=False, env="staging")

        assert ok is True
        assert run.call_count == 1
