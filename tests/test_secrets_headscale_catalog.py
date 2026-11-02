"""The Headscale values in SOPS that are not credentials, and how the audit reads them."""

from __future__ import annotations

from typing import Any
from pathlib import Path
from unittest.mock import patch

from toolkit.features.secrets_manager import SECRET_CATALOG, SecretsManager, orphan_key_paths

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SEGMENTS = "apps.services.core.headscale.segments"
AUDIT_SOURCE = "apps.services.core.headscale.audit_sources.audit_automation"


def _vault(headscale: dict[str, Any]) -> dict[str, Any]:
    return {"apps": {"services": {"core": {"headscale": headscale}}}}


def _spec(key: str):
    return next(s for s in SECRET_CATALOG if s.key_path == key)


def _audit_prod(decrypted: dict[str, Any]):
    with patch("toolkit.features.configuration.ConfigurationManager._decrypt_sops", return_value=decrypted):
        return SecretsManager(PROJECT_ROOT).audit("prod")


def test_a_tenant_segment_under_any_neutral_key_has_an_owner() -> None:
    """Key names are plaintext in SOPS, so the catalog owns the subtree, not `tenant-1`."""
    vault = _vault({"segments": {"tenant-7": {"owner": "x", "ports": "y"}}})

    assert orphan_key_paths(vault) == []


def test_the_catalog_never_names_a_tenant() -> None:
    assert not [s.key_path for s in SECRET_CATALOG if s.key_path.startswith(f"{SEGMENTS}.")]


def test_the_segments_are_expected_only_in_prod() -> None:
    assert _spec(SEGMENTS).envs == ("prod",)


def test_an_unset_source_pin_is_a_decision_not_a_gap() -> None:
    """SEC-037 left `from=` unset on purpose, so its absence must not read as Missing."""
    assert _spec(AUDIT_SOURCE).optional is True

    result = _audit_prod(_vault({"segments": {"tenant-1": {"owner": "x"}}}))

    assert AUDIT_SOURCE not in result.missing
    assert AUDIT_SOURCE not in result.present


def test_a_set_source_pin_is_still_held_to_its_shape() -> None:
    result = _audit_prod(_vault({"audit_sources": {"audit_automation": "not an address"}}))

    assert AUDIT_SOURCE in result.malformed


def test_an_ordinary_entry_absent_from_the_vault_is_still_missing() -> None:
    """The flag is opt-in: nothing else may slip out of the audit with it."""
    result = _audit_prod(_vault({}))

    assert SEGMENTS in result.missing
