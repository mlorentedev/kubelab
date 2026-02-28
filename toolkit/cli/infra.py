"Infrastructure management commands for deployment and status checking."

import os
from typing import Annotated

import typer

from toolkit.config.constants import MESSAGES, NETWORK_DEFAULTS, PATH_STRUCTURES
from toolkit.config.settings import get_settings, settings
from toolkit.core.logging import logger
from toolkit.features import command
from toolkit.features.validation import (
    confirm_dangerous_operation,
    validate_environment_config,
)

app = typer.Typer(
    name="infra",
    help="Infrastructure deployment and status commands",
    no_args_is_help=True,
)

ansible_app = typer.Typer(
    name="ansible",
    help="Ansible management commands",
    no_args_is_help=True,
)

terraform_app = typer.Typer(
    name="terraform",
    help="Terraform management commands",
    no_args_is_help=True,
)

k8s_app = typer.Typer(
    name="k8s",
    help="Kubernetes management commands",
    no_args_is_help=True,
)

app.add_typer(ansible_app, name="ansible")
app.add_typer(terraform_app, name="terraform")
app.add_typer(k8s_app, name="k8s")


# =============================================================================
# KUBERNETES COMMANDS
# =============================================================================

_K8S_DEFAULT_KUBECONFIG = "~/.kube/kubelab-config"


def _get_kubeconfig() -> str:
    """Get kubeconfig path from env or default."""
    return os.environ.get("KUBECONFIG", os.path.expanduser(_K8S_DEFAULT_KUBECONFIG))


def _kubectl_cmd(kubeconfig: str) -> str:
    """Build kubectl base command with kubeconfig."""
    return f"kubectl --kubeconfig {kubeconfig}"


def _generate_k8s_manifests(env: str) -> bool:
    """Generate K8s manifests via K8sGenerator. Returns True on success."""
    from toolkit.features.generator_k8s import K8sGenerator

    generator = K8sGenerator()
    result = generator.generate(env)
    if not result.get("success", False):
        logger.error(f"Manifest generation failed: {result.get('error', 'unknown')}")
        return False
    return True


def _get_traefik_config_path() -> str | None:
    """Return path to traefik-config.yaml if it exists (applied outside Kustomize)."""
    path = settings.project_root / PATH_STRUCTURES.K8S_BASE_DIR / "traefik-config.yaml"
    return str(path) if path.exists() else None


@k8s_app.command("apply-secrets")
def k8s_apply_secrets(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would be applied")] = False,
) -> None:
    """Decrypt SOPS secrets and apply as K8s Secrets.

    Reads from infra/config/secrets/{env}.enc.yaml, resolves the secret
    mappings, and runs kubectl create/apply for each K8s Secret.
    """
    if env == "dev":
        logger.info("Dev environment uses Docker Compose, not K8s")
        raise typer.Exit(0)

    validate_environment_config(env)

    from toolkit.features.k8s_secrets import apply_secrets

    if not apply_secrets(env, settings.project_root, dry_run=dry_run):
        raise typer.Exit(1)


