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
from typer.testing import CliRunner

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


def test_help_decrypts_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    import toolkit.config.settings as settings_module
    from toolkit.features import configuration
    from toolkit.main import app

    monkeypatch.setattr(settings_module, "_settings_cache", {})

    def refuse(*a, **k):
        raise AssertionError("SOPS decrypted by --help")

    monkeypatch.setattr(configuration.ConfigurationManager, "_decrypt_sops", refuse)
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0, result.output


def test_settings_still_resolve_on_first_use(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lazy, not absent: the first attribute read builds the same object `get_settings()` returns."""
    from toolkit.config.settings import PROJECT_ROOT, get_settings, settings

    assert settings.project_root == PROJECT_ROOT
    assert settings.environment == get_settings().environment
