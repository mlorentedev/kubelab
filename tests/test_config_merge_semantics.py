"""Tests for the config/secrets deep-merge: an empty mapping must not delete data.

`ConfigurationManager._deep_update` guarded its recursive branch with
``isinstance(value, dict) and value``. An empty mapping is falsy, so it fell
through to the assignment branch and *replaced* the base subtree instead of
recursing into it — an empty dict in an env file silently deleted whatever
`common` declared at that path.

That diverged from the other merge path over the same files. The Ansible
playbooks merge with ``combine(recursive=True)`` (``merge_hash``), which treats
an empty mapping as a Mapping and recurses, preserving the base. So the two
consumers of `common.enc.yaml` + `<env>.enc.yaml` disagreed about what the same
two files meant:

    common:  {dev_node: {github_token: "..."}}
    staging: {dev_node: {}}

    ansible combine(recursive=True) -> {dev_node: {github_token: "..."}}   token kept
    toolkit _deep_update            -> {dev_node: {}}                      token GONE

Found via ANSIBLE-033: the dev-node PAT lived in `common.enc.yaml` and
provisioned correctly through Ansible, while `toolkit secrets audit` reported it
missing — because a leftover `dev_node: {}` in `staging.enc.yaml` erased it on
the toolkit side only. A credential that is present for one tool and absent for
another is the drift the SSOT discipline exists to prevent.

These tests pin the merge contract: an empty mapping is a no-op, every other
override still wins.
"""

from __future__ import annotations

from typing import Any

from toolkit.features.configuration import ConfigurationManager


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Run _deep_update without constructing a ConfigurationManager (no env/IO)."""
    cm = ConfigurationManager.__new__(ConfigurationManager)
    return cm._deep_update(base, override)


class TestEmptyMappingIsANoOp:
    """An empty mapping declares no override, so it must not delete anything."""

    def test_empty_mapping_preserves_base_subtree(self) -> None:
        merged = _merge({"dev_node": {"github_token": "SENTINEL"}}, {"dev_node": {}})
        assert merged["dev_node"] == {"github_token": "SENTINEL"}

    def test_empty_mapping_preserves_deeply_nested_leaf(self) -> None:
        base = {"apps": {"services": {"automation": {"dev_node": {"github_token": "S"}}}}}
        override = {"apps": {"services": {"automation": {"dev_node": {}}}}}
        merged = _merge(base, override)
        token = merged["apps"]["services"]["automation"]["dev_node"]["github_token"]
        assert token == "S"

    def test_empty_mapping_for_absent_key_still_creates_it(self) -> None:
        """Structure-only declarations stay structure — no crash, no invention."""
        assert _merge({"other": 1}, {"argocd": {}}) == {"other": 1, "argocd": {}}


class TestOverridesStillWin:
    """Regression guard: the fix must only affect the empty-mapping case."""

    def test_non_empty_mapping_merges_key_by_key(self) -> None:
        merged = _merge({"a": {"keep": 1, "beat": 1}}, {"a": {"beat": 2, "add": 3}})
        assert merged["a"] == {"keep": 1, "beat": 2, "add": 3}

    def test_scalar_override_replaces(self) -> None:
        assert _merge({"a": "old"}, {"a": "new"})["a"] == "new"

    def test_explicit_none_still_clears_the_value(self) -> None:
        """`key:` (null) remains the way to blank a value; only `{}` changed."""
        assert _merge({"a": "old"}, {"a": None})["a"] is None

    def test_mapping_replaces_scalar(self) -> None:
        assert _merge({"a": "scalar"}, {"a": {"now": "mapping"}})["a"] == {"now": "mapping"}

    def test_list_override_replaces_wholesale(self) -> None:
        """Lists are not merged element-wise — unchanged, pinned to prevent drift."""
        assert _merge({"a": [1, 2, 3]}, {"a": [9]})["a"] == [9]


class TestMergeOrderContract:
    """The documented order is common -> env, with env winning on real values."""

    def test_env_empty_mapping_does_not_beat_common_value(self) -> None:
        merged: dict[str, Any] = {}
        _merge(merged, {"argocd": {"admin_password": "hub"}})
        _merge(merged, {"argocd": {}})
        assert merged["argocd"]["admin_password"] == "hub"


class TestWritePathCannotDestroySecrets:
    """The same merge runs on a path that ENCRYPTS ITS RESULT BACK TO DISK.

    `credentials.py` (`_promote_shared_secrets`) lifts shared subtrees out of an
    env file via `_partition_secrets`, deep-merges them into the decrypted
    `common.enc.yaml`, and re-encrypts the result. `_partition_secrets` copies
    subtrees verbatim, and `apps.services.automation` is one of its SHARED_NESTED
    paths — so an empty mapping in an env file was carried straight into the
    write.

    Under the old semantics that silently DELETED the corresponding subtree from
    `common.enc.yaml` and persisted the deletion. This was not hypothetical:
    `staging.enc.yaml` carried `apps.services.automation.dev_node: {}` while
    `common.enc.yaml` held the dev-node PAT at exactly that path, so a
    `credentials generate` run would have destroyed the credential.

    Read-path breakage is recoverable — you re-run the tool. This is not.
    """

    SHARED_PATH = ("apps", "services", "automation")

    def test_empty_mapping_in_promoted_payload_preserves_the_secret(self) -> None:
        common = {"apps": {"services": {"automation": {"dev_node": {"github_token": "PAT"}}}}}
        promoted = {"apps": {"services": {"automation": {"dev_node": {}}}}}
        _merge(common, promoted)
        automation = common["apps"]["services"]["automation"]
        assert automation["dev_node"] == {"github_token": "PAT"}

    def test_sibling_secrets_survive_an_empty_mapping_promotion(self) -> None:
        common = {
            "apps": {
                "services": {
                    "automation": {
                        "dev_node": {"github_token": "PAT"},
                        "github_runner": {"token": "RUNNER"},
                    }
                }
            }
        }
        _merge(common, {"apps": {"services": {"automation": {"dev_node": {}}}}})
        automation = common["apps"]["services"]["automation"]
        assert automation["github_runner"] == {"token": "RUNNER"}
        assert automation["dev_node"] == {"github_token": "PAT"}