@k8s_app.command("deploy")
def k8s_deploy(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")],
    skip_generate: Annotated[bool, typer.Option("--skip-generate", help="Skip manifest generation")] = False,
) -> None:
    """Deploy K8s manifests to the cluster.

    Generates manifests, validates with dry-run, applies, and waits for rollout.
    """
    if env == "dev":
        logger.info("Dev environment uses Docker Compose, not K8s")
        raise typer.Exit(0)

    logger.section(f"K8s Deploy - {env.upper()}")
    env_config = validate_environment_config(env)
    confirm_dangerous_operation(env_config, "Deploy to Kubernetes")

    kubeconfig = _get_kubeconfig()
    kctl = _kubectl_cmd(kubeconfig)
    overlay_dir = settings.project_root / PATH_STRUCTURES.K8S_OVERLAYS_DIR / env

    # 1. Generate manifests
    if not skip_generate:
        logger.info("Generating K8s manifests...")
        if not _generate_k8s_manifests(env):
            raise typer.Exit(1)

    if not overlay_dir.exists():
        logger.error(f"Overlay directory not found: {overlay_dir}")
        raise typer.Exit(1)

    # 2. Dry-run validation
    logger.info("Running dry-run validation...")
    dry_run = command.run(
        f"{kctl} apply --dry-run=client -k {overlay_dir}",
        check=False,
    )
    if dry_run.returncode != 0:
        logger.error(f"Dry-run failed:\n{dry_run.stderr}")
        raise typer.Exit(1)
    logger.success("Dry-run passed")

    # 3. Apply cluster-wide resources (outside Kustomize namespace override)
    traefik_cfg = _get_traefik_config_path()
    if traefik_cfg:
        logger.info("Applying Traefik config to kube-system...")
        tc_result = command.run(f"{kctl} apply -f {traefik_cfg}", check=False)
        if tc_result.returncode != 0:
            logger.error(f"Traefik config apply failed:\n{tc_result.stderr}")
            raise typer.Exit(1)

    # 4. Apply namespace-scoped manifests
    logger.info("Applying manifests...")
    apply_result = command.run(f"{kctl} apply -k {overlay_dir}", check=False)
    if apply_result.returncode != 0:
        logger.error(f"Apply failed:\n{apply_result.stderr}")
        raise typer.Exit(1)
    logger.console.print(apply_result.stdout)

    # 4. Wait for rollout
    logger.info("Waiting for rollout completion...")
    rollout = command.run(
        f"{kctl} rollout status deployment -n kubelab --timeout=120s",
        check=False,
    )
    if rollout.returncode != 0:
        logger.warning(f"Rollout not fully complete:\n{rollout.stderr}")
    else:
        logger.success("All deployments rolled out successfully")


@k8s_app.command("dry-run")
def k8s_dry_run(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")],
) -> None:
    """Generate manifests and validate with dry-run (no apply)."""
    if env == "dev":
        logger.info("Dev environment uses Docker Compose, not K8s")
        raise typer.Exit(0)

    logger.section(f"K8s Dry-Run - {env.upper()}")
    validate_environment_config(env)

    kubeconfig = _get_kubeconfig()
    kctl = _kubectl_cmd(kubeconfig)
    overlay_dir = settings.project_root / PATH_STRUCTURES.K8S_OVERLAYS_DIR / env

    # Generate manifests
    logger.info("Generating K8s manifests...")
    if not _generate_k8s_manifests(env):
        raise typer.Exit(1)

    if not overlay_dir.exists():
        logger.error(f"Overlay directory not found: {overlay_dir}")
        raise typer.Exit(1)

    # Dry-run cluster-wide resources
    traefik_cfg = _get_traefik_config_path()
    if traefik_cfg:
        logger.info("Validating Traefik config (kube-system)...")
        tc_result = command.run(
            f"{kctl} apply --dry-run=client -f {traefik_cfg}",
            check=False,
        )
        if tc_result.returncode != 0:
            logger.error(f"Traefik config dry-run failed:\n{tc_result.stderr}")
            raise typer.Exit(1)
        logger.console.print(tc_result.stdout)

    # Dry-run namespace-scoped resources
    logger.info("Running dry-run validation...")
    result = command.run(
        f"{kctl} apply --dry-run=client -k {overlay_dir}",
        check=False,
    )
    if result.returncode != 0:
        logger.error(f"Dry-run failed:\n{result.stderr}")
        raise typer.Exit(1)

    logger.console.print(result.stdout)
    logger.success("Dry-run validation passed — manifests are valid")


@k8s_app.command("status")
def k8s_status(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")],
) -> None:
    """Show K8s resource status for the kubelab namespace."""
    if env == "dev":
        logger.info("Dev environment uses Docker Compose, not K8s")
        raise typer.Exit(0)

    logger.section(f"K8s Status - {env.upper()}")
    validate_environment_config(env)

    kubeconfig = _get_kubeconfig()
    kctl = _kubectl_cmd(kubeconfig)

    result = command.run(
        f"{kctl} get pods,svc,ingressroute -n kubelab",
        check=False,
    )
    if result.returncode != 0:
        logger.error(f"Failed to get status:\n{result.stderr}")
        raise typer.Exit(1)

    logger.console.print(result.stdout)


# =============================================================================
# ANSIBLE COMMANDS
# =============================================================================


