"""Terminal Dashboard for monitoring the stack status."""

import time
from datetime import datetime
from typing import Annotated, Any, Dict, List

import typer
from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from toolkit.config.settings import PROJECT_ROOT, get_settings, settings
from toolkit.features import command
from toolkit.features.configuration import (
    ConfigurationManager,
)  # Import ConfigurationManager

app = typer.Typer(
    name="dashboard",
    help="Interactive terminal dashboard.",
    no_args_is_help=False,
)


def _get_docker_status() -> List[Dict[str, str]]:
    """Fetch running containers status, filtered by project."""
    # Format: Names|Status|State|Ports
    # Filter by network to capture all project-related containers
    result = command.run(
        f'docker ps -a --filter "network={settings.docker_network}" '
        f"--format '{{{{.Names}}}}|{{{{.Status}}}}|{{{{.State}}}}|{{{{.Ports}}}}'",
        check=False,
        capture_output=True,
    )

    containers = []
    if result.returncode == 0 and result.stdout.strip():
        for line in result.stdout.strip().split("\n"):
            try:
                parts = line.split("|")
                if len(parts) >= 3:
                    containers.append(
                        {
                            "name": parts[0].replace(f"{settings.project_name}-", ""),  # Clean name
                            "status": parts[1],
                            "state": parts[2],  # running, exited, etc.
                            "ports": parts[3] if len(parts) > 3 else "",
                        }
                    )
            except Exception:
                continue
    return containers


def _generate_services_table(env: str, containers: List[Dict[str, str]]) -> Table:
    """Generate the services status table."""
    table = Table(expand=True, box=box.ROUNDED, title=f"Containers ({env})")
    table.add_column("Service", style="cyan")
    table.add_column("Status", style="white")
    table.add_column("State", justify="center")

    # Sort by name
    containers.sort(key=lambda x: x["name"])

    if not containers:
        table.add_row("No project containers found", "-", "stopped")
        return table

    for c in containers:
        state_style = "green" if c["state"] == "running" else "red"
        state_icon = "●" if c["state"] == "running" else "○"

        status_text = c["status"]

        table.add_row(
            c["name"],
            status_text,
            Text(f" {state_icon} {c['state']} ", style=f"bold {state_style} reverse"),
        )

    return table


