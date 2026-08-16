"""Backup pipeline commands (BACKUP-044)."""

from pathlib import Path
from typing import Annotated, Optional

import typer

from toolkit.core.logging import logger
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


@app.command("verify-restic")
def verify_restic_cmd(
    node: Annotated[
        str,
        typer.Option("--node", "-n", help="Repository name (one repository per node)"),
    ] = "_smoketest-probe",
    env: Annotated[str, typer.Option("--env", "-e", help="Environment whose merged config is used")] = "prod",
    keep: Annotated[bool, typer.Option("--keep", help="Do not delete the probe repository afterwards")] = False,
    project_root: Annotated[Optional[Path], typer.Option("--project-root", help="Repo root")] = None,
) -> None:
    """Prove restic can create, use and verify a repository in R2.

    Runs the whole lifecycle — init, backup, snapshots, `restic check` — against a
    throwaway repository, then removes it. "The bucket accepts objects" and
    "restic works here" are different claims; only the second one matters.
    """
    from toolkit.features.backup_destination import verify_restic

    if not verify_restic(node=node, env=env, project_root=project_root, keep=keep):
        raise typer.Exit(code=1)


@app.command("generate-password")
def generate_password_cmd(
    env: Annotated[str, typer.Option("--env", "-e", help="SOPS file to write to")] = "common",
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing password")] = False,
) -> None:
    """Generate the restic repository password and store it in SOPS.

    The value is never printed. Read it once with
    `make secrets-show KEY=backup.restic_password SECRETS_ENV=common` to place a
    copy in the offsite escrow — without that second copy the password is
    reachable only through an age key that a disaster destroys, which is the one
    scenario the backups exist for.

    Refuses to overwrite silently: replacing this value without running
    `restic key add` first locks you out of every existing snapshot.
    """
    import secrets as _secrets

    from toolkit.features.secrets_manager import SecretsManager

    key = "backup.restic_password"
    manager = SecretsManager()

    if manager.show_secret(env, key) and not force:
        logger.error(
            f"'{key}' already exists in {env}. Overwriting it locks you out of every existing "
            "snapshot unless `restic key add` ran first. Pass --force only if you mean it."
        )
        raise typer.Exit(code=1)

    if not manager.set_secret(env, key, _secrets.token_urlsafe(48)):
        logger.error(f"Failed to write '{key}' to {env}")
        raise typer.Exit(code=1)

    logger.success(f"Generated '{key}' in {env} (value not printed)")
    logger.warning("Copy it to the offsite escrow now: make secrets-show KEY=backup.restic_password SECRETS_ENV=common")
