"""#1733 (SEC-017): `credentials generate` never prints a secret unless asked to.

Its default path used to print about fifteen generated values "for manual copy
to SOPS", and a failed SOPS write fell back to the same printout. An agent
running the documented command put every one of them in a transcript that
nothing scans and nothing can un-print. Now the default names the keys it would
write, `--print-secrets` is the only way to see a value, and a failed write
exits non-zero with nothing printed in its place.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from toolkit.features import credentials

# Shorter values are the username and fixed markers, not generated secrets.
SECRET_MIN_LENGTH = 12


def _manager(monkeypatch: pytest.MonkeyPatch, *, write_ok: tuple[bool, bool] = (True, True)) -> Any:
    """A CredentialsManager whose every side effect is mocked, as in test_hub_secrets_not_shadowed."""
    outcomes = iter(write_ok)
    cm = MagicMock()
    cm.get_merged_config.return_value = {"apps": {"auth": {"identities": {"operator": "operator"}}}}
    cm.batch_update_secrets.side_effect = lambda data, secret_file_path=None: next(outcomes)
    monkeypatch.setattr(credentials, "ConfigurationManager", MagicMock(return_value=cm))
    answers = iter(["operator", "Passw0rdForTests"])
    monkeypatch.setattr(credentials.typer, "prompt", lambda *a, **k: next(answers))

    manager = credentials.CredentialsManager()
    monkeypatch.setattr(manager, "_read_existing_secrets", lambda env: {})
    monkeypatch.setattr(manager, "generate_argon2_hash", lambda s: "$argon2id$fake")
    monkeypatch.setattr(manager, "generate_oidc_client_secret_hash", lambda s: "$argon2id$fake")
    monkeypatch.setattr(manager, "generate_bcrypt_hash", lambda s: "$2b$fake")
    monkeypatch.setattr(manager, "_generate_htpasswd_bcrypt_hash", lambda u, p: "u:$2y$fake")
    manager.reconciled = []
    monkeypatch.setattr(manager, "_reconcile_external_credentials", lambda *a, **k: manager.reconciled.append(a))

    def no_jwks(*_: Any, **__: Any) -> str:
        raise RuntimeError("not in a unit test: nothing may be written to the repo")

    monkeypatch.setattr(manager, "generate_jwks_rsa_key", no_jwks)
    return manager


def _capture_generated(monkeypatch: pytest.MonkeyPatch, manager: Any) -> dict[str, str]:
    """Every value the run generates, read where the env set is fixed and the hub set is built."""
    seen: dict[str, str] = {}
    preserve = manager.preserve_break_glass

    def spy(generated: dict[str, str], existing: dict[str, str]) -> dict[str, str]:
        result = preserve(generated, existing)
        seen.update(result)
        return result

    monkeypatch.setattr(manager, "preserve_break_glass", spy)
    original_report = manager._report_secret_names

    def report(env: str, generated: dict[str, str], hub: dict[str, str]) -> None:
        seen.update(hub)
        original_report(env, generated, hub)

    monkeypatch.setattr(manager, "_report_secret_names", report)

    # The write path never reaches the report, so read the values where they are written.
    cm = manager.config_manager
    write = cm.batch_update_secrets.side_effect

    def recording(data: dict[str, str], secret_file_path: Any = None) -> bool:
        seen.update(data)
        return write(data, secret_file_path=secret_file_path)

    cm.batch_update_secrets.side_effect = recording
    return seen


def _flat(text: str) -> str:
    """Rich wraps long lines; a secret split across two is still on screen."""
    return re.sub(r"\s+", "", text)


def _secret_values(generated: dict[str, str]) -> set[str]:
    return {v for v in generated.values() if isinstance(v, str) and len(v) >= SECRET_MIN_LENGTH}


def test_the_default_names_every_key_and_shows_no_value(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manager = _manager(monkeypatch)
    generated = _capture_generated(monkeypatch, manager)

    manager.setup_authelia_secrets("prod")

    out = _flat("".join(capsys.readouterr()))
    values = _secret_values(generated)
    assert len(values) >= 10, "the run generated too few secrets for this check to mean anything"
    assert not [v for v in values if _flat(v) in out], "a generated secret value reached the output"
    missing = [k for k in generated if _flat(k) not in out]
    assert not missing, f"the default path did not name {missing}"


def test_values_are_printed_only_when_asked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manager = _manager(monkeypatch)
    generated = _capture_generated(monkeypatch, manager)

    manager.setup_authelia_secrets("prod", print_secrets=True)

    out = _flat("".join(capsys.readouterr()))
    assert any(_flat(v) in out for v in _secret_values(generated)), "--print-secrets printed no value"


@pytest.mark.parametrize(
    ("write_ok", "names"),
    [((False, True), "prod.enc.yaml"), ((True, False), "common.enc.yaml")],
    ids=["env-file", "hub-file"],
)
def test_a_failed_write_raises_and_prints_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], write_ok: tuple[bool, bool], names: str
) -> None:
    manager = _manager(monkeypatch, write_ok=write_ok)
    generated = _capture_generated(monkeypatch, manager)
    # Where each write went, not only what the error says: the message is built
    # from its own literal, so it would name the hub file whatever path was written.
    targets: list[str] = []
    write = manager.config_manager.batch_update_secrets.side_effect

    def targeting(data: dict[str, str], secret_file_path: Any = None) -> bool:
        targets.append(Path(secret_file_path).name if secret_file_path else "<env file>")
        return write(data, secret_file_path=secret_file_path)

    manager.config_manager.batch_update_secrets.side_effect = targeting

    with pytest.raises(credentials.CredentialsWriteFailed, match=re.escape(names)):
        manager.setup_authelia_secrets("prod", auto_update=True)
    # The env file first; the hub file only once the env write succeeded.
    assert targets == (["<env file>"] if names == "prod.enc.yaml" else ["<env file>", "common.enc.yaml"])
    if names == "common.enc.yaml":
        assert any("argocd" in key for key in generated), "the hub values were not in the checked set"
    # Uptime Kuma's new password is in the env file once that write succeeds, so
    # the service is reconciled then, whatever happens to the hub write after it.
    assert bool(manager.reconciled) is (names == "common.enc.yaml"), manager.reconciled

    out = _flat("".join(capsys.readouterr()))
    assert not [v for v in _secret_values(generated) if _flat(v) in out], "a failed write printed a secret"


def test_the_cli_exits_non_zero_on_a_failed_write(monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from toolkit.cli import credentials as cli

    def fail(**_: Any) -> None:
        raise credentials.CredentialsWriteFailed("planted")

    monkeypatch.setattr(cli.credentials_manager, "setup_authelia_secrets", fail)
    run = CliRunner().invoke(cli.app, ["generate", "--env", "prod", "--auto-update"])
    assert run.exit_code == 1, run.output
    # The runner also reports 1 for an unhandled exception; the handler is what exits cleanly.
    assert isinstance(run.exception, SystemExit), run.exception
    assert "planted" in run.output


@pytest.mark.parametrize(("flag", "expected"), [([], False), (["--print-secrets"], True)])
def test_the_cli_forwards_print_secrets(monkeypatch: pytest.MonkeyPatch, flag: list[str], expected: bool) -> None:
    from typer.testing import CliRunner

    from toolkit.cli import credentials as cli

    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli.credentials_manager, "setup_authelia_secrets", lambda **kwargs: seen.update(kwargs))
    run = CliRunner().invoke(cli.app, ["generate", "--env", "prod", *flag])
    assert run.exit_code == 0, run.output
    assert seen.get("print_secrets") is expected, seen
