"""Main CLI application entry point."""

import inspect
from typing import Any

import typer
from typer import rich_utils

from toolkit import __version__
from toolkit.cli import (
    config,
    credentials,
    dashboard,
    deployment,
    infra,
    monitoring,
    secrets,
    services,
    tools,
)
from toolkit.config.settings import settings
from toolkit.core.logging import logger


def _patch_typer_help() -> None:
    """
    Monkey patch Typer/Rich to fix metavar display in help panels.

    This interacts with private APIs (_print_options_panel) and is brittle.
    If it fails, we silently swallow the error to prevent crashing the CLI,
    falling back to standard (unpatched) behavior.
    """
    try:
        if getattr(rich_utils, "_toolkit_patched_options_panel", False):
            return

        # Verify the target exists before patching
        if not hasattr(rich_utils, "_print_options_panel"):
            return

        original_print_options_panel = rich_utils._print_options_panel

        def patched_print_options_panel(
            *,
            name: str,
            params: list[Any],
            ctx: typer.Context,
            markup_mode: Any,
            console: Any,
        ) -> None:
            patched_methods: list[tuple[Any, Any]] = []

            try:
                for param in params:
                    make_metavar = getattr(param, "make_metavar", None)
                    if make_metavar is None:
                        continue

                    try:
                        param_count = len(inspect.signature(make_metavar).parameters)
                    except (ValueError, TypeError):
                        param_count = 0

                    if param_count == 0:
                        patched_methods.append((param, make_metavar))
                        param.make_metavar = lambda bound=make_metavar, context=ctx: bound(context)

                original_print_options_panel(
                    name=name,
                    params=params,
                    ctx=ctx,
                    markup_mode=markup_mode,
                    console=console,
                )
            finally:
                for param, original in patched_methods:
                    param.make_metavar = original

        rich_utils._print_options_panel = patched_print_options_panel  # type: ignore[assignment]
        rich_utils._toolkit_patched_options_panel = True  # type: ignore[attr-defined]
    except Exception:
        # If patching fails (e.g. library update changes internals), just ignore it.
        # The help text might look slightly less pretty, but the tool will work.
        pass


_patch_typer_help()


app = typer.Typer(
    name="toolkit",
    help="Toolkit - Unified infrastructure management tool.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main(_ctx: typer.Context) -> None:
    """Toolkit - Unified infrastructure management tool."""
    logger._setup_logging()


@app.command()
def version() -> None:
    """Show version and exit."""
    typer.echo(f"Toolkit v{__version__}")


@app.command()
def info() -> None:
    """Show toolkit information and configuration."""
    logger.info("Toolkit Information")
    logger.info(f"Version: {__version__}")
    logger.info(f"Python Version: {settings.python_version}")
    logger.info(f"Project Root: {settings.project_root}")
    logger.info(f"Default Environment: {settings.environment}")


app.add_typer(config.app, name="config")
app.add_typer(credentials.app, name="credentials")
app.add_typer(dashboard.app, name="dashboard")
app.add_typer(deployment.app, name="deployment")
app.add_typer(infra.app, name="infra")
app.add_typer(monitoring.app, name="monitoring")
app.add_typer(secrets.app, name="secrets")
app.add_typer(services.app, name="services")
app.add_typer(tools.app, name="tools")

if __name__ == "__main__":
    app()
