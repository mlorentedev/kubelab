"Service and application management commands."

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from rich.console import Console
from rich.table import Table

from toolkit.config.constants import MESSAGES, PATH_STRUCTURES
from toolkit.config.settings import PlatformSettings, get_settings
from toolkit.core.logging import logger
from toolkit.features import command
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.docker_service import DockerService

if TYPE_CHECKING:
    from toolkit.features.gitea_client import GiteaClient

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


def _gitea_clients(env: str) -> tuple["GiteaClient", "GiteaClient", str, str]:
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
            "Both are minted BY PROVISIONING, not by hand: run `make provision NODE=bee "
            "ENV=prod`. The `beelink_services` role mints each with "
            "`gitea admin user generate-access-token` and records it to SOPS over stdin, "
            "gated on the key being absent — so a re-provision with both present does "
            "nothing. This message used to say 'Mint at Settings > Applications', which "
            "sent operators to a browser to redo work the IaC already owns."
        )
        raise typer.Exit(1)

    bot_username = merged["apps"]["auth"]["identities"]["machine"]
    return (
        GiteaClient(base_url, str(admin_token)),
        GiteaClient(base_url, str(bot_token)),
        str(bot_username),
        base_url,
    )


def _report_machine_ownership(admin: "GiteaClient", bot_username: str) -> None:
    """Print what the machine identity owns — ADR-065 D1 / TOOL-035 AC4, every run.

    ON THE RECONCILE PATH RATHER THAN IN A TEST, deliberately. The property is
    about the LIVE forge, and the repo's live suites cannot decrypt SOPS, so a
    credentialed pytest would be new machinery rather than evidence. Printing it
    where the operator already looks makes `make gitea-reconcile ENV=prod` produce
    AC4's proof as a side effect of the run that proves AC1 — one transcript,
    both criteria, no second command anyone has to remember.

    NOT FATAL WHEN IT CANNOT BE READ, and the distinction is the point: a refusal
    means "I could not look", which lesson-408 says must never be reported as "I
    looked and it is empty". A reconcile that converged still converged; what is
    lost is the check, and the message says so rather than printing `(none)` and
    letting an unread state pass for a verified one.
    """
    from toolkit.features.gitea_client import GiteaError

    try:
        owned = sorted(admin.list_owned_repos(bot_username))
    except GiteaError as exc:
        console.print(
            f"\n[yellow]AC4 unchecked[/yellow] — could not read what {bot_username} owns: "
            f"{exc.status_code}. This is 'I did not look', not 'it owns nothing'. "
            f"A 403 here means the admin token predates `read:user` in "
            f"`apps.services.core.gitea.token_scopes.admin`; rotate and re-provision."
        )
        return

    if owned:
        console.print(
            f"\n[red]AC4 VIOLATED[/red] — {bot_username} owns {owned}. ADR-065 D1 requires the "
            f"machine identity to own nothing, so that retiring it is a membership deletion "
            f"rather than a data migration."
        )
        return

    console.print(f"\n[dim]AC4 ok — {bot_username} owns: (none)[/dim]")


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
        # Checked even here. AC4 is a property of the FORGE, not of the declaration:
        # an empty declaration is exactly the state in which nobody would think to
        # look, and a machine identity that has acquired a repository is worth
        # hearing about whether or not this run had anything to reconcile.
        _report_machine_ownership(admin, bot_username)
        raise typer.Exit(0)

    try:
        # Read with the admin credential: a listing taken with the bot's token
        # reports an organization it cannot see as absent, and the plan would
        # then propose creating something that already exists (lesson-408).
        existing_orgs = admin.list_orgs()
        existing_repos = admin.list_repos()
    except GiteaError as exc:
        logger.error(f"could not read forge state from {base_url}: {exc}")
        raise typer.Exit(1) from exc

    plan = plan_reconcile(declared, existing_orgs, existing_repos)
    console.print(f"\n[bold]Gitea reconcile[/bold] — {base_url} ({env})\n")
    console.print(format_plan(plan))

    if plan.is_noop:
        _report_machine_ownership(admin, bot_username)
        logger.success("forge matches the declaration — nothing to create")
        return

    if not apply:
        console.print("\n[dim]plan only — re-run with --apply to create[/dim]")
        _report_machine_ownership(admin, bot_username)
        return

    # Read only when a migration is actually planned. Its absence is a hard error
    # for a run that needs it and a non-event for one that does not, so fetching it
    # unconditionally would make every ordinary reconcile depend on a credential it
    # never uses.
    # Read only when a migration is actually planned, so an ordinary reconcile does
    # not depend on credentials it never uses.
    migration_token = None
    migrator = None
    if plan.repos_to_migrate:
        from toolkit.features.gitea_client import GiteaBasicAuthClient

        gitea_cfg = merged["apps"]["services"]["core"]["gitea"]
        migration_token = gitea_cfg.get("github_migration_token")
        admin_password = gitea_cfg.get("admin_password")
        if not admin_password:
            logger.error(
                f"missing apps.services.core.gitea.admin_password in {env} SOPS. Migration is the "
                f"one operation no token may perform (bot: not an organization owner; admin token: "
                f"lacks write:repository, which it must not be granted), so there is no fallback."
            )
            raise typer.Exit(1)
        migrator = GiteaBasicAuthClient(
            base_url, merged["apps"]["auth"]["identities"]["superadmin"], str(admin_password)
        )

    report = execute(plan, admin, bot, bot_username=bot_username, migration_token=migration_token, migrator=migrator)
    for created in report.orgs_created:
        logger.success(f"org created: {created}")
    for created in report.repos_created:
        logger.success(f"repo created: {created}")
    for migrated in report.repos_migrated:
        logger.success(f"repo migration accepted: {migrated}")
    if report.repos_migrated:
        console.print(
            "\n[yellow]The import continues in the background.[/yellow] Gitea returns from "
            "`/repos/migrate` before issues and pull requests have all arrived — counted minutes "
            "apart on `resume`: 98 pull requests, then 147. Verify AC3 once the counts stop moving, "
            "not when this command exits."
        )
    for target, reason in report.failures:
        logger.error(f"{target}: {reason}")

    # AFTER `execute`, not before. AC4 reads "the machine identity owns nothing
    # AFTERWARDS", and this call used to run once before the plan was carried out
    # -- so on `--apply` it reported PRE-reconcile state and an ownership violation
    # created by the very run being reported could not appear in its own output.
    # Reported by review on #1562.
    _report_machine_ownership(admin, bot_username)

    if not report.ok:
        raise typer.Exit(1)