@ansible_app.command("deploy")
def ansible_deploy(
    env: Annotated[
        str,
        typer.Option(
            "--env",
            "-e",
            help="Target environment",
        ),
    ],
    limit: Annotated[
        str | None,
        typer.Option(
            "--limit",
            "-l",
            help="Limit deployment to specific hosts",
        ),
    ] = None,
) -> None:
    """Deploy configuration using Ansible playbooks.

    Executes the deployment playbook for the specified environment.
    """
    logger.section(f"Ansible Deployment - {env.upper()}")

    # Validate environment and get config
    env_config = validate_environment_config(env)
    env_settings = get_settings(env)

    try:
        if not env_config.ansible_inventory:
            logger.error(MESSAGES.ERROR_ANSIBLE_NO_INVENTORY.format(env))
            raise typer.Exit(1) from None

        ansible_dir = env_settings.ansible_dir
        inventory_path = ansible_dir / env_config.ansible_inventory

        if not inventory_path.exists():
            logger.error(MESSAGES.ERROR_ANSIBLE_INVENTORY_NOT_FOUND.format(inventory_path))
            raise typer.Exit(1) from None

        # Build command
        limit_hosts = limit or env
        cmd = (
            f"ansible-playbook {ansible_dir}/playbooks/deploy.yml "
            f"-i {inventory_path} --limit {limit_hosts} -e env={env}"
        )

        logger.info(f"Running: {cmd}")
        result = command.run(cmd, cwd=ansible_dir)

        if result.returncode == 0:
            logger.success(MESSAGES.SUCCESS_ANSIBLE_DEPLOYMENT.format(env))
        else:
            logger.error(MESSAGES.ERROR_ANSIBLE_DEPLOYMENT_FAILED)
            raise typer.Exit(1) from None

    except Exception as e:
        logger.error(MESSAGES.ERROR_ANSIBLE_DEPLOYMENT_FAILED_WITH_ERROR.format(e))
        raise typer.Exit(1) from None


# =============================================================================
# TERRAFORM COMMANDS
# =============================================================================


def _check_terraform_setup() -> None:
    """Check if Terraform is properly set up."""
    if command.run("which terraform", check=False).returncode != 0:
        logger.error(MESSAGES.ERROR_TERRAFORM_NOT_FOUND)
        raise typer.Exit(1) from None

    if not settings.terraform_dir.exists():
        logger.error(MESSAGES.ERROR_TERRAFORM_DIR_NOT_FOUND.format(settings.terraform_dir))
        raise typer.Exit(1) from None


def _get_terraform_env(env: str) -> dict[str, str]:
    """Build environment dict with Cloudflare API token from SOPS.

    Extracts the Cloudflare API token from the SOPS secrets and returns
    an env dict suitable for passing to subprocess/command.run calls.
    """
    from toolkit.features.configuration import ConfigurationManager

    config_manager = ConfigurationManager(env, settings.project_root)
    merged = config_manager.get_merged_config()

    # Navigate: cloudflare.api_token (from common.enc.yaml)
    token = merged.get("cloudflare", {}).get("api_token", "")
    if not token:
        logger.error("Cloudflare API token not found in SOPS secrets (cloudflare.api_token)")
        raise typer.Exit(1) from None

    # Inherit current environment + inject TF_VAR
    env_dict = dict(os.environ)
    env_dict["TF_VAR_cloudflare_api_token"] = token
    return env_dict


@terraform_app.command("init")
def tf_init(env: str = typer.Argument("dev", help="Target environment")) -> None:
    """
    Initialize Terraform configuration.

    Generates necessary backend config and runs 'terraform init'.
    """
    logger.section(f"Terraform Init - {env.upper()}")
    validate_environment_config(env)

    try:
        # Generate configuration first
        from toolkit.features.generator_terraform import terraform_generator

        result = terraform_generator.generate(env)
        if not result.get("success", False):
            logger.error(MESSAGES.ERROR_TERRAFORM_CONFIG_GENERATION_FAILED)
            raise typer.Exit(1) from None

        # Check terraform setup
        _check_terraform_setup()

        # Run terraform init
        terraform_dir = settings.terraform_dir
        tf_env = _get_terraform_env(env)

        cmd = "terraform init"
        logger.info(f"Running: {cmd}")

        tf_result = command.run(cmd, cwd=terraform_dir, env=tf_env)
        if tf_result.returncode == 0:
            logger.success(MESSAGES.SUCCESS_TERRAFORM_INIT.format(env))
        else:
            logger.error(MESSAGES.ERROR_TERRAFORM_INIT_FAILED)
            raise typer.Exit(1) from None

    except Exception as e:
        logger.error(MESSAGES.ERROR_TERRAFORM_INIT_FAILED_WITH_ERROR.format(e))
        raise typer.Exit(1) from None