def _generate_info_panel(env: str, containers: List[Dict[str, str]]) -> Panel:
    """Generate the information panel with dynamically loaded URLs for running services."""
    env_settings = get_settings(env)

    urls = []

    # Get raw configuration from ConfigurationManager to access nested structure
    config_manager = ConfigurationManager(env, PROJECT_ROOT)
    raw_config = config_manager.get_merged_config()  # This should return nested dict

    # Helper to check if a container is running
    def is_container_running(container_name: str) -> bool:
        for c in containers:
            if c["name"] == container_name and c["state"] == "running":
                return True
        return False

    # Helper to process a dict of apps/services
    def process_components(components_dict: Dict[str, Any], prefix: str = "") -> None:
        for comp_name, comp_config in components_dict.items():
            if isinstance(comp_config, dict) and "domain" in comp_config:
                # Special handling for uptime-kuma due to name vs dir
                clean_comp_name = comp_name.replace("_", "-")
                if is_container_running(clean_comp_name):
                    domain = comp_config["domain"]
                    protocol = env_settings.protocol  # Use env_settings.protocol
                    health_path = comp_config.get("health_path", "/")

                    # Fix for localhost/dev environments: Append port if domain is
                    # localhost/127.0.0.1. In dev, domains like 'blog.kubelab.test'
                    # resolve to 127.0.0.1 via /etc/hosts or DNS. But if we are
                    # accessing them directly without a reverse proxy on port 80/443
                    # (which might be the case if Traefik is not exposing them there,
                    # or we want direct access). However, the user says "incomplete".
                    # If domain is "blog.kubelab.test", and protocol is https,
                    # it becomes https://blog.kubelab.test. If Traefik is running
                    # on 80/443, this is correct. But maybe Traefik is on a
                    # different port? Let's check Traefik config.

                    # Actually, for the specific "dev" environment in the provided values/dev.yaml:
                    # Traefik has domain "traefik.kubelab.test".
                    # And `endpoints` section in dev.yaml shows:
                    # api: http://api:8080
                    # web: http://web:4321
                    # blog: http://blog:4000
                    # wiki: http://wiki:8000

                    # The `endpoints` section seems to be for internal service discovery.
                    # The `apps` section has `domain`.

                    # If the user sees "incomplete" links, it might be that `domain` is None or empty?
                    # Or maybe the protocol is missing? (handled by f-string)

                    # Let's fallback to localhost:port if domain is not set or if
                    # we are in a mode where we prefer ports. But the config seems
                    # to have domains.

                    # If the user says "endpoints are incomplete", and the dashboard
                    # showed "No active service endpoints found", it was because
                    # `is_container_running` was false. Now that we fixed
                    # `docker ps`, `is_container_running` should be true. So the
                    # links should appear now.

                    # However, if the user *still* thinks they will be incomplete
                    # (maybe predicting based on "Quick Links" title?), or if the
                    # `domain` variable in the config is somehow not what we expect.

                    # Wait, looking at dev.yaml:
                    # apps.platform.api.domain = "api.kubelab.test"
                    # apps.platform.web.domain = "web.kubelab.test"

                    # If I assume the user simply hasn't seen the links yet because of the docker ps bug,
                    # then fixing docker ps might be enough.
                    # But the user asked "The quicklinks are wrong, missing info?".
                    # This implies they *saw* them, or saw something.
                    # Ah, in the previous output, the "Quick Links" panel was empty:
                    # "No active service endpoints found."

                    # So the user might be confusing "No active service endpoints found" with "incomplete info".
                    # OR, the user saw the code/logic and thinks it's missing something.

                    # But let's look at `_generate_info_panel` again.
                    # It iterates `raw_config['apps']['platform']`.
                    # In `dev.yaml`, `apps` has `platform` and `services`.

                    # If I simply return the correct URL based on config, it should be fine.
                    # The issue might be that for local dev, if Traefik isn't routing these domains to the containers,
                    # the user might expect `localhost:port`.

                    # But `dev.yaml` sets `domain: blog.kubelab.test`.
                    # And `traefik` in `dev.yaml` has `domain: traefik.kubelab.test`.

                    # If I want to be safe, I can check if `default_port` is
                    # available and `base_domain` includes "localhost" (or "test"
                    # if that's the local convention). But sticking to the
                    # configured domain is cleaner if the environment is set up
                    # correctly (hosts file).

                    # Let's assume the "incomplete" comment was about the empty list.
                    # But wait, the user said "Quick links are wrong, not capturing full endpoint".
                    # Maybe they mean `http://api` instead of `http://api.kubelab.test`?
                    # In `dev.yaml`, `apps.platform.api.domain` is `api.kubelab.test`.

                    # Let's look at `toolkit/cli/dashboard.py` logic again:
                    # domain = comp_config['domain']
                    # This is a direct dict access.

                    # If `comp_config` comes from `ConfigurationManager.get_merged_config()`,
                    # let's verify if `domain` is correctly populated.

                    # I will refrain from changing logic blindly.
                    # But I will update the code to handle the case where `domain` might be missing gracefully,
                    # and ensuring we use the right keys.

                    display_name = comp_name.replace("_", " ").title()

                    # Special path for API health
                    if comp_name == "api" and prefix == "platform":
                        health_path = "/health"

                    # Special handling for Traefik dashboard link
                    if comp_name == "traefik" and prefix == "services-core":
                        urls.append(
                            (
                                f"{display_name} Dashboard",
                                f"{protocol}://{domain}/dashboard",
                            )
                        )

                    urls.append((display_name, f"{protocol}://{domain}{health_path}"))
            elif isinstance(comp_config, dict):
                process_components(comp_config, f"{prefix}-{comp_name}" if prefix else comp_name)

    if "apps" in raw_config:
        if "platform" in raw_config["apps"]:
            process_components(raw_config["apps"]["platform"], "platform")
        if "services" in raw_config["apps"]:
            process_components(raw_config["apps"]["services"], "services")

    # Also add the main Traefik instance from edge, if it's running
    if "edge" in raw_config and "traefik" in raw_config["edge"]:
        if is_container_running("traefik"):  # Check main traefik container
            traefik_domain = raw_config["edge"]["traefik"].get("domain", env_settings.base_domain)
            protocol = env_settings.protocol  # Use env_settings.protocol
            urls.append(("Traefik (Proxy)", f"{protocol}://{traefik_domain}"))
            urls.append(("Traefik Dashboard", f"{protocol}://{traefik_domain}/dashboard"))

    # Sort for consistent display
    urls = sorted(list(set(urls)))  # Remove duplicates and sort

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold yellow")
    grid.add_column(style="blue underline")

    if not urls:
        grid.add_row("No active service endpoints found.", "")

    for name, url in urls:
        grid.add_row(f"{name}:", url)

    return Panel(
        grid,
        title=f"Quick Links ({env_settings.base_domain})",
        border_style="blue",
        box=box.ROUNDED,
    )


def _generate_header(env: str, is_watching: bool, refresh_interval: float) -> Panel:
    """Generate the dashboard header."""
    grid = Table.grid(expand=True)
    grid.add_column(justify="left", ratio=1)
    grid.add_column(justify="right", ratio=1)

    watch_status = f"Watching (every {refresh_interval}s)" if is_watching else "Static Snapshot"

    grid.add_row(
        f"[b]Toolkit Dashboard[/b] | Env: [cyan]{env}[/cyan] | Status: {watch_status}",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    return Panel(grid, style="white on blue", box=box.HEAVY_HEAD)


@app.callback(invoke_without_command=True)
def run_dashboard(
    ctx: typer.Context,
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")] = "dev",
    watch: Annotated[bool, typer.Option("--watch", "-w", help="Enable auto-refresh mode")] = False,
    interval: Annotated[
        float,
        typer.Option("--interval", "-i", help="Refresh interval in seconds (only with --watch)"),
    ] = 1.0,  # Default to 1 second
) -> None:
    """
    Display an interactive terminal dashboard or a static snapshot of the stack.
    """
    if ctx.invoked_subcommand:
        return

    # Initialize settings for the chosen environment
    # This also validates the environment
    get_settings(env)

    layout = Layout()
    layout.split(
        Layout(name="header", size=3),
        Layout(name="body", ratio=1),
    )
    layout["body"].split_row(
        Layout(name="services", ratio=2),
        Layout(name="info", ratio=1),
    )

    def update_layout_content() -> None:
        containers = _get_docker_status()  # Fetch once per update cycle
        layout["header"].update(_generate_header(env, watch, interval))
        layout["services"].update(_generate_services_table(env, containers))
        layout["info"].update(_generate_info_panel(env, containers))

    try:
        if watch:
            # Refresh rich.Live faster, but docker command still takes time
            # Increased rich refresh rate
            with Live(layout, screen=True, refresh_per_second=24):
                while True:
                    update_layout_content()
                    time.sleep(interval)
        else:
            # Static snapshot
            update_layout_content()
            console = Console()
            console.print(layout)  # Print once

    except KeyboardInterrupt:
        pass
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e
