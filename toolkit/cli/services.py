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


# =============================================================================
# Gitea forge reconciliation (TOOL-035, #1076)
# =============================================================================

gitea_app = typer.Typer(help="Reconcile the Gitea forge against its declaration")
app.add_typer(gitea_app, name="gitea")


def _gitea_clients(env: str) -> tuple[object, object, str, str]:
    """Build the admin and bot clients from SOPS, and resolve the bot's username.

    TWO CLIENTS BECAUSE TWO CREDENTIALS MAY DIFFERENT THINGS, per ADR-065 D1:
    the superadmin creates organizations (Gitea puts the creator in `Owners`) and
    reads whole-forge state (the bot cannot see an organization it is not a
    member of); the bot creates repositories inside them.

    Neither token is returned to a caller that might print it — they go straight
    into the clients that use them.
    """
    from toolkit.features.gitea_client import GiteaClient

    merged = ConfigurationManager(env, get_settings().project_root).get_merged_config()
    gitea = merged["apps"]["services"]["core"]["gitea"]
    base_url = f"https://{gitea['domain']}"

    admin_token = gitea.get("admin_token")
    bot_token = gitea.get("bot_token")
    missing = [n for n, v in (("admin_token", admin_token), ("bot_token", bot_token)) if not v]
    if missing:
        logger.error(
            f"missing Gitea credential(s) in {env} SOPS: {', '.join(missing)}. "
            "Mint at Settings > Applications; see SECRET_CATALOG for the required scopes."
        )
        raise typer.Exit(1)

    bot_username = merged["apps"]["auth"]["identities"]["machine"]
    return (
        GiteaClient(base_url, str(admin_token)),
        GiteaClient(base_url, str(bot_token)),
        str(bot_username),
        base_url,
    )


@gitea_app.command("reconcile")
def gitea_reconcile(
    env: Annotated[str, typer.Option("--env", "-e", help="Environment holding the forge credentials")] = "prod",
    apply: Annotated[bool, typer.Option("--apply", help="Actually create. Without it, plan only.")] = False,
) -> None:
    """Create declared organizations and repositories in Gitea; report undeclared ones.

    PLAN-ONLY BY DEFAULT. `--apply` is opt-in because the first run creates real
    organizations, and a reconciler whose default mutates a forge is one bad
    `make` invocation away from doing so unattended.

    Never deletes: `ReconcilePlan` has no field a deletion could travel in
    (#1076 scope), and undeclared entries are printed rather than acted on.
    """
    from toolkit.features.gitea_client import GiteaError
    from toolkit.features.gitea_repos import execute, format_plan, load_declaration, plan_reconcile

    admin, bot, bot_username, base_url = _gitea_clients(env)
    merged = ConfigurationManager(env, get_settings().project_root).get_merged_config()
    declared = load_declaration(merged)
    if not declared:
        logger.warning("no `gitea.organizations` declared in common.yaml — nothing to reconcile")
        raise typer.Exit(0)

    try:
        # Read with the admin credential: a listing taken with the bot's token
        # reports an organization it cannot see as absent, and the plan would
        # then propose creating something that already exists (lesson-408).
        existing_orgs = admin.list_orgs()  # type: ignore[attr-defined]
        existing_repos = admin.list_repos()  # type: ignore[attr-defined]
    except GiteaError as exc:
        logger.error(f"could not read forge state from {base_url}: {exc}")
        raise typer.Exit(1) from exc

    plan = plan_reconcile(declared, existing_orgs, existing_repos)
    console.print(f"\n[bold]Gitea reconcile[/bold] — {base_url} ({env})\n")
    console.print(format_plan(plan))

    if plan.is_noop:
        logger.success("forge matches the declaration — nothing to create")
        return

    if not apply:
        console.print("\n[dim]plan only — re-run with --apply to create[/dim]")
        return

    report = execute(plan, admin, bot, bot_username=bot_username)  # type: ignore[arg-type]
    for created in report.orgs_created:
        logger.success(f"org created: {created}")
    for created in report.repos_created:
        logger.success(f"repo created: {created}")
    for target, reason in report.failures:
        logger.error(f"{target}: {reason}")
    if not report.ok:
        raise typer.Exit(1)