@terraform_app.command("plan")
def tf_plan(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")],
    out: Annotated[str | None, typer.Option("--out", "-o", help="Save plan to file")] = None,
) -> None:
    """
    Create a Terraform execution plan.

    Previews changes without applying them.
    """
    validate_environment_config(env)
    logger.section(f"Terraform Plan - {env.upper()}")

    try:
        _check_terraform_setup()
        terraform_dir = settings.terraform_dir
        tf_env = _get_terraform_env(env)
        tfvars_file = terraform_dir / f"{env}.tfvars"

        output_file = out or f"{env}.tfplan"
        cmd_parts = ["terraform", "plan"]

        if tfvars_file.exists():
            cmd_parts.extend(["-var-file", str(tfvars_file)])

        cmd_parts.extend(["-out", output_file])
        cmd = " ".join(cmd_parts)

        logger.info(f"Creating plan: {cmd}")
        result = command.run(cmd, cwd=terraform_dir, env=tf_env)

        if result.returncode == 0:
            logger.success(MESSAGES.SUCCESS_TERRAFORM_PLAN_CREATED.format(output_file))
        else:
            raise typer.Exit(1) from None

    except Exception as e:
        logger.error(MESSAGES.ERROR_TERRAFORM_PLAN_FAILED.format(e))
        raise typer.Exit(1) from None


@terraform_app.command("apply")
def tf_apply(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")],
    plan_file: Annotated[str | None, typer.Option("--plan-file", "-f", help="Plan file to apply")] = None,
    auto_approve: Annotated[bool, typer.Option("--auto-approve", help="Skip interactive approval")] = False,
) -> None:
    """
    Apply Terraform configuration changes.

    Executes the plan to modify infrastructure.
    """
    logger.section(f"Terraform Apply - {env.upper()}")

    # Validate environment and get config
    env_config = validate_environment_config(env)

    try:
        _check_terraform_setup()

        # Safety check for production
        if env_config.requires_confirmation and not auto_approve:
            confirm_dangerous_operation(env_config, "Apply Terraform changes")

        terraform_dir = settings.terraform_dir
        tf_env = _get_terraform_env(env)
        plan_to_apply = plan_file or f"{env}.tfplan"

        # Check if plan file exists
        plan_path = terraform_dir / plan_to_apply
        if plan_path.exists():
            cmd = f"terraform apply {plan_to_apply}"
        else:
            logger.warning(MESSAGES.WARNING_TERRAFORM_PLAN_NOT_FOUND.format(plan_path))
            logger.info(MESSAGES.INFO_TERRAFORM_APPLY_WITHOUT_PLAN)
            cmd = "terraform apply"
            if auto_approve:
                cmd += " -auto-approve"

        logger.info(f"Applying configuration: {cmd}")
        result = command.run(cmd, cwd=terraform_dir, env=tf_env)

        if result.returncode == 0:
            logger.success(MESSAGES.SUCCESS_TERRAFORM_APPLY.format(env))
        else:
            raise typer.Exit(1) from None

    except Exception as e:
        logger.error(MESSAGES.ERROR_TERRAFORM_APPLY_FAILED.format(e))
        raise typer.Exit(1) from None


