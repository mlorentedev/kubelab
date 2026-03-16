"Monitoring management commands for Uptime Kuma backup and status."

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from toolkit.config.constants import MESSAGES
from toolkit.config.settings import get_settings
from toolkit.core.logging import console, logger
from toolkit.features import command

app = typer.Typer(
    name="monitoring",
    help="Uptime Kuma monitoring: backup, restore, and status",
    no_args_is_help=True,
)

# Uptime Kuma runs on RPi3 (kubelab-rpi3) via Tailscale
_KUMA_HOST = "100.64.0.6"
_KUMA_SSH_USER = "manu"
_KUMA_CONTAINER = "uptime-kuma"
_KUMA_DB_PATH_IN_CONTAINER = "/app/data/kuma.db"
_KUMA_BACKUP_DIR = "infra/config/uptime-kuma"
_KUMA_URL = f"http://{_KUMA_HOST}:3001"


def _ssh_cmd(cmd: str) -> str:
    """Build SSH command to RPi3."""
    return f"ssh -o ConnectTimeout=5 {_KUMA_SSH_USER}@{_KUMA_HOST} {cmd!r}"


def _backup_dir(project_root: Path) -> Path:
    """Get the local backup directory path."""
    return project_root / _KUMA_BACKUP_DIR


@app.command("backup")
def backup(
    output: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Custom output filename (default: kuma.db)"),
    ] = None,
) -> None:
    """Pull Uptime Kuma database from RPi3 to local repo.

    Extracts kuma.db from the running container via docker cp,
    then copies it to infra/config/uptime-kuma/ via scp.
    """
    settings = get_settings()
    backup_path = _backup_dir(settings.project_root)
    filename = output or "kuma.db"
    local_file = backup_path / filename

    logger.section("Uptime Kuma Backup")

    # 1. Check RPi3 reachability
    logger.info(f"Connecting to RPi3 ({_KUMA_HOST})...")
    ping = command.run(f"ping -c1 -W2 {_KUMA_HOST}", check=False)
    if ping.returncode != 0:
        logger.error(f"RPi3 unreachable at {_KUMA_HOST}. Is Tailscale connected?")
        raise typer.Exit(1)

    # 2. Extract DB from container to RPi3 /tmp
    logger.info("Extracting kuma.db from container...")
    extract = command.run(
        _ssh_cmd(f"docker cp {_KUMA_CONTAINER}:{_KUMA_DB_PATH_IN_CONTAINER} /tmp/kuma.db"),
        check=False,
    )
    if extract.returncode != 0:
        logger.error(f"Failed to extract DB: {extract.stderr}")
        raise typer.Exit(1)

    # 3. Copy to local workstation
    logger.info(f"Copying to {local_file}...")
    backup_path.mkdir(parents=True, exist_ok=True)
    scp = command.run(
        f"scp -o ConnectTimeout=5 {_KUMA_SSH_USER}@{_KUMA_HOST}:/tmp/kuma.db {local_file}",
        check=False,
    )
    if scp.returncode != 0:
        logger.error(f"SCP failed: {scp.stderr}")
        raise typer.Exit(1)

    # 4. Cleanup remote temp file
    command.run(_ssh_cmd("rm -f /tmp/kuma.db"), check=False)

    # 5. Show file info
    size_kb = local_file.stat().st_size / 1024
    logger.success(f"Backup saved: {local_file} ({size_kb:.0f} KB)")
    logger.info("Commit this file to Git as a restore point when monitors change significantly.")