@gitea_app.command("rotate-token")
def gitea_rotate_token(
    token: Annotated[str, typer.Option("--token", help="Which credential: bot or admin")] = "bot",
    env: Annotated[str, typer.Option("--env", "-e", help="Environment holding the forge credentials")] = "prod",
    apply: Annotated[bool, typer.Option("--apply", help="Actually rotate. Without it, plan only.")] = False,
) -> None:
    """Revoke a Gitea machine token and clear its SOPS key so a re-provision re-mints it.

    PLAN-ONLY BY DEFAULT, and the default matters more here than on `reconcile`:
    `--apply` OPENS AN OUTAGE. Between the revoke and the next
    `make provision NODE=bee ENV=prod`, nothing holding this credential can
    authenticate. Short, but real -- so it is run deliberately, never as a side
    effect of a mistyped target.

    BOTH HALVES OR NEITHER, in that order. See `gitea_tokens` for why revoking
    without clearing the key strands the account permanently, and why the reverse
    order silently mints a second live credential instead.

    Needs the admin PASSWORD, not a token: Gitea's token endpoints sit behind
    `reqBasicOrRevProxyAuth()` and reject bearer tokens before the handler runs.
    That is also why a drifted admin password takes this path down with it -- the
    probe/reassert pair in `beelink_services` exists to keep SOPS authoritative.
    """
    from toolkit.features.gitea_client import GiteaBasicAuthClient, GiteaError
    from toolkit.features.gitea_tokens import format_rotation_plan, plan_rotation
    from toolkit.features.secrets_manager import secrets_manager

    merged = ConfigurationManager(env, get_settings().project_root).get_merged_config()
    gitea = merged["apps"]["services"]["core"]["gitea"]
    identities = merged["apps"]["auth"]["identities"]

    try:
        plan = plan_rotation(token, identities, secret_present=bool(gitea.get(_secret_leaf(token))))
    except KeyError as exc:
        logger.error(str(exc).strip("'"))
        raise typer.Exit(1) from exc

    base_url = f"https://{gitea['domain']}"
    console.print(f"\n[bold]Gitea token rotation[/bold] — {base_url} ({env})\n")
    console.print(format_rotation_plan(plan))

    if not apply:
        console.print("\n[dim]plan only — re-run with --apply to rotate (this opens an outage window)[/dim]")
        return

    admin_password = gitea.get("admin_password")
    if not admin_password:
        # Fail BEFORE revoking, not after: without the password the revoke cannot
        # happen, and discovering that between the two halves is the stranded
        # state this command exists to prevent.
        logger.error(f"missing apps.services.core.gitea.admin_password in {env} SOPS — cannot reach the token endpoint")
        raise typer.Exit(1)

    client = GiteaBasicAuthClient(base_url, identities["superadmin"], str(admin_password))
    try:
        revoked = client.revoke_token(plan.username, plan.token_name)
    except GiteaError as exc:
        hint = " (a 401 here usually means the SOPS admin password has drifted — re-provision the Beelink)"
        logger.error(f"revoke failed{hint if exc.status_code == 401 else ''}: {exc}")
        raise typer.Exit(1) from exc

    if revoked:
        logger.success(f"revoked {plan.token_name} on {plan.username} — the outage window is now OPEN")
    else:
        logger.info(f"{plan.token_name} was already absent on {plan.username} — nothing to revoke")

    if not plan.secret_present:
        logger.info(f"{plan.secret_key} already unset — the mint gate was open")
    elif secrets_manager.unset_secret(env, plan.secret_key):
        logger.success(f"cleared {plan.secret_key} — the mint gate is open")
    else:
        # The loud half of the asymmetry in `gitea_tokens`: the token is gone and
        # the gate is still shut, so nothing will re-mint. Name the exact remedy
        # rather than leaving it to be reconstructed under pressure.
        logger.error(
            f"REVOKED BUT NOT CLEARED — run: toolkit secrets unset {plan.secret_key} --env {env}\n"
            "  until then the mint task stays gated and no replacement is issued."
        )
        raise typer.Exit(1)

    console.print("\n[bold]Next:[/bold] make provision NODE=bee ENV=prod   [dim](closes the outage window)[/dim]")


def _secret_leaf(token: str) -> str:
    """The last segment of a rotatable token's SOPS key.

    The merged config is already scoped to `apps.services.core.gitea`, so the
    lookup needs the leaf rather than the full dotted path the registry records.
    """
    from toolkit.features.gitea_tokens import ROTATABLE_TOKENS

    spec = ROTATABLE_TOKENS.get(token)
    return spec.secret_key.rsplit(".", 1)[-1] if spec else ""
