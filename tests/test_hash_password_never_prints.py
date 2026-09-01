"""AUTH-004 — `hash-password` writes the hash to SOPS and never puts it on stdout.

The defect this guards against is not hypothetical and was not a slip. Until
2026-09-01 `update_hashed_secret` **printed** the argon2 hash with "Please manually
update the secret", so a copy-paste through the operator's terminal was the only
way to use the command. The tool's design made the exposure mandatory, and it duly
put an Authelia credential into a session transcript — durable, possibly synced,
scanned by nothing and un-printable by nothing.

The hash is the stored credential rather than a derivative: Authelia keeps no
password, only this, so whoever holds it can attack it offline at their leisure.

Two properties, both asserted on the observable output rather than on the shape of
the code, so a refactor that reintroduces a print fails here:

1. the value reaches `batch_update_secrets`, and
2. the value appears nowhere in stdout or stderr — including on the failure path,
   where the temptation to "at least show it so it isn't lost" is strongest and
   would be exactly wrong.
"""

from __future__ import annotations

from typing import Any

import pytest
import typer

from toolkit.features.credentials import CredentialsManager

PASSWORD = "correct-horse-battery-staple"
KEY = "apps.services.security.authelia.users_manu_password_hash"


class FakeConfigManager:
    """Captures what would be written, and whether the write is allowed to succeed."""

    def __init__(self, tmp_path: Any, succeed: bool = True) -> None:
        self.secrets_path = tmp_path
        self.env = "prod"
        self.succeed = succeed
        self.written: dict[str, Any] = {}

    def batch_update_secrets(self, secrets: dict[str, Any], secret_file_path: Any = None) -> bool:
        self.written.update(secrets)
        return self.succeed


@pytest.fixture
def manager(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> CredentialsManager:
    m = CredentialsManager()
    m.config_manager = FakeConfigManager(tmp_path)  # type: ignore[assignment]
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: PASSWORD)
    return m


def _written_hash(manager: CredentialsManager) -> str:
    return str(manager.config_manager.written[KEY])  # type: ignore[attr-defined]


def test_the_hash_is_written_to_sops(manager: CredentialsManager) -> None:
    """The command's contract: the operator runs it and the secret is stored."""
    manager.update_hashed_secret(key_path=KEY, env="prod")

    assert KEY in manager.config_manager.written  # type: ignore[attr-defined]
    assert _written_hash(manager).startswith("$argon2id$")


def test_the_hash_never_reaches_stdout(manager: CredentialsManager, capsys: pytest.CaptureFixture[str]) -> None:
    """The property that matters. Asserted on captured output, not on the source.

    A future edit that helpfully echoes the value "so the operator can verify it"
    fails here, which is the only place that decision gets caught — no scanner
    reads a terminal.
    """
    manager.update_hashed_secret(key_path=KEY, env="prod")
    written = _written_hash(manager)

    captured = capsys.readouterr()
    assert written not in captured.out
    assert written not in captured.err
    # The distinctive prefix too: a truncated or reformatted echo is the same leak.
    assert "$argon2id$" not in captured.out
    assert "$argon2id$" not in captured.err


def test_the_plaintext_password_never_reaches_stdout(
    manager: CredentialsManager, capsys: pytest.CaptureFixture[str]
) -> None:
    """The stronger sibling: the password itself must not be echoed either."""
    manager.update_hashed_secret(key_path=KEY, env="prod")

    captured = capsys.readouterr()
    assert PASSWORD not in captured.out
    assert PASSWORD not in captured.err


def test_a_failed_write_reports_the_key_and_not_the_value(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The failure path, where "at least print it so it isn't lost" is most tempting.

    Losing the password is recoverable — the operator runs the command again. A
    leaked hash is not recoverable, so the failure stays quiet about the value and
    loud about the key.
    """
    m = CredentialsManager()
    m.config_manager = FakeConfigManager(tmp_path, succeed=False)  # type: ignore[assignment]
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: PASSWORD)

    with pytest.raises(typer.Exit):
        m.update_hashed_secret(key_path=KEY, env="prod")

    captured = capsys.readouterr()
    assert "$argon2id$" not in captured.out
    assert "$argon2id$" not in captured.err
    assert PASSWORD not in captured.out
    assert KEY in captured.out + captured.err


def test_an_empty_password_is_refused_before_hashing(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pre-existing behaviour, pinned so the rewrite did not drop it."""
    m = CredentialsManager()
    m.config_manager = FakeConfigManager(tmp_path)  # type: ignore[assignment]
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: "")

    with pytest.raises(typer.Exit):
        m.update_hashed_secret(key_path=KEY, env="prod")

    assert m.config_manager.written == {}  # type: ignore[attr-defined]