@terraform_app.command("destroy")
def tf_destroy(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")],
    auto_approve: Annotated[bool, typer.Option("--auto-approve", help="Skip interactive approval")] = False,
) -> None:
    """
    Destroy Terraform-managed infrastructure.

    DANGER: This will delete resources!
    """
    logger.section(f"Terraform Destroy - {env.upper()}")

    # Validate environment and get config
    env_config = validate_environment_config(env)

    try:
        _check_terraform_setup()

        # Always require confirmation for destroy
        if not auto_approve:
            logger.warning(MESSAGES.WARNING_TERRAFORM_DESTROY_DANGER)
            confirm_dangerous_operation(env_config, "Destroy infrastructure")

            # Additional confirmation for production (special case for destroy)
            if env == "prod":
                if not logger.confirm("This is PRODUCTION. Type 'destroy' to confirm:", default=False):
                    logger.info(MESSAGES.INFO_TERRAFORM_DESTROY_CANCELLED)
                    raise typer.Exit(0) from None

        terraform_dir = settings.terraform_dir
        tf_env = _get_terraform_env(env)
        tfvars_file = terraform_dir / f"{env}.tfvars"

        cmd_parts = ["terraform", "destroy"]

        if tfvars_file.exists():
            cmd_parts.extend(["-var-file", str(tfvars_file)])

        if auto_approve:
            cmd_parts.append("-auto-approve")

        cmd = " ".join(cmd_parts)

        logger.info(f"Destroying infrastructure: {cmd}")
        result = command.run(cmd, cwd=terraform_dir, env=tf_env)

        if result.returncode == 0:
            logger.success(MESSAGES.SUCCESS_TERRAFORM_DESTROY.format(env))
        else:
            raise typer.Exit(1) from None

    except Exception as e:
        logger.error(MESSAGES.ERROR_TERRAFORM_DESTROY_FAILED.format(e))
        raise typer.Exit(1) from None


@terraform_app.command("validate")
def tf_validate() -> None:
    """
    Validate and format Terraform configuration files.
    """
    logger.section("Terraform Configuration Validation")

    try:
        _check_terraform_setup()
        terraform_dir = settings.terraform_dir

        with logger.progress("Validating Terraform configuration...") as progress:
            task = progress.add_task("Validation", total=3)

            # Format check
            progress.update(task, description="Checking formatting...")
            format_result = command.run("terraform fmt -check", cwd=terraform_dir, check=False)
            progress.advance(task)

            # Syntax validation (needs provider vars for full validation)
            progress.update(task, description="Validating syntax...")
            validate_result = command.run("terraform validate", cwd=terraform_dir, check=False)
            progress.advance(task)

            progress.update(task, description="Finalizing...")
            progress.advance(task)

        if format_result.returncode != 0:
            logger.warning(MESSAGES.WARNING_TERRAFORM_FORMAT_NEEDED)
            logger.info(MESSAGES.INFO_TERRAFORM_FMT_COMMAND)

        if validate_result.returncode == 0:
            logger.success(MESSAGES.SUCCESS_TERRAFORM_VALID)
        else:
            raise typer.Exit(1) from None

    except Exception as e:
        logger.error(MESSAGES.ERROR_TERRAFORM_VALIDATION_FAILED.format(e))
        raise typer.Exit(1) from None


# =============================================================================
# GENERAL INFRA COMMANDS
# =============================================================================


@app.command()
def status(
    service: Annotated[
        str,
        typer.Argument(help="Service to check (traefik, all)"),
    ] = "traefik",
    env: Annotated[
        str,
        typer.Option(
            "--env",
            "-e",
            help="Target environment",
        ),
    ] = "dev",
) -> None:
    """
    Check the status of infrastructure services (e.g., Traefik).
    """
    validate_environment_config(env)

    if service == "traefik":
        _check_traefik_status(env)
    elif service == "all":
        _check_all_services_status(env)
    else:
        logger.error(MESSAGES.ERROR_UNKNOWN_SERVICE.format(service))
        logger.info(MESSAGES.INFO_INFRASTRUCTURE_AVAILABLE_SERVICES)
        raise typer.Exit(1) from None


def _check_traefik_status(env: str) -> None:
    """Check Traefik service status."""
    logger.section(f"Traefik Status - {env.upper()}")

    try:
        # Check if Traefik container is running
        result = command.run(
            "docker ps --filter name=traefik --format 'table {{.Names}}\t{{.Status}}'",
            check=False,
        )

        if result.returncode == 0 and result.stdout.strip():
            logger.success(MESSAGES.SUCCESS_INFRASTRUCTURE_TRAEFIK_RUNNING)
            logger.console.print(result.stdout)
        else:
            logger.warning(MESSAGES.WARNING_INFRASTRUCTURE_TRAEFIK_NOT_RUNNING)

        # Health check endpoints
        _check_traefik_health(env)

    except Exception as e:
        logger.error(MESSAGES.ERROR_INFRASTRUCTURE_STATUS_CHECK_FAILED.format(e))
        raise typer.Exit(1) from None


