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

# A hub credential is one the catalog marks HUB_MANAGED (written to common by
# `credentials generate`) OR one delivered to the hub through Secret Manager.
# The second group includes EXTERNAL keys such as the Argo CD webhooks, and
# `sync-secret-manager` and `deploy-argocd` both read them from common only.
# Deriving the set from both flags, not from the kind alone, keeps a future
# per-env override of any of them from reproducing SSOT-028 unguarded.
HUB_KEYS = sorted(
    s.key_path for s in SECRET_CATALOG if s.kind == SecretKind.HUB_MANAGED or s.sync_to_secret_manager
)


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


class TestCredentialsGenerateWritesHubKeysToCommon:
    """The writer half (Codex P1 on #1790): `credentials generate` must not re-create the copy.

    Before this, the Argo CD OIDC pair went into `generated_secrets`, the per-env
    batch, and only `argocd.admin_password{,_hash}` went to common. So every prod
    rotation put a fresh shadow pair back into `prod.enc.yaml`. That re-broke
    Argo CD SSO and turned the guard above red.
    """

    def _run(self, monkeypatch: pytest.MonkeyPatch) -> list[tuple[dict[str, Any], Path | None]]:
        from unittest.mock import MagicMock

        from toolkit.features import credentials

        writes: list[tuple[dict[str, Any], Path | None]] = []
        cm = MagicMock()
        cm.get_merged_config.return_value = {"apps": {"auth": {"identities": {"operator": "operator"}}}}
        cm.batch_update_secrets.side_effect = lambda data, secret_file_path=None: writes.append(
            (dict(data), secret_file_path)
        ) or True
        monkeypatch.setattr(credentials, "ConfigurationManager", MagicMock(return_value=cm))
        answers = iter(["operator", "Passw0rdForTests"])
        monkeypatch.setattr(credentials.typer, "prompt", lambda *a, **k: next(answers))

        manager = credentials.CredentialsManager()
        monkeypatch.setattr(manager, "_read_existing_secrets", lambda env: {})
        monkeypatch.setattr(manager, "generate_argon2_hash", lambda s: "$argon2id$fake")
        monkeypatch.setattr(manager, "generate_oidc_client_secret_hash", lambda s: "$argon2id$fake")
        monkeypatch.setattr(manager, "generate_bcrypt_hash", lambda s: "$2b$fake")
        monkeypatch.setattr(manager, "_generate_htpasswd_bcrypt_hash", lambda u, p: "u:$2y$fake")
        monkeypatch.setattr(manager, "_reconcile_external_credentials", lambda *a, **k: None)

        def no_jwks(*_: Any, **__: Any) -> str:
            raise RuntimeError("not in a unit test: nothing may be written to the repo")

        monkeypatch.setattr(manager, "generate_jwks_rsa_key", no_jwks)
        manager.setup_authelia_secrets("prod", auto_update=True)
        return writes

    def test_no_hub_key_goes_to_the_env_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        env_writes = [data for data, path in self._run(monkeypatch) if path is None]
        assert env_writes, "the per-env batch was never written: the test exercised nothing"
        leaked = sorted(k for data in env_writes for k in data if k in HUB_KEYS)
        assert not leaked, f"credentials generate writes hub keys to prod.enc.yaml: {leaked}"

    def test_every_generated_hub_key_goes_to_common(self, monkeypatch: pytest.MonkeyPatch) -> None:
        common = {
            k
            for data, path in self._run(monkeypatch)
            if path is not None and Path(path).name == "common.enc.yaml"
            for k in data
        }
        generated = sorted(s.key_path for s in SECRET_CATALOG if s.kind == SecretKind.HUB_MANAGED)
        assert set(generated) <= common, f"HUB_MANAGED keys not written to common: {set(generated) - common}"