@gitea_app.command("drop-empty")
def gitea_drop_empty(
    repo: Annotated[str, typer.Option("--repo", help="Target as `owner/name`")],
    env: Annotated[str, typer.Option("--env", "-e", help="Environment holding the forge credentials")] = "prod",
    apply: Annotated[bool, typer.Option("--apply", help="Actually delete. Without it, plan only.")] = False,
) -> None:
    """Remove an EMPTY DECLARED repository, so a migration can create it in its place.

    NOT A DELETION PATH FOR THE RECONCILER. `make gitea-reconcile` still cannot
    remove anything — `ReconcilePlan` has no field a deletion could travel in, and
    a test asserts that over `dataclasses.fields`. This is a separate command with
    its own object, its own credential and three refusals in front of it.

    It exists because PR1 created the declared repositories as empty shells and
    Gitea's `POST /repos/migrate` answers 409 when the target already exists — it
    creates a repository, it does not fill one. The shells therefore block the
    migration they were declared for, and something has to remove them once.

    Reads with the least-privileged credential that can answer and deletes with the
    one Gitea will accept: the admin TOKEN is refused `DELETE` with
    `required=[write:repository]`, and widening it would buy a standing delete
    capability on the reconciler's credential. `GiteaBasicAuthClient` grants nothing
    durable — see `gitea_client.GiteaBasicAuthClient.delete_repo`.
    """
    from toolkit.features.gitea_client import GiteaBasicAuthClient, GiteaError
    from toolkit.features.gitea_repos import declared_full_names, load_declaration, plan_drop, split_full_name

    admin, _bot, _bot_username, base_url = _gitea_clients(env)
    merged = ConfigurationManager(env, get_settings().project_root).get_merged_config()
    gitea = merged["apps"]["services"]["core"]["gitea"]
    declared = declared_full_names(load_declaration(merged))

    try:
        # The SAME parser the planner uses. Splitting here independently is what
        # made a malformed target die on "not enough values to unpack" instead of
        # on the refusal written for it.
        owner, name = split_full_name(repo)
        current = admin.get_repo(owner, name)
        decision = plan_drop(full_name=repo, repo=current, declared=declared)
    except ValueError as exc:
        logger.error(str(exc))
        raise typer.Exit(1) from exc
    except GiteaError as exc:
        logger.error(f"could not read {repo} from {base_url}: {exc}")
        raise typer.Exit(1) from exc

    console.print(f"\n[bold]Gitea drop-empty[/bold] — {base_url} ({env})\n")
    if current is not None:
        console.print(f"  {repo}  empty={current.get('empty')}  size={current.get('size')}")

    if not decision.may_drop:
        # Deliberately exit 0 on "already absent" and non-zero on a refusal: the
        # first is convergence, the second is a target that must not be touched,
        # and a caller scripting this needs to tell them apart.
        already_gone = current is None
        (logger.info if already_gone else logger.error)(decision.reason or "refused")
        raise typer.Exit(0 if already_gone else 1)

    if not apply:
        console.print("\n[dim]plan only — re-run with --apply to delete[/dim]")
        return

    admin_password = gitea.get("admin_password")
    if not admin_password:
        logger.error(
            f"missing apps.services.core.gitea.admin_password in {env} SOPS — the delete endpoint "
            f"refuses bearer tokens, so there is no token fallback. Re-provision the Beelink."
        )
        raise typer.Exit(1)

    client = GiteaBasicAuthClient(base_url, merged["apps"]["auth"]["identities"]["superadmin"], str(admin_password))
    try:
        deleted = client.delete_repo(owner, name)
    except GiteaError as exc:
        hint = " (a 401 here usually means the SOPS admin password has drifted — re-provision the Beelink)"
        logger.error(f"delete failed{hint if exc.status_code == 401 else ''}: {exc}")
        raise typer.Exit(1) from exc

    if deleted:
        logger.success(f"deleted {repo} (was empty) — `gitea-reconcile --apply` would recreate it as a shell")
    else:
        logger.info(f"{repo} was already absent — nothing to delete")


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


