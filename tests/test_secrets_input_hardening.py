"""Tests for TOOL-008: secrets CLI input hardening.

Covers two fixes to the toolkit secrets subsystem:

1. `secrets set --stdin` reads the value from stdin (so values starting with `-`,
   e.g. Telegram chat IDs, work and secrets stay out of argv). The positional
   VALUE is kept for back-compat; passing both is an error.
2. `secrets init` is idempotent: it skips secrets that already exist, `--force`
   regenerates all machine-generable secrets, and `--rotate KEY` targets specific
   keys only.

Mocking strategy:
  - CLI tests use Typer's CliRunner with `input=` to feed stdin and patch
    `_get_manager`, so no SOPS file is touched.
  - init tests call `init_machine_secrets(..., dry_run=True)` (no write) and patch
    `audit` / `_generate_secret`, asserting only on the returned dict.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from toolkit.features.secrets_manager import (
    SECRET_CATALOG,
    AuditResult,
    SecretKind,
    SecretsManager,
)
from toolkit.main import app

runner = CliRunner()

AUTO_KINDS = {
    SecretKind.RANDOM_HEX,
    SecretKind.RANDOM_TOKEN,
    SecretKind.OIDC_CLIENT_SECRET,
    SecretKind.RSA_KEY,
}


def _machine_keys(env: str) -> list[str]:
    """Machine-generable secret key paths registered for an env."""
    return [s.key_path for s in SECRET_CATALOG if env in s.envs and s.kind in AUTO_KINDS]


def _patch_gen():
    """Deterministic _generate_secret so assertions don't depend on randomness."""
    return patch.object(SecretsManager, "_generate_secret", side_effect=lambda spec: f"gen::{spec.key_path}")


# ───────────────────────────── secrets set --stdin ─────────────────────────────


class TestSecretsSetStdin:
    def test_stdin_value_with_leading_dash(self) -> None:
        """A `-100…` chat ID piped via --stdin is stored verbatim (newline stripped)."""
        mgr = MagicMock()
        mgr.set_secret.return_value = True
        with patch("toolkit.cli.secrets._get_manager", return_value=mgr):
            result = runner.invoke(
                app,
                ["secrets", "set", "apps.x.chat_log", "--env", "staging", "--stdin"],
                input="-1004406031115\n",
            )
        assert result.exit_code == 0, result.output
        mgr.set_secret.assert_called_once_with("staging", "apps.x.chat_log", "-1004406031115")

    def test_both_value_and_stdin_is_error(self) -> None:
        """Passing both a positional VALUE and --stdin is a clear error, no write."""
        mgr = MagicMock()
        with patch("toolkit.cli.secrets._get_manager", return_value=mgr):
            result = runner.invoke(
                app,
                ["secrets", "set", "apps.x.k", "the-value", "--env", "staging", "--stdin"],
                input="piped\n",
            )
        assert result.exit_code != 0
        mgr.set_secret.assert_not_called()

    def test_empty_stdin_is_error(self) -> None:
        """--stdin with nothing piped fails clearly rather than storing an empty secret."""
        mgr = MagicMock()
        with patch("toolkit.cli.secrets._get_manager", return_value=mgr):
            result = runner.invoke(
                app,
                ["secrets", "set", "apps.x.k", "--env", "staging", "--stdin"],
                input="",
            )
        assert result.exit_code != 0
        mgr.set_secret.assert_not_called()

    def test_positional_value_still_works(self) -> None:
        """Back-compat: positional VALUE (no --stdin) is unchanged."""
        mgr = MagicMock()
        mgr.set_secret.return_value = True
        with patch("toolkit.cli.secrets._get_manager", return_value=mgr):
            result = runner.invoke(
                app,
                ["secrets", "set", "apps.x.k", "plainvalue", "--env", "staging"],
            )
        assert result.exit_code == 0, result.output
        mgr.set_secret.assert_called_once_with("staging", "apps.x.k", "plainvalue")


# ─────────────────────────── secrets init idempotency ──────────────────────────


class TestInitIdempotent:
    ENV = "staging"

    def test_skips_existing_generates_missing(self) -> None:
        keys = _machine_keys(self.ENV)
        assert len(keys) >= 2, "fixture needs >=2 machine-generable staging keys in the catalog"
        existing, missing = keys[0], keys[1]
        audit = AuditResult(env=self.ENV, present=[existing])
        with patch.object(SecretsManager, "audit", return_value=audit), _patch_gen():
            generated = SecretsManager().init_machine_secrets(self.ENV, dry_run=True)
        assert existing not in generated, "an existing secret must NOT be regenerated"
        assert missing in generated, "a missing secret must be generated"

    def test_force_regenerates_all(self) -> None:
        keys = _machine_keys(self.ENV)
        existing = keys[0]
        audit = AuditResult(env=self.ENV, present=[existing])
        with patch.object(SecretsManager, "audit", return_value=audit), _patch_gen():
            generated = SecretsManager().init_machine_secrets(self.ENV, dry_run=True, force=True)
        assert existing in generated, "--force must regenerate even existing secrets"
        assert set(generated) >= set(keys)

    def test_rotate_targets_only_named_key(self) -> None:
        keys = _machine_keys(self.ENV)
        target = keys[0]
        audit = AuditResult(env=self.ENV, present=list(keys))  # everything present
        with patch.object(SecretsManager, "audit", return_value=audit), _patch_gen():
            generated = SecretsManager().init_machine_secrets(self.ENV, dry_run=True, rotate=[target])
        assert set(generated) == {target}, "--rotate KEY must regenerate ONLY that key"

    def test_rotate_unknown_key_errors(self) -> None:
        with _patch_gen():
            generated = SecretsManager().init_machine_secrets(self.ENV, dry_run=True, rotate=["apps.does.not.exist"])
        assert generated == {}, "rotating an unknown key must error (empty result)"

    def test_rotate_non_machine_key_errors(self) -> None:
        non_machine = next(
            (s.key_path for s in SECRET_CATALOG if self.ENV in s.envs and s.kind not in AUTO_KINDS),
            None,
        )
        if non_machine is None:
            pytest.skip("no non-machine staging key in catalog to test")
        with _patch_gen():
            generated = SecretsManager().init_machine_secrets(self.ENV, dry_run=True, rotate=[non_machine])
        assert generated == {}, "rotating a non-machine-generable key must error"
