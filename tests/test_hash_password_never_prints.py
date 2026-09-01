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

1. the value reaches the SOPS write, and
2. the value appears nowhere in stdout or stderr — including on the failure path,
   where the temptation to "at least show it so it isn't lost" is strongest and
   would be exactly wrong.
"""

from __future__ import annotations

from typing import Any

import pytest
import typer

import toolkit.features.secrets_manager as secrets_manager_module
from toolkit.features.credentials import CredentialsManager

PASSWORD = "correct-horse-battery-staple"
KEY = "apps.services.security.authelia.users_manu_password_hash"


class FakeConfigManager:
    """Only supplies the path used in log lines. It must NOT be the write path."""

    def __init__(self, tmp_path: Any) -> None:
        self.secrets_path = tmp_path
        self.env = "prod"


#: Captured writes, keyed by (env, key_path). Module-level so the failure-path
#: test can assert on it without threading a fixture through.
WRITES: dict[tuple[str, str], str] = {}


def _install(monkeypatch: pytest.MonkeyPatch, succeed: bool, tmp_path: Any) -> CredentialsManager:
    """Build a manager whose every write path is intercepted.

    THE SINGLETON IS THE ONE THAT MATTERS. `update_hashed_secret` writes through
    `toolkit.features.secrets_manager.secrets_manager`, imported inside the
    function -- so faking `self.config_manager` alone leaves the real `sops set`
    live. A first version of this file did exactly that, and running it would have
    rewritten the real `prod.enc.yaml` with the argon2 of PASSWORD, silently, in
    three of five tests, before any assertion had a chance to fail.

    A test that mutates the real environment is worse than no test: it passes
    while it destroys. Patch the singleton, and patch it in every test including
    the failure path.
    """
    WRITES.clear()

    def fake_set_secret(env: str, key_path: str, value: str) -> bool:
        WRITES[(env, key_path)] = value
        return succeed

    monkeypatch.setattr(secrets_manager_module.secrets_manager, "set_secret", fake_set_secret)
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: PASSWORD)

    m = CredentialsManager()
    m.config_manager = FakeConfigManager(tmp_path)  # type: ignore[assignment]
    return m


@pytest.fixture
def manager(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> CredentialsManager:
    return _install(monkeypatch, succeed=True, tmp_path=tmp_path)


def _written_hash(_manager: CredentialsManager) -> str:
    return WRITES[("prod", KEY)]


def test_the_hash_is_written_to_sops(manager: CredentialsManager) -> None:
    """The command's contract: the operator runs it and the secret is stored."""
    manager.update_hashed_secret(key_path=KEY, env="prod")

    assert ("prod", KEY) in WRITES
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
    m = _install(monkeypatch, succeed=False, tmp_path=tmp_path)

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
    m = _install(monkeypatch, succeed=True, tmp_path=tmp_path)
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: "")

    with pytest.raises(typer.Exit):
        m.update_hashed_secret(key_path=KEY, env="prod")

    assert WRITES == {}
