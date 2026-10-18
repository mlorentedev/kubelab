"""#1777: `credentials generate` mints exactly the OIDC client secrets the SSOT declares.

The client list lives in `apps.services.security.authelia.oidc_clients`. The minting used
to be a hardcoded sequence beside it, and the two drifted both ways: it rotated a pair for
`kubelab-oidc`, which nothing registers, and never rotated `vikunja-oidc` or
`open-webui-oidc`, which are registered. Each client's keys come from `SECRET_CATALOG`: the
digest key from `oidc_clients.digest_key`, and the plaintext from that spec's `derived_from`
(Gitea's plaintext lives with Gitea, not under Authelia).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from toolkit.features import oidc_clients
from toolkit.features.secrets_manager import SECRET_CATALOG

ENVS = ("dev", "staging", "prod")
SPECS = {s.key_path: s for s in SECRET_CATALOG}


def _declared_keys(env: str) -> set[str]:
    values = oidc_clients.load_values(env)
    keys: set[str] = set()
    for client in oidc_clients.declared_clients(values):
        if env in client["envs"]:
            digest = oidc_clients.digest_key(client["client_id"])
            keys |= {digest, SPECS[digest].derived_from}
    return keys


def _is_oidc_client_key(key: str) -> bool:
    return "oidc_client_secret" in key


def _run(env: str, monkeypatch: pytest.MonkeyPatch) -> tuple[set[str], list[str]]:
    from toolkit.features import credentials

    written: set[str] = set()
    cm = MagicMock()
    cm.get_merged_config.return_value = {"apps": {"auth": {"identities": {"operator": "operator"}}}}
    cm.batch_update_secrets.side_effect = lambda data, secret_file_path=None: written.update(data) or True
    monkeypatch.setattr(credentials, "ConfigurationManager", MagicMock(return_value=cm))
    answers = iter(["operator", "Passw0rdForTests"])
    monkeypatch.setattr(credentials.typer, "prompt", lambda *a, **k: next(answers))
    notes: list[str] = []
    monkeypatch.setattr(credentials.logger, "warning", lambda msg, *a, **k: notes.append(str(msg)))

    manager = credentials.CredentialsManager()
    monkeypatch.setattr(manager, "_read_existing_secrets", lambda env: {})
    monkeypatch.setattr(manager, "generate_argon2_hash", lambda s: "$argon2id$fake")
    monkeypatch.setattr(manager, "generate_oidc_client_secret_hash", lambda s: "$argon2id$fake")
    monkeypatch.setattr(manager, "generate_bcrypt_hash", lambda s: "$2b$fake")
    monkeypatch.setattr(manager, "_generate_htpasswd_bcrypt_hash", lambda u, p: "u:$2y$fake")
    monkeypatch.setattr(manager, "_reconcile_external_credentials", lambda *a, **k: None)
    monkeypatch.setattr(manager, "_reconcile_services", lambda *a, **k: None)
    manager.setup_authelia_secrets(env, auto_update=True)
    return {k for k in written if _is_oidc_client_key(k)}, notes


@pytest.mark.parametrize("env", ENVS)
def test_every_declared_client_has_its_digest_and_plaintext_in_the_catalog(env: str) -> None:
    values = oidc_clients.load_values(env)
    for client in oidc_clients.declared_clients(values):
        digest = oidc_clients.digest_key(client["client_id"])
        assert digest in SPECS, f"{client['client_id']}: no SECRET_CATALOG entry {digest}"
        assert SPECS[digest].derived_from in SPECS, f"{client['client_id']}: its plaintext is not catalogued"


@pytest.mark.parametrize("env", ENVS)
def test_the_generator_mints_exactly_the_declared_clients(env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    minted, _ = _run(env, monkeypatch)
    declared = _declared_keys(env)
    assert minted - declared == set(), f"{env}: minted for no declared client: {sorted(minted - declared)}"
    assert declared - minted == set(), f"{env}: declared but never minted: {sorted(declared - minted)}"


def test_each_rotated_client_names_the_delivery_step_it_did_not_perform(monkeypatch: pytest.MonkeyPatch) -> None:
    """Until #1356 models delivery, a rotation that reaches a consumer only later says so, per client."""
    _, notes = _run("prod", monkeypatch)
    values = oidc_clients.load_values("prod")
    for client in oidc_clients.declared_clients(values):
        if "prod" in client["envs"]:
            assert any(client["client_id"] in note for note in notes), f"{client['client_id']}: no delivery note"


def test_the_retired_kubelab_oidc_pair_is_an_acknowledged_orphan() -> None:
    import yaml

    baseline = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "infra/config/orphan-secrets-baseline.yaml").read_text()
    )
    orphans: dict[str, Any] = baseline["orphans"]
    for key in ("oidc_client_secret", "oidc_client_secret_hash"):
        path = f"apps.services.security.authelia.{key}"
        assert path not in SPECS, f"{path} is still catalogued, so audits keep demanding a secret nothing reads"
        assert path in orphans, f"{path} must be acknowledged in the orphan baseline until SOPS drops it"
