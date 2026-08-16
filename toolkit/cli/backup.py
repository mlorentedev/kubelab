"""Backup pipeline commands (BACKUP-044)."""

from pathlib import Path
from typing import Annotated, Optional

import typer

from toolkit.features.backup_destination import verify_destination

app = typer.Typer(
    name="backup",
    help="Offsite backup pipeline (Cloudflare R2 / restic).",
    no_args_is_help=True,
)


@app.command("verify-destination")
def verify_destination_cmd(
    env: Annotated[
        str,
        typer.Option("--env", "-e", help="Environment whose merged config is used"),
    ] = "prod",
    project_root: Annotated[
        Optional[Path],
        typer.Option("--project-root", help="Repo root (defaults to auto-detection)"),
    ] = None,
) -> None:
    """Prove the R2 destination is usable: scope, reach, and a write/read/delete round-trip.

    Writes 1 KB of throwaway data under `_smoketest/` and removes it. Safe to run
    against a live destination, and worth running before trusting a backup to it —
    a token without delete permission lets backups look healthy until the bucket
    fills and retention turns out never to have retained anything.
    """
    if not verify_destination(env=env, project_root=project_root):
        raise typer.Exit(code=1)