vikunja_app = typer.Typer(help="Audit the Vikunja task platform")
app.add_typer(vikunja_app, name="vikunja")


@vikunja_app.command("audit-users")
def vikunja_audit_users(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")],
) -> None:
    """List every Vikunja account, separating password signups from OIDC logins.

    SEC-VIKUNJA-001 (#1568) AC3. Public self-registration was open on an
    internet-facing domain from #1484 until #1568; closing it does not evict
    whoever is already inside. This answers "who exists" with a count instead of
    an assumption.

    Read-only by construction: the SQL is a `SELECT` held as a constant in
    `vikunja_users`, and nothing here writes. Emails are printed because
    identifying a stranger is the entire point -- they are not secrets, and no
    password, hash or token is read.
    """
    import subprocess

    from toolkit.cli.infra import _get_kubeconfig
    from toolkit.features.vikunja_users import (
        EXEC_TIMEOUT,
        FIELD_SEPARATOR,
        USER_AUDIT_SQL,
        local_accounts,
        parse_user_rows,
    )

    cmd = [
        "kubectl",
        "--kubeconfig",
        _get_kubeconfig(env),
        "-n",
        "kubelab",
        "exec",
        "-i",
        "deployment/postgres",
        "--",
        "psql",
        "-U",
        "kubelab",
        "-d",
        "vikunja",
        "-tAF",
        FIELD_SEPARATOR,
        "-c",
        USER_AUDIT_SQL,
    ]
    # Every failure below lands on the same branch, and that is the point: an audit
    # that cannot read the table must say so. Reporting zero accounts because the
    # query never ran is the same inversion the ticket was filed for -- "I could not
    # look" rendered as "nobody is there".
    #
    # The timeout is not defensive dressing. `kubectl exec` opens a stream and will
    # wait forever on an unreachable API server or a pod stuck terminating, and the
    # homelab is on-demand, so "unreachable" is a normal state here rather than an
    # exceptional one. Without a bound the command hangs instead of failing.
    try:
        res = subprocess.run(cmd, text=True, capture_output=True, timeout=EXEC_TIMEOUT)
    except subprocess.TimeoutExpired:
        logger.error(
            f"timed out after {EXEC_TIMEOUT}s reading the Vikunja user table in {env} — "
            "the cluster did not answer. This is NOT an empty account list."
        )
        raise typer.Exit(1) from None
    except OSError as exc:
        # Raised before `res` exists, so it cannot be handled by a returncode check:
        # a missing `kubectl` binary is the common case.
        logger.error(f"could not run kubectl: {exc}")
        raise typer.Exit(1) from None

    if res.returncode != 0:
        logger.error(f"could not read the Vikunja user table in {env}: {res.stderr.strip()}")
        raise typer.Exit(1)

    users = parse_user_rows(res.stdout)
    locals_ = local_accounts(users)

    table = Table(title=f"Vikunja accounts — {env}")
    table.add_column("id")
    table.add_column("username")
    table.add_column("email")
    table.add_column("origin")
    for user in users:
        table.add_row(user.user_id, user.username, user.email, user.issuer)
    console.print(table)

    console.print(
        f"\n{len(users)} account(s), {len(locals_)} created by password signup "
        f"(the ones an open /register endpoint could have produced)."
    )
    if locals_:
        console.print("[yellow]Confirm every password account above is yours.[/yellow]")
