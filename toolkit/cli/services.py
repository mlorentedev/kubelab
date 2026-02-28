"Service and application management commands."

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from toolkit.config.constants import MESSAGES, PATH_STRUCTURES
from toolkit.config.settings import PlatformSettings, get_settings
from toolkit.core.logging import logger
from toolkit.features import command
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.docker_service import DockerService

console = Console()
app = typer.Typer(help="Manage services and applications")


def _discover_all_components(settings: PlatformSettings) -> list[str]:
    """Discover all components that have compose files."""
    components: list[str] = []

    # Apps
    apps_dir = settings.project_root / PATH_STRUCTURES.INFRA_STACKS_APPS
    if apps_dir.exists():
        for d in sorted(apps_dir.iterdir()):
            if d.is_dir() and (d / "compose.base.yml").exists():
                components.append(d.name)

    # Services (by category)
    services_dir = settings.project_root / PATH_STRUCTURES.INFRA_STACKS_SERVICES
    if services_dir.exists():
        for category in sorted(services_dir.iterdir()):
            if category.is_dir():
                for d in sorted(category.iterdir()):
                    if d.is_dir() and (d / "compose.base.yml").exists():
                        components.append(d.name)

    # Edge
    edge_dir = settings.project_root / PATH_STRUCTURES.EDGE_DIR
    if edge_dir.exists():
        for d in sorted(edge_dir.iterdir()):
            if d.is_dir() and (d / "compose.base.yml").exists():
                components.append(d.name)

    return components


@app.command("up")
def start_service(
    component_names: Annotated[
        list[str] | None,
        typer.Argument(help="Name(s) of the service(s)/app(s) to start"),
    ] = None,
    all_components: bool = typer.Option(False, "--all", "-a", help="Start all components"),
    environment: str = typer.Option("dev", "--env", "-e", help="Environment to use"),
) -> None:
    """Start one or more services or applications."""
    settings = get_settings(environment)
    service = DockerService(settings)

    names = _discover_all_components(settings) if all_components else (component_names or [])
    if not names:
        logger.error("Specify component name(s) or use --all")
        raise typer.Exit(1)

    for name in names:
        service.start_component(name, environment)


@app.command("down")
def stop_service(
    component_names: Annotated[
        list[str] | None,
        typer.Argument(help="Name(s) of the service(s)/app(s) to stop"),
    ] = None,
    all_components: bool = typer.Option(False, "--all", "-a", help="Stop all components"),
    environment: str = typer.Option("dev", "--env", "-e", help="Environment to use"),
    volumes: bool = typer.Option(False, "--volumes", "-v", help="Remove volumes"),
) -> None:
    """Stop one or more services or applications."""
    settings = get_settings(environment)
    service = DockerService(settings)

    names = _discover_all_components(settings) if all_components else (component_names or [])
    if not names:
        logger.error("Specify component name(s) or use --all")
        raise typer.Exit(1)

    for name in names:
        service.stop_component(name, environment, volumes=volumes)


@app.command("restart")
def restart_service(
    component_names: Annotated[list[str], typer.Argument(help="Name(s) of the service(s)/app(s) to restart")],
    environment: str = typer.Option("dev", "--env", "-e", help="Environment to use"),
    volumes: bool = typer.Option(False, "--volumes", "-v", help="Remove volumes on stop"),
) -> None:
    """Restart one or more services or applications (down + up)."""
    settings = get_settings(environment)
    service = DockerService(settings)

    for name in component_names:
        logger.info(f"Restarting {name} service")
        service.stop_component(name, environment, volumes=volumes)
        service.start_component(name, environment)


@app.command("logs")
def show_logs(
    component_names: Annotated[list[str], typer.Argument(help="Name(s) of the service(s)/app(s)")],
    environment: str = typer.Option("dev", "--env", "-e", help="Environment to use"),
    follow: bool = typer.Option(
        False,
        "--follow/--no-follow",
        "-f",
        help="Follow log output",
    ),
) -> None:
    """Show logs for one or more services or applications."""
    settings = get_settings(environment)
    service = DockerService(settings)
    for name in component_names:
        service.show_component_logs(name, environment, follow)


