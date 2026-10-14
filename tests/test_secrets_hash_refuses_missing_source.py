"""#1057: `secrets hash` refuses a missing source instead of minting a secret.

It used to generate a new OIDC client secret whenever the plaintext was absent
from `{env}.enc.yaml`, write it to the vault and log `success`. That is a
rotation nobody asked for: the relying party keeps the old value and fails at its
next login. Generating is `secrets init`'s job; hashing only reads.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from toolkit.features.secrets_manager import HashSourceMissing, SecretsManager, hashed_specs

SECRETS_DIR = Path(__file__).resolve().parents[1] / "infra/config/secrets"
ENV = "prod"


def _nest(paths: list[str]) -> dict[str, Any]:
    tree: dict[str, Any] = {}
    for path in paths:
        *parents, leaf = path.split(".")
        node = tree
        for key in parents:
            node = node.setdefault(key, {})
        node[leaf] = f"plaintext-of-{leaf}"
    return tree


class _Vault:
    """A stand-in for ConfigurationManager whose every write lands in a real file."""

    def __init__(self, directory: Path, decrypted: dict[str, Any]) -> None:
        self.secrets_path = directory
        self.file = directory / f"{ENV}.enc.yaml"
        self.file.write_text("sops: {}\n", encoding="utf-8")
        self.decrypted = decrypted

    def _decrypt_sops(self, _path: Path) -> dict[str, Any]:
        return self.decrypted

    def update_secret_key(self, key: str, value: str) -> bool:
        with self.file.open("a", encoding="utf-8") as handle:
            handle.write(f"{key}: {value}\n")
        return True

    def batch_update_secrets(self, values: dict[str, str]) -> bool:
        for key, value in values.items():
            self.update_secret_key(key, value)
        return True


def _manager(monkeypatch: pytest.MonkeyPatch, vault: _Vault) -> SecretsManager:
    manager = SecretsManager()
    monkeypatch.setattr(manager, "_cm", lambda _env: vault)
    hasher = SimpleNamespace(generate_argon2_hash=lambda value: f"$argon2id$of-{value}")
    monkeypatch.setattr(manager, "_credentials_manager", lambda: hasher)
    return manager


def test_a_missing_source_is_refused_and_the_vault_is_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = [spec.derived_from for spec in hashed_specs(ENV)]
    assert len(sources) > 1, "the catalog no longer hashes several sources in prod"
    absent = sources[-1]
    vault = _Vault(tmp_path, _nest(sources[:-1]))
    before = vault.file.read_bytes()

    with pytest.raises(HashSourceMissing) as refusal:
        _manager(monkeypatch, vault).hash_oidc_secrets(ENV)

    assert absent in str(refusal.value)
    assert f"{ENV}.enc.yaml" in str(refusal.value)
    assert vault.file.read_bytes() == before


def test_an_empty_source_is_refused_as_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A key holding "" is no source: hashing it would publish a digest of the empty string."""
    sources = [spec.derived_from for spec in hashed_specs(ENV)]
    tree = _nest(sources)
    *parents, leaf = sources[0].split(".")
    node = tree
    for key in parents:
        node = node[key]
    node[leaf] = ""
    vault = _Vault(tmp_path, tree)
    before = vault.file.read_bytes()

    with pytest.raises(HashSourceMissing, match="missing or empty") as refusal:
        _manager(monkeypatch, vault).hash_oidc_secrets(ENV)

    assert sources[0] in str(refusal.value)
    assert vault.file.read_bytes() == before


def test_with_every_source_present_only_hashes_are_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    specs = hashed_specs(ENV)
    vault = _Vault(tmp_path, _nest([spec.derived_from for spec in specs]))

    hashes = _manager(monkeypatch, vault).hash_oidc_secrets(ENV)

    assert set(hashes) == {spec.key_path for spec in specs}
    written = {line.split(":", 1)[0] for line in vault.file.read_text(encoding="utf-8").splitlines()[1:]}
    assert written == {spec.key_path for spec in specs}


def test_hashing_cannot_reach_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_minting(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("hash_oidc_secrets generated a secret")

    monkeypatch.setattr("secrets.token_urlsafe", no_minting)
    monkeypatch.setattr(SecretsManager, "init_machine_secrets", no_minting)
    vault = SimpleNamespace(
        secrets_path=Path("/nonexistent"),
        _decrypt_sops=lambda _path: {"apps": {}},
        update_secret_key=no_minting,
        batch_update_secrets=no_minting,
    )
    manager = SecretsManager()
    monkeypatch.setattr(manager, "_cm", lambda _env: vault)
    with pytest.raises(HashSourceMissing):
        manager.hash_oidc_secrets(ENV)


def test_an_undecryptable_file_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No age key, or no file: every source is missing, so the command must not report success."""
    vault = _Vault(tmp_path, {})
    with pytest.raises(HashSourceMissing, match="cannot decrypt"):
        _manager(monkeypatch, vault).hash_oidc_secrets(ENV)


def test_the_cli_fails_when_nothing_was_written(monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from toolkit.cli import secrets as cli

    manager = SimpleNamespace(hash_oidc_secrets=lambda _env: {})
    monkeypatch.setattr(cli, "_get_manager", lambda: manager)
    run = CliRunner().invoke(cli.app, ["hash", "--env", ENV])
    assert run.exit_code == 1, run.output


@pytest.mark.parametrize("env", ["dev", "staging", "prod"])
def test_every_hashed_source_lives_in_its_own_env_file(env: str) -> None:
    """AC4: no spec resolves to "missing" as a normal condition.

    SOPS leaves key names in plaintext, so this reads the encrypted file and never
    decrypts a value.
    """
    tree = yaml.safe_load((SECRETS_DIR / f"{env}.enc.yaml").read_text(encoding="utf-8"))
    specs = hashed_specs(env)
    assert specs, f"no hashed specs for {env}: this case would check nothing"
    # The command's own resolver and its own test, so the two cannot disagree on "present".
    absent = [spec.derived_from for spec in specs if not SecretsManager._resolve_key(tree, spec.derived_from)]
    assert not absent, f"{env}.enc.yaml lacks hash sources: {absent}"
