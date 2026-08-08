"""Tests for ANSIBLE-033: track the dev-node PAT in SECRET_CATALOG.

The ace2 dev node gets its own machine identity — a fine-grained GitHub PAT that
authenticates both `gh` and `git` over HTTPS. It lives in `common.enc.yaml`, not
per-env, because it authenticates a *machine* to GitHub and GitHub is not an
environment.

Two invariants are worth pinning, because both were broken at some point while
this spec was being written:

1. **The key is registered at all.** It sat in SOPS but not in `SECRET_CATALOG`,
   so `toolkit secrets audit` never checked it — a blank or missing dev-node
   token would have reported "all present". Same class of gap as TOOL-023/D64.

2. **The audit actually resolves it through the common+env merge.** This is the
   regression guard for the `_deep_update` bug fixed in #891: a leftover empty
   mapping at `apps.services.automation.dev_node` in `staging.enc.yaml` erased
   the common subtree on the toolkit side, so the token was present for Ansible
   and missing for the toolkit. The audit must see a token that only common
   declares.

There is no `common` pseudo-env in this catalog — `envs` is the *audit*
dimension. The key is audited under `staging` because that is the environment
ace2 provisions with (`make provision NODE=ace2 ENV=staging`), and `audit()`
merges common in. The Argo CD hub keys use the same trick under `prod`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from toolkit.config.settings import PROJECT_ROOT
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.secrets_manager import (
    SECRET_CATALOG,
    SecretKind,
    SecretsManager,
)

DEV_NODE_TOKEN = "apps.services.automation.dev_node.github_token"

# Kinds that `init_machine_secrets` auto-generates into the PER-ENV vault.
AUTO_KINDS = {
    SecretKind.RANDOM_HEX,
    SecretKind.RANDOM_TOKEN,
    SecretKind.OIDC_CLIENT_SECRET,
    SecretKind.RSA_KEY,
}

_CATALOG_BY_KEY = {s.key_path: s for s in SECRET_CATALOG}

# What common.enc.yaml holds: the token, plus a sibling under the same parent.
_COMMON: dict[str, Any] = {
    "apps": {
        "services": {
            "automation": {
                "dev_node": {"github_token": "github_pat_11ABCDEFG_realish_looking_value"},
                "github_runner": {"token": "ghp_runner_token"},
            }
        }
    }
}


def _sops_side_effect(common: dict[str, Any], env: dict[str, Any]):
    """Return different payloads for common.enc.yaml vs <env>.enc.yaml."""

    def _decrypt(path: Path) -> dict[str, Any]:
        return common if Path(path).name == "common.enc.yaml" else env

    return _decrypt


class TestDevNodeTokenRegistered:
    def test_token_is_in_catalog(self) -> None:
        assert DEV_NODE_TOKEN in _CATALOG_BY_KEY, (
            "dev-node PAT absent from SECRET_CATALOG — `secrets audit` would not check it"
        )

    def test_token_is_operator_supplied_not_machine_generable(self) -> None:
        """A PAT is minted at GitHub; `secrets init` must never invent one."""
        spec = _CATALOG_BY_KEY[DEV_NODE_TOKEN]
        assert spec.kind is SecretKind.EXTERNAL
        assert spec.kind not in AUTO_KINDS

    def test_token_is_audited_under_staging(self) -> None:
        """ace2 provisions with ENV=staging; common merges into that audit."""
        assert _CATALOG_BY_KEY[DEV_NODE_TOKEN].envs == ("staging",)

    def test_rotate_note_points_at_the_runbook(self) -> None:
        """The token expires, so the catalog must say where the procedure lives."""
        note = _CATALOG_BY_KEY[DEV_NODE_TOKEN].rotate_note
        assert "dev-node-token-rotation" in note
        assert "revoke" in note.lower()


class TestAuditResolvesTokenFromCommon:
    """The token is declared ONLY in common; the staging audit must still see it."""

    def test_present_when_only_common_declares_it(self) -> None:
        side_effect = _sops_side_effect(_COMMON, {"apps": {"services": {"automation": {}}}})
        with patch.object(ConfigurationManager, "_decrypt_sops", side_effect=side_effect):
            result = SecretsManager(PROJECT_ROOT).audit("staging")
        assert DEV_NODE_TOKEN in result.present

    def test_empty_env_mapping_does_not_hide_it(self) -> None:
        """Regression guard for #891.

        `staging.enc.yaml` carried `apps.services.automation.dev_node: {}` after
        the token moved to common. Under the old merge that empty mapping
        replaced the common subtree, so the audit reported a token that exists as
        missing — present for Ansible, absent for the toolkit.
        """
        env = {"apps": {"services": {"automation": {"dev_node": {}}}}}
        side_effect = _sops_side_effect(_COMMON, env)
        with patch.object(ConfigurationManager, "_decrypt_sops", side_effect=side_effect):
            result = SecretsManager(PROJECT_ROOT).audit("staging")
        assert DEV_NODE_TOKEN not in result.missing, (
            "an empty mapping in the env vault must not hide a secret declared in common"
        )
        assert DEV_NODE_TOKEN in result.present

    def test_missing_token_is_flagged_not_invisible(self) -> None:
        """The whole point of registering it: absence must be reported."""
        common_without = {"apps": {"services": {"automation": {"github_runner": {"token": "x"}}}}}
        side_effect = _sops_side_effect(common_without, {})
        with patch.object(ConfigurationManager, "_decrypt_sops", side_effect=side_effect):
            result = SecretsManager(PROJECT_ROOT).audit("staging")
        assert DEV_NODE_TOKEN in result.missing

    def test_placeholder_counts_as_missing(self) -> None:
        """A REPLACE_WITH_SOPS_VALUE sentinel is syntactically present, not configured."""
        common_placeholder = {
            "apps": {"services": {"automation": {"dev_node": {"github_token": "REPLACE_WITH_SOPS_VALUE"}}}}
        }
        side_effect = _sops_side_effect(common_placeholder, {})
        with patch.object(ConfigurationManager, "_decrypt_sops", side_effect=side_effect):
            result = SecretsManager(PROJECT_ROOT).audit("staging")
        assert DEV_NODE_TOKEN in result.missing