@app.command("build")
def build_app(
    app_name: str = typer.Argument(..., help="Name of the application to build"),
    environment: str = typer.Option("dev", "--env", "-e", help="Environment to build for"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Build without using cache"),
) -> None:
    """Build application using docker compose."""
    settings = get_settings(environment)
    service = DockerService(settings)
    service.build_app(app_name, environment, no_cache=no_cache)


@app.command("clean")
def clean_app(
    app_name: str = typer.Argument(..., help="Name of the application to clean"),
    environment: str = typer.Option("dev", "--env", "-e", help="Environment to use"),
) -> None:
    """Clean application artifacts and resources."""
    settings = get_settings(environment)
    service = DockerService(settings)
    service.clean_app(app_name, environment)


@app.command("push")
def push_image(
    app_name: str = typer.Argument(..., help="Name of the application"),
    environment: str = typer.Option("dev", "--env", "-e", help="Environment tag for image"),
) -> None:
    """Push Docker image for an application to registry."""
    settings = get_settings(environment)
    service = DockerService(settings)
    service.push_app_image(app_name, environment)


@app.command("list")
def list_components() -> None:
    """List all available services and applications."""
    logger.info(MESSAGES.INFO_AVAILABLE_COMPONENTS)
    settings = get_settings()
    components: dict[str, list[str]] = {}

    # List Apps
    apps_dir = settings.project_root / PATH_STRUCTURES.APPS_DIR
    if apps_dir.exists():
        components["apps"] = []
        for app_dir in apps_dir.iterdir():
            if app_dir.is_dir() and not app_dir.name.startswith("."):
                components["apps"].append(app_dir.name)

    # List Services
    services_base = settings.project_root / PATH_STRUCTURES.INFRA_STACKS_SERVICES
    if services_base.exists():
        for category_dir in services_base.iterdir():
            if category_dir.is_dir() and not category_dir.name.startswith("."):
                category_name = f"services/{category_dir.name}"
                components[category_name] = []
                for service_dir in category_dir.iterdir():
                    if service_dir.is_dir() and not service_dir.name.startswith("."):
                        components[category_name].append(service_dir.name)

    # List Edge
    edge_path = settings.project_root / PATH_STRUCTURES.EDGE_DIR
    if edge_path.exists():
        components["edge"] = []
        for service_dir in edge_path.iterdir():
            if service_dir.is_dir() and not service_dir.name.startswith("."):
                components["edge"].append(service_dir.name)

    logger.section("Available Components")
    for category in sorted(components.keys()):
        logger.info(f"[cyan]{category.upper()}[/cyan]")
        for item in sorted(components[category]):
            logger.info(f"  • {item}")
        logger.info("")


@app.command("health")
def health_check(
    component_names: Annotated[
        list[str] | None,
        typer.Argument(help="Service name(s) to check (default: all running)"),
    ] = None,
    environment: str = typer.Option("dev", "--env", "-e", help="Environment to use"),
) -> None:
    """Check health of running services using config-driven endpoints."""
    from toolkit.features.health_check import HealthChecker

    checker = HealthChecker(environment)
    filter_names = list(component_names) if component_names else None
    results = checker.check_health(filter_names=filter_names)

    if not results:
        logger.warning("No services to check.")
        raise typer.Exit(0)

    table = Table(title=f"Service Health — {environment.upper()}")
    table.add_column("Service", style="cyan")
    table.add_column("URL", style="dim")
    table.add_column("Status", justify="center")
    table.add_column("Reason")

    has_failures = False
    for r in results:
        status = "[green]PASS[/green]" if r.healthy else "[red]FAIL[/red]"
        if not r.healthy:
            has_failures = True
        table.add_row(r.service, r.url, status, r.reason)

    console.print(table)

    if has_failures:
        raise typer.Exit(1)


def _backup_gitea(service_dir: Path, environment: str, output_dir: str) -> None:
    """Backup Gitea service data."""
    backup_file = Path(output_dir) / "gitea-backup.zip"
    config_manager = ConfigurationManager(environment)
    compose_files = config_manager.get_compose_files(service_dir)
    result = command.run_list(
        [
            "docker",
            "compose",
            *compose_files,
            "exec",
            "gitea",
            "gitea",
            "dump",
            "-c",
            "/data/gitea/conf/app.ini",
            "-f",
            str(backup_file),
        ],
        cwd=service_dir,
    )
    if result.returncode == 0:
        logger.success(MESSAGES.SUCCESS_BACKED_UP.format("Gitea data", backup_file))
    else:
        logger.error(MESSAGES.ERROR_GITEA_BACKUP_FAILED)
        raise typer.Exit(1)


def _backup_vaultwarden(service_dir: Path, environment: str, output_dir: str) -> None:
    """Backup Vaultwarden service data."""
    _backup_docker_volumes(service_dir, environment, "vaultwarden", output_dir)


def _backup_docker_volumes(service_dir: Path, environment: str, service_name: str, output_dir: str) -> None:
    """Generic Docker volume backup."""
    config_manager = ConfigurationManager(environment)
    compose_files = config_manager.get_compose_files(service_dir)
    result = command.run_list(
        [
            "docker",
            "compose",
            *compose_files,
            "config",
            "--volumes",
        ],
        cwd=service_dir,
    )
    if result.returncode == 0 and result.stdout.strip():
        volumes = result.stdout.strip().split("\n")
        for volume in volumes:
            volume = volume.strip()
            if volume:
                command.run_list(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "-v",
                        f"{volume}:/data",
                        "-v",
                        f"{output_dir}:/backup",
                        "alpine:latest",
                        "tar",
                        "czf",
                        f"/backup/{volume}.tar.gz",
                        "-C",
                        "/data",
                        ".",
                    ]
                )
        logger.success(MESSAGES.SUCCESS_BACKED_UP.format("Docker volumes", output_dir))
    else:
        logger.warning(MESSAGES.WARNING_NO_VOLUMES_FOUND.format(service_name))


def _restore_gitea(service_dir: Path, environment: str, backup_path: Path) -> None:
    """Restore Gitea service data."""
    config_manager = ConfigurationManager(environment)
    compose_files = config_manager.get_compose_files(service_dir)
    result = command.run_list(
        [
            "docker",
            "compose",
            *compose_files,
            "exec",
            "gitea",
            "gitea",
            "restore",
            "--config",
            "/data/gitea/conf/app.ini",
            str(backup_path),
        ],
        cwd=service_dir,
    )
    if result.returncode == 0:
        logger.success(MESSAGES.SUCCESS_GITEA_RESTORED)
    else:
        logger.error(MESSAGES.ERROR_GITEA_RESTORE_FAILED)
        raise typer.Exit(1)


def _restore_vaultwarden(service_dir: Path, environment: str, backup_path: Path) -> None:
    """Restore Vaultwarden service data."""
    logger.warning(MESSAGES.WARNING_VAULTWARDEN_RESTORE_NOT_IMPL)


def _get_timestamp() -> str:
    """Get current timestamp for backup naming."""
    from datetime import datetime

    return datetime.now().strftime("%Y%m%d-%H%M%S")
