"""#1777: `credentials generate` mints exactly the OIDC client secrets the SSOT declares.

The client list lives in `apps.services.security.authelia.oidc_clients`. The minting used
to be a hardcoded sequence beside it, and the two drifted both ways: it rotated a pair for
`kubelab-oidc`, which nothing registers, and never rotated `vikunja-oidc` or
`open-webui-oidc`, which are registered. Each client's keys come from `SECRET_CATALOG`: the
digest key from `oidc_clients.digest_key`, and the plaintext from that spec's `derived_from`
(Gitea's plaintext lives with Gitea, not under Authelia).
"""

from __future__ import annotations

import dataclasses
import sys
from unittest.mock import MagicMock

import pytest

from toolkit.features import oidc_clients
from toolkit.features.secrets_manager import SECRET_CATALOG, SecretKind

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


def _run(env: str, monkeypatch: pytest.MonkeyPatch, written: set[str] | None = None) -> tuple[set[str], list[str]]:
    from toolkit.features import credentials

    written = set() if written is None else written
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


def test_the_manual_copy_prints_hub_keys_under_common_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Printed under the env file's header, the Argo CD pair would be copied into the shadow SSOT-028 removed."""
    from toolkit.features import credentials

    cm = MagicMock()
    cm.get_merged_config.return_value = {"apps": {"auth": {"identities": {"operator": "operator"}}}}
    monkeypatch.setattr(credentials, "ConfigurationManager", MagicMock(return_value=cm))
    answers = iter(["operator", "Passw0rdForTests"])
    monkeypatch.setattr(credentials.typer, "prompt", lambda *a, **k: next(answers))
    manager = credentials.CredentialsManager()
    for name, fake in {
        "_read_existing_secrets": lambda env: {},
        "generate_argon2_hash": lambda s: "$argon2id$fake",
        "generate_oidc_client_secret_hash": lambda s: "$argon2id$fake",
        "generate_bcrypt_hash": lambda s: "$2b$fake",
        "_generate_htpasswd_bcrypt_hash": lambda u, p: "u:$2y$fake",
    }.items():
        monkeypatch.setattr(manager, name, fake)

    # The headers are logged (stderr) and the values printed (stdout): read them in the
    # order the operator's terminal shows them, as `2>&1` would.
    monkeypatch.setattr(sys, "stderr", sys.stdout)
    manager.setup_authelia_secrets("prod", print_secrets=True)

    out = capsys.readouterr().out
    _, env_header, rest = out.partition("Generated secrets for prod.enc.yaml")
    env_block, hub_header, hub_block = rest.partition("Generated secrets for common.enc.yaml")
    assert env_header and hub_header, "each file gets its own block"
    assert "oidc_client_secret_grafana" in env_block
    assert "oidc_client_secret_argocd" not in env_block
    assert "oidc_client_secret_argocd" in hub_block


def _is_hub(key: str) -> bool:
    return SPECS[key].kind == SecretKind.HUB_MANAGED


@pytest.mark.parametrize("env", ENVS)
def test_every_declared_pair_agrees_on_hub_managed(env: str) -> None:
    """#2522: the pair goes to one file, so a digest and plaintext that disagree put one half in the wrong one."""
    clients = oidc_clients.declared_clients(oidc_clients.load_values(env))
    assert clients, f"{env}: no declared OIDC client, so this check would compare nothing"
    for client in clients:
        digest = oidc_clients.digest_key(client["client_id"])
        plaintext = SPECS[digest].derived_from
        assert _is_hub(digest) == _is_hub(plaintext), (
            f"{client['client_id']}: {digest} and {plaintext} disagree on HUB_MANAGED"
        )


def test_a_mixed_pair_is_refused_before_anything_is_written(monkeypatch: pytest.MonkeyPatch) -> None:
    """#2522: a HUB_MANAGED digest whose plaintext is per-env must stop the run, not pick one file for both."""
    from toolkit.features import secrets_manager

    plaintext = oidc_clients.digest_key("argocd")
    plaintext = SPECS[plaintext].derived_from
    mixed = [
        dataclasses.replace(s, kind=SecretKind.OIDC_CLIENT_SECRET) if s.key_path == plaintext else s
        for s in SECRET_CATALOG
    ]
    monkeypatch.setattr(secrets_manager, "SECRET_CATALOG", mixed)

    written: set[str] = set()
    with pytest.raises(oidc_clients.OidcClientError, match="HUB_MANAGED"):
        _run("prod", monkeypatch, written)
    assert written == set(), f"keys written before the refusal: {sorted(written)}"


# Catalogued OIDC secrets that belong to no declared client, each with the ticket that
# retires it. The kubelab-oidc pair sat here unnoticed until #1777 AC3 removed it.
UNDECLARED_OIDC_ENTRIES = {
    "apps.services.core.vikunja.oidc_client_secret": "#2508: stale copy of authelia.oidc_client_secret_vikunja",
}


def test_every_catalogued_oidc_secret_belongs_to_a_declared_client() -> None:
    declared: set[str] = set()
    for env in ENVS:
        for client in oidc_clients.declared_clients(oidc_clients.load_values(env)):
            digest = oidc_clients.digest_key(client["client_id"])
            declared |= {digest, SPECS[digest].derived_from}
    catalogued = {key for key in SPECS if "oidc_client_secret" in key}
    assert catalogued, "no OIDC secret is catalogued, so this check would compare nothing"
    orphans = sorted(catalogued - declared - set(UNDECLARED_OIDC_ENTRIES))
    assert not orphans, f"catalogued OIDC secrets no declared client uses: {orphans}"
    stale = sorted(set(UNDECLARED_OIDC_ENTRIES) - catalogued)
    assert not stale, f"exceptions that are no longer catalogued, drop them: {stale}"
