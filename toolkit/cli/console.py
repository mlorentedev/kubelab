"""Forge console commands (CONSOLE-004)."""

from __future__ import annotations

from typing import Annotated

import typer

from toolkit.core.logging import logger

app = typer.Typer(name="console", help="Forge console: read what the console records.", no_args_is_help=True)


@app.command("usage")
def usage_cmd(
    env: Annotated[str, typer.Option("--env", "-e", help="Environment whose console is read")] = "prod",
) -> None:
    """Report the A8 usage gate: days the console was opened, in the best 14-day window.

    Read-only: one SELECT in a READ ONLY transaction. Prints identities and dates only.
    Exits 1 when the counter cannot be read, never reporting that as no use.
    """
    from toolkit.config.settings import get_settings
    from toolkit.features.configuration import ConfigurationManager
    from toolkit.features.console_usage import ReadError, report
    from toolkit.features.k8s_kubeconfig import output_path

    merged = ConfigurationManager(env, get_settings().project_root).get_merged_config()
    database = merged["apps"]["platform"]["api"]["postgres_tenant"]
    try:
        lines = report(env, kubeconfig=str(output_path(env)), database=database)
    except ReadError as exc:
        logger.error(str(exc))
        raise typer.Exit(1) from exc
    for line in lines:
        typer.echo(line)
