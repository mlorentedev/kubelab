"""Importing the toolkit reads no configuration and decrypts nothing (TOOL-097, #2021).

`settings` used to be built at import, so every command, `--help` included,
decrypted `common.enc.yaml` and `dev.enc.yaml` into its own `os.environ` before
parsing its arguments. A host meant to hold no secrets (ace2 running a drill
with `--inputs-stdin`) then printed SOPS warnings for a read it never needed.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_importing_the_cli_builds_no_configuration_manager() -> None:
    """A fresh interpreter, so no earlier test has already built settings."""
    script = textwrap.dedent(
        """
        import toolkit.features.configuration as c

        def refuse(*a, **k):
            raise AssertionError("ConfigurationManager built at import")

        c.ConfigurationManager.__init__ = refuse
        import toolkit.main  # noqa: F401
        print("imported")
        """
    )
    done = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and "imported" in done.stdout, done.stderr[-2000:]


def test_help_decrypts_nothing() -> None:
    """The whole process, not the invoke: patching after the import would miss a decrypt done at import."""
    script = textwrap.dedent(
        """
        import toolkit.features.configuration as c

        def refuse(*a, **k):
            raise AssertionError("SOPS decrypted by --help")

        c.ConfigurationManager._decrypt_sops = refuse
        from typer.testing import CliRunner
        from toolkit.main import app

        result = CliRunner().invoke(app, ["--help"])
        print("exit", result.exit_code)
        """
    )
    done = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and "exit 0" in done.stdout, (done.stdout + done.stderr)[-2000:]


def test_settings_still_resolve_on_first_use(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lazy, not absent: the first attribute read builds the same object `get_settings()` returns."""
    from toolkit.config.settings import PROJECT_ROOT, get_settings, settings

    assert settings.project_root == PROJECT_ROOT
    assert settings.environment == get_settings().environment


@pytest.fixture
def logger_state():
    """The process-wide logger, restored after the test reconfigures it."""
    from toolkit.core.logging import logger

    level = logger.logger.level
    formats = [h.formatter for h in logger.logger.handlers]
    yield logger
    logger.logger.setLevel(level)
    for handler, fmt in zip(logger.logger.handlers, formats, strict=True):
        handler.setFormatter(fmt)


def _fake_config(monkeypatch: pytest.MonkeyPatch, values: dict) -> None:
    import toolkit.config.settings as settings_module
    from toolkit.features import configuration

    class Fake:
        def __init__(self, env, root=None):
            self.env = env

        def get_env_vars(self):
            return dict(values[self.env])

    monkeypatch.setattr(configuration, "ConfigurationManager", Fake)
    monkeypatch.setattr(settings_module, "_settings_cache", {})
    # get_settings() writes these into os.environ; registering them first makes teardown undo it.
    for key in {k for env_values in values.values() for k in env_values}:
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key)


def test_the_logger_takes_the_import_environments_level_and_format(monkeypatch, logger_state) -> None:
    """What building settings at import used to do, now done when they are first built."""
    import logging

    import toolkit.config.settings as settings_module

    env = settings_module._IMPORT_ENV
    other = "prod" if env != "prod" else "staging"
    _fake_config(
        monkeypatch,
        {
            env: {"log_level": "WARNING", "log_format": "drill %(message)s"},
            other: {"log_level": "ERROR", "log_format": "%(message)s"},
        },
    )
    logger_state.logger.setLevel(logging.INFO)

    settings_module.get_settings(other)  # another environment leaves the logger alone
    assert logger_state.logger.level == logging.INFO

    settings_module.get_settings(env)
    assert logger_state.logger.level == logging.WARNING
    assert all(h.formatter._fmt == "drill %(message)s" for h in logger_state.logger.handlers)
