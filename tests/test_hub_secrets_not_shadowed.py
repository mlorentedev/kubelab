"""SSOT-028: a hub credential lives in `common.enc.yaml` only.

The Argo CD hub is one management plane, not a per-environment deployment, so its
credentials are written to common SOPS and read from there by every consumer:
`deploy-argocd`, Secret Manager, and so the hub itself. A copy of one of them in a
per-env file is not a harmless duplicate. `get_merged_config(env)` lets the env file
override common, so every generator for that env silently uses the copy while the
hub keeps using the original.

Measured 2026-09-23: `prod.enc.yaml` carried its own `oidc_client_secret_argocd`
pair. Authelia registered prod's digest, the hub sent common's secret, and Argo CD
SSO failed with `invalid_client`. Both pairs were self-consistent, so no audit that
checks a pair against itself could see it.

SOPS encrypts values, not key names, so this reads the committed files without
decrypting anything and runs in CI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.features.secrets_manager import SECRET_CATALOG, SecretKind

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECRETS_DIR = PROJECT_ROOT / "infra/config/secrets"

HUB_KEYS = sorted(s.key_path for s in SECRET_CATALOG if s.kind == SecretKind.HUB_MANAGED)


def _has_key(doc: dict[str, Any], dotted: str) -> bool:
    node: Any = doc
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def _env_files() -> list[Path]:
    return sorted(p for p in SECRETS_DIR.glob("*.enc.yaml") if p.name != "common.enc.yaml")


def test_the_catalog_declares_hub_keys() -> None:
    """An empty HUB_KEYS would make the guard below pass vacuously."""
    assert HUB_KEYS, "no HUB_MANAGED secret in SECRET_CATALOG: the shadow guard checks nothing"


def test_every_hub_key_is_in_common() -> None:
    common = yaml.safe_load((SECRETS_DIR / "common.enc.yaml").read_text(encoding="utf-8"))
    missing = [key for key in HUB_KEYS if not _has_key(common, key)]
    assert not missing, f"hub keys absent from common.enc.yaml: {missing}"


@pytest.mark.parametrize("path", _env_files(), ids=lambda p: p.name)
def test_no_env_file_shadows_a_hub_key(path: Path) -> None:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    shadowed = [key for key in HUB_KEYS if _has_key(doc, key)]
    assert not shadowed, (
        f"{path.name} carries hub key(s) {shadowed}. They override common.enc.yaml in the merged "
        f"config, so generators use this copy while the hub uses common's. Remove them with "
        f"`toolkit secrets unset <key> --env {path.name.split('.')[0]}`."
    )
