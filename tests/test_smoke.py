"""Smoke tests: verify toolkit imports and CLI commands are registered."""

import pytest
from typer.testing import CliRunner

from toolkit.main import app

runner = CliRunner()

EXPECTED_COMMAND_GROUPS = [
    "config",
    "credentials",
    "dashboard",
    "deployment",
    "infra",
    "services",
    "tools",
]

EXPECTED_COMMANDS = [
    "version",
    "info",
]


class TestToolkitImport:
    """Verify core modules import without errors."""

    def test_import_toolkit(self) -> None:
        import toolkit

        assert hasattr(toolkit, "__version__")

    def test_import_main(self) -> None:
        from toolkit.main import app

        assert app is not None

    def test_import_settings(self) -> None:
        from toolkit.config.settings import settings

        assert settings.project_root is not None

    def test_import_constants(self) -> None:
        from toolkit.config import constants

        assert hasattr(constants, "PATH_STRUCTURES")


class TestCLIRegistered:
    """Verify all CLI command groups and commands are registered."""

    @staticmethod
    def _get_registered_names() -> dict[str, str]:
        """Return a mapping of registered command/group names to their types."""
        registered: dict[str, str] = {}
        if hasattr(app, "registered_groups"):
            for group in app.registered_groups:
                name = group.typer_instance.info.name or group.name
                registered[name] = "group"
        if hasattr(app, "registered_commands"):
            for cmd in app.registered_commands:
                if cmd.name:
                    registered[cmd.name] = "command"
                elif cmd.callback:
                    registered[cmd.callback.__name__] = "command"
        return registered

    @pytest.mark.parametrize("group", EXPECTED_COMMAND_GROUPS)
    def test_command_group_registered(self, group: str) -> None:
        registered = self._get_registered_names()
        assert group in registered, f"Command group '{group}' not registered. Found: {sorted(registered.keys())}"

    @pytest.mark.parametrize("command", EXPECTED_COMMANDS)
    def test_command_registered(self, command: str) -> None:
        registered = self._get_registered_names()
        assert command in registered, f"Command '{command}' not registered. Found: {sorted(registered.keys())}"


class TestCLIHelp:
    """Verify CLI responds to --help without errors."""

    def test_main_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Toolkit" in result.output

    def test_version_command(self) -> None:
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "Toolkit v" in result.output

    @pytest.mark.parametrize("group", EXPECTED_COMMAND_GROUPS)
    def test_group_help(self, group: str) -> None:
        result = runner.invoke(app, [group, "--help"])
        assert result.exit_code == 0, f"'{group} --help' failed: {result.output}"
