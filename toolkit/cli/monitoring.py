"Monitoring management commands for Uptime Kuma: status and config-as-code."

import typer
from rich.table import Table

from toolkit.config.settings import get_settings
from toolkit.core.logging import console, logger
from toolkit.features import command
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.monitoring import apply_monitors, export_monitors, import_monitors
from toolkit.features.monitoring import bootstrap as bootstrap_fn

app = typer.Typer(
    name="monitoring",
    help="Uptime Kuma monitoring: status and config-as-code (backup is node_backup)",
    no_args_is_help=True,
)

# Cached config loaded lazily from common.yaml (SSOT)
_kuma_config: dict[str, str] | None = None


def _get_kuma_config() -> dict[str, str]:
    """Load Uptime Kuma connection details from config (networking.nodes.rpi3 + apps.services)."""
    global _kuma_config
    if _kuma_config is not None:
        return _kuma_config

    settings = get_settings()
    # Node data lives in common.yaml — env doesn't matter for this lookup
    config_manager = ConfigurationManager("staging", settings.project_root)
    merged = config_manager.get_merged_config()

    networking = merged.get("networking", {})
    node = networking.get("nodes", {}).get("rpi3", {})
    svc = merged.get("apps", {}).get("services", {}).get("observability", {}).get("uptime_kuma", {})

    host = node.get("tailscale_ip", "")
    if not host:
        logger.error("networking.nodes.rpi3.tailscale_ip not found in config")
        raise typer.Exit(1)

    port = str(svc.get("default_port", "3001"))

    _kuma_config = {
        "host": host,
        # SSOT-014a: read from networking.ssh_users.homelab, fall back to per-node override.
        "ssh_user": node.get("ssh_user") or networking["ssh_users"]["homelab"],
        "container": svc.get("name", "uptime-kuma"),
        "url": f"http://{host}:{port}",
    }
    return _kuma_config


def _ssh_cmd(cmd: str) -> str:
    """Build SSH command to RPi3."""
    cfg = _get_kuma_config()
    return f"ssh -o ConnectTimeout=5 {cfg['ssh_user']}@{cfg['host']} {cmd!r}"


@app.command("status")
def status() -> None:
    """Check Uptime Kuma connectivity and container status on RPi3."""
    cfg = _get_kuma_config()
    logger.section("Uptime Kuma Status")

    # 1. Ping RPi3
    logger.info(f"Pinging RPi3 ({cfg['host']})...")
    ping = command.run(f"ping -c1 -W2 {cfg['host']}", check=False)
    if ping.returncode != 0:
        logger.error(f"RPi3 unreachable at {cfg['host']}")
        raise typer.Exit(1)
    logger.success("RPi3 reachable via Tailscale")

    # 2. Check container
    logger.info("Checking container status...")
    container = command.run(
        _ssh_cmd(f"docker inspect {cfg['container']} --format '{{{{.State.Status}}}}'"),
        check=False,
    )
    container_status = container.stdout.strip() if container.returncode == 0 else "not found"

    # 3. Check HTTP
    logger.info("Checking HTTP endpoint...")
    http = command.run(
        f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 5 {cfg['url']}",
        check=False,
    )
    http_code = http.stdout.strip() if http.returncode == 0 else "timeout"

    # 4. Get container uptime
    started_at = "unknown"
    if container_status == "running":
        uptime = command.run(
            _ssh_cmd(f"docker inspect {cfg['container']} --format '{{{{.State.StartedAt}}}}'"),
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
        cfg["host"],
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


@app.command("export")
def export_cmd() -> None:
    """Export monitors and notifications to JSON (config-as-code).

    Connects to Uptime Kuma via API, exports all monitors and notifications
    to infra/config/uptime-kuma/{monitors,notifications}.json.
    Requires admin_password in SOPS: apps.services.observability.uptime_kuma.admin_password
    """
    settings = get_settings()
    export_monitors(settings.project_root)


@app.command("import")
def import_cmd() -> None:
    """Import monitors from JSON seed files into Uptime Kuma.

    Reads from infra/config/uptime-kuma/monitors.json and applies to
    the running instance. Existing monitors with same name are skipped.
    """
    settings = get_settings()
    import_monitors(settings.project_root)


@app.command("apply")
def apply_cmd(
    check: bool = typer.Option(False, "--check", help="Print the sync plan and write nothing."),
    prune: bool = typer.Option(False, "--prune", help="Delete live monitors the seed does not declare."),
) -> None:
    """Declarative sync: apply monitors from seed JSON to Uptime Kuma.

    Converges the live instance onto the seed by UPSERTING. Monitors are matched
    on an immutable `key` carried in the description, so a rename is an edit and
    **uptime history survives a sync**. A live monitor matching no seed entry is
    removed, because the seed is the source of truth.

    This said "deletes all existing monitors and recreates from seed" until
    2026-09-02, describing behaviour OPS-016 replaced with the diff in
    `monitoring_diff.compute_sync_plan`. The error mattered in the direction that
    stops people: an operator reading it concludes a routine sync costs every
    monitor's history and reaches for the Kuma UI instead, which is how a
    config-as-code file drifts from the instance it is supposed to describe.
    """
    settings = get_settings()
    apply_monitors(settings.project_root, check=check, prune=prune)


@app.command("bootstrap")
def bootstrap_cmd() -> None:
    """Full disaster recovery: create admin user + import monitors.

    For fresh Uptime Kuma instances (new SD card). Creates admin user
    from SOPS credentials, then imports monitors + notifications from
    JSON seed files. Idempotent — safe to re-run.
    """
    settings = get_settings()
    bootstrap_fn(settings.project_root)