@app.command("restore")
def restore(
    input_file: Annotated[
        str | None,
        typer.Option("--input", "-i", help="Path to kuma.db file (default: infra/config/uptime-kuma/kuma.db)"),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation prompt"),
    ] = False,
) -> None:
    """Push a local kuma.db backup to RPi3 and restart Uptime Kuma.

    This overwrites the running database. Use with caution.
    """
    settings = get_settings()
    backup_path = _backup_dir(settings.project_root)
    local_file = Path(input_file) if input_file else backup_path / "kuma.db"

    logger.section("Uptime Kuma Restore")

    if not local_file.exists():
        logger.error(f"Backup file not found: {local_file}")
        raise typer.Exit(1)

    size_kb = local_file.stat().st_size / 1024
    logger.warning(f"This will overwrite the running Uptime Kuma database with {local_file} ({size_kb:.0f} KB)")

    if not force and not logger.confirm("Are you sure?", default=False):
        logger.info(MESSAGES.WARNING_CANCELLED)
        raise typer.Exit(0)

    # 1. Check connectivity
    logger.info(f"Connecting to RPi3 ({_KUMA_HOST})...")
    ping = command.run(f"ping -c1 -W2 {_KUMA_HOST}", check=False)
    if ping.returncode != 0:
        logger.error(f"RPi3 unreachable at {_KUMA_HOST}")
        raise typer.Exit(1)

    # 2. Upload DB to RPi3
    logger.info("Uploading kuma.db to RPi3...")
    scp = command.run(
        f"scp -o ConnectTimeout=5 {local_file} {_KUMA_SSH_USER}@{_KUMA_HOST}:/tmp/kuma-restore.db",
        check=False,
    )
    if scp.returncode != 0:
        logger.error(f"Upload failed: {scp.stderr}")
        raise typer.Exit(1)

    # 3. Stop container, replace DB, start container
    logger.info("Stopping Uptime Kuma...")
    command.run(_ssh_cmd("cd ~/uptime-kuma && docker compose down"), check=False)

    logger.info("Replacing database...")
    command.run(
        _ssh_cmd(
            "docker run --rm "
            "-v uptime-kuma_uptime_kuma_data:/data "
            "-v /tmp:/backup "
            "alpine sh -c 'cp /backup/kuma-restore.db /data/kuma.db'"
        ),
        check=False,
    )

    logger.info("Starting Uptime Kuma...")
    start = command.run(_ssh_cmd("cd ~/uptime-kuma && docker compose up -d"), check=False)

    # 4. Cleanup
    command.run(_ssh_cmd("rm -f /tmp/kuma-restore.db"), check=False)

    if start.returncode == 0:
        logger.success(f"Uptime Kuma restored from {local_file}")
        logger.info(f"Verify at {_KUMA_URL}")
    else:
        logger.error("Failed to restart Uptime Kuma after restore")
        raise typer.Exit(1)


@app.command("status")
def status() -> None:
    """Check Uptime Kuma connectivity and container status on RPi3."""
    logger.section("Uptime Kuma Status")

    # 1. Ping RPi3
    logger.info(f"Pinging RPi3 ({_KUMA_HOST})...")
    ping = command.run(f"ping -c1 -W2 {_KUMA_HOST}", check=False)
    if ping.returncode != 0:
        logger.error(f"RPi3 unreachable at {_KUMA_HOST}")
        raise typer.Exit(1)
    logger.success("RPi3 reachable via Tailscale")

    # 2. Check container
    logger.info("Checking container status...")
    container = command.run(
        _ssh_cmd(f"docker inspect {_KUMA_CONTAINER} --format '{{{{.State.Status}}}}'"),
        check=False,
    )
    container_status = container.stdout.strip() if container.returncode == 0 else "not found"

    # 3. Check HTTP
    logger.info("Checking HTTP endpoint...")
    http = command.run(
        f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 5 {_KUMA_URL}",
        check=False,
    )
    http_code = http.stdout.strip() if http.returncode == 0 else "timeout"

    # 4. Get container uptime
    started_at = "unknown"
    if container_status == "running":
        uptime = command.run(
            _ssh_cmd(f"docker inspect {_KUMA_CONTAINER} --format '{{{{.State.StartedAt}}}}'"),
            check=False,
        )
        started_at = uptime.stdout.strip()[:19] if uptime.returncode == 0 else "unknown"

    # 5. Display results
    table = Table(title="Uptime Kuma Status")
    table.add_column("Check", style="cyan")
    table.add_column("Result", justify="center")
    table.add_column("Detail")

    ping_ok = ping.returncode == 0
    table.add_row(
        "RPi3 Tailscale",
        "[green]OK[/green]" if ping_ok else "[red]FAIL[/red]",
        _KUMA_HOST,
    )

    container_ok = container_status == "running"
    table.add_row(
        "Container",
        "[green]OK[/green]" if container_ok else "[red]FAIL[/red]",
        container_status,
    )

    http_ok = http_code in ("200", "301", "302")
    table.add_row(
        "HTTP",
        "[green]OK[/green]" if http_ok else "[red]FAIL[/red]",
        f"HTTP {http_code}",
    )

    if container_ok:
        table.add_row("Started", "[dim]--[/dim]", started_at)

    console.print(table)

    if not all([ping_ok, container_ok, http_ok]):
        raise typer.Exit(1)