def _check_traefik_health(env: str) -> None:
    """Check Traefik health endpoints."""
    try:
        # Check Traefik API/dashboard
        env_settings = get_settings(env)
        api_url = env_settings.api_endpoint
        result = command.run(
            f"curl -s -o /dev/null -w '%{{http_code}}' --max-time {env_settings.curl_timeout} {api_url}",
            check=False,
        )

        if result.returncode == 0 and result.stdout.strip() in NETWORK_DEFAULTS.CONNECTION_SUCCESS_CODES:
            logger.success(MESSAGES.SUCCESS_INFRASTRUCTURE_TRAEFIK_API_RESPONDING)
        else:
            logger.warning(MESSAGES.WARNING_INFRASTRUCTURE_TRAEFIK_API_NOT_RESPONDING.format(result.stdout.strip()))

        # Check service discovery
        logger.info(MESSAGES.INFO_SERVICE_DISCOVERY_STATUS)
        result = command.run("docker ps --format 'table {{.Names}}\t{{.Labels}}'", check=False)
        if result.returncode == 0:
            # Count services with traefik labels
            traefik_services = 0
            for line in result.stdout.split("\n"):
                if "traefik.enable=true" in line:
                    traefik_services += 1

            logger.info(f"Found {traefik_services} services with Traefik labels")

    except Exception as e:
        logger.warning(MESSAGES.WARNING_INFRASTRUCTURE_HEALTH_CHECK_FAILED.format(e))


def _check_all_services_status(env: str) -> None:
    """Check status of all infrastructure services."""
    logger.section(f"All Services Status - {env.upper()}")

    services = ["traefik"]

    for service in services:
        logger.info(f"Checking {service}...")
        try:
            if service == "traefik":
                _check_traefik_status(env)
            logger.success(MESSAGES.SUCCESS_INFRASTRUCTURE_SERVICE_STATUS_CHECKED.format(service))
        except Exception:
            logger.warning(MESSAGES.WARNING_INFRASTRUCTURE_SERVICE_CHECK_FAILED.format(service))

    logger.info(MESSAGES.INFO_INFRASTRUCTURE_STATUS_CHECK_COMPLETED)


@app.command("nuke")
def nuke_infra(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")] = "dev",
    force: Annotated[bool, typer.Option("--force", "-f", help="Force execution without confirmation")] = False,
) -> None:
    """
    DESTROY EVERYTHING: Stops containers, removes volumes, networks, and cleans caches.

    Use with caution. This will:
    1. Stop all containers and remove volumes/networks for the environment.
    2. Remove all __pycache__ and .pytest_cache directories.
    3. Optionally run docker system prune.
    """
    logger.section("☢️  NUCLEAR OPTION: CLEAN INFRASTRUCTURE ☢️")

    if not force:
        logger.warning("This will destroy all data in volumes and stop services.")
        if not typer.confirm("Are you sure you want to proceed?"):
            logger.info("Operation cancelled.")
            raise typer.Exit()

    # 1. Stop all running containers and remove volumes
    logger.info(f"Stopping all containers and removing volumes for {env}...")
    command.run(
        "docker compose down --volumes --remove-orphans 2>/dev/null || true",
        check=False,
    )
    command.run("docker stop $(docker ps -q) 2>/dev/null || true", check=False)
    command.run("docker container prune -f", check=False)

    # 2. Clean Python Cache
    logger.info("Cleaning Python cache files...")
    cleaned_count = 0
    for path in settings.project_root.rglob("__pycache__"):
        import shutil

        try:
            shutil.rmtree(path)
            cleaned_count += 1
        except Exception as e:
            logger.warning(f"Failed to remove {path}: {e}")

    for path in settings.project_root.rglob(".pytest_cache"):
        import shutil

        try:
            shutil.rmtree(path)
            cleaned_count += 1
        except Exception as e:
            logger.warning(f"Failed to remove {path}: {e}")

    logger.success(f"Removed {cleaned_count} cache directories.")

    # 3. Docker System Prune (Optional)
    if force or typer.confirm("Do you want to run 'docker system prune -a' (removes unused images/networks)?"):
        logger.info("Pruning Docker system...")
        command.run("docker system prune -a -f --volumes", check=False)

    logger.success("Nuke complete. The slate is clean.")
