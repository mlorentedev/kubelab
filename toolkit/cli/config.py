"""Configuration management commands."""

from typing import Annotated

import typer

from toolkit.config.constants import MESSAGES
from toolkit.core.logging import logger
from toolkit.features.generator_ansible import AnsibleGenerator
from toolkit.features.generator_authelia import AutheliaGenerator
from toolkit.features.generator_k8s import K8sGenerator
from toolkit.features.generator_terraform import TerraformGenerator
from toolkit.features.generator_traefik import TraefikGenerator
from toolkit.features.generator_wiki import WikiGenerator
from toolkit.features.validation import (
    confirm_dangerous_operation,
    validate_environment_config,
)

app = typer.Typer(
    name="config",
    help="Manage configuration files and environment variables.",
    no_args_is_help=True,
)


# =============================================================================
# General Configuration
# =============================================================================


@app.command()
def generate(
    env: str = typer.Option("dev", "--env", "-e", help="Target environment"),
    service: str | None = typer.Option(
        None,
        "--service",
        "-s",
        help="Specific service (traefik, ansible, terraform, authelia, k8s)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip the staging/prod confirmation prompt. Required for CI runs.",
    ),
) -> None:
    """
    Generate configuration files from templates (Traefik, Ansible, Terraform).

    Regenerates configs based on current environment variables.
    """
    logger.section(f"Configuration Generation - {env.upper()}")

    # Validate environment and confirm dangerous operation
    env_config = validate_environment_config(env)
    logger.info(f"Target: {env_config.description}")
    if not force:
        confirm_dangerous_operation(env_config, "Generate configs")

    try:
        success_count = 0
        total_count = 0

        if env == "dev":
            services_to_generate = [service] if service else ["traefik", "wiki", "authelia"]
        else:
            services_to_generate = (
                [service] if service else ["terraform", "traefik", "ansible", "wiki", "authelia", "k8s"]
            )

        for svc in services_to_generate:
            total_count += 1
            logger.info(f"Generating {svc} configuration...")

            try:
                if svc == "terraform":
                    result = TerraformGenerator().generate(env)
                elif svc == "traefik":
                    result = TraefikGenerator().generate(env)
                elif svc == "ansible":
                    result = AnsibleGenerator().generate(env)
                elif svc == "wiki":
                    result = WikiGenerator().generate(env)
                elif svc == "authelia":
                    result = AutheliaGenerator().generate(env)
                elif svc == "k8s":
                    result = K8sGenerator().generate(env)
                else:
                    logger.error(MESSAGES.ERROR_INVALID.format("service", svc))
                    continue

                if result:
                    success_count += 1
                    logger.success(MESSAGES.SUCCESS_CREATED.format(f"{svc} config"))
                else:
                    logger.warning(MESSAGES.WARNING_CONFIG_GENERATION_FAILED.format(svc, env))

            except Exception as e:
                logger.error(MESSAGES.ERROR_FAILED.format(f"generate {svc} config: {e}"))

        # Summary
        if success_count == total_count:
            logger.success(MESSAGES.SUCCESS_ALL_CONFIGS_GENERATED)
        else:
            failed_count = total_count - success_count
            msg = f"{failed_count} of {total_count} configurations failed to generate"
            logger.warning(MESSAGES.WARNING_FAILED.format(msg))
            raise typer.Exit(1) from None

    except Exception as e:
        logger.error(MESSAGES.ERROR_FAILED.format(f"generate configuration: {e}"))
        raise typer.Exit(1) from None


@app.command()
def validate(
    service: Annotated[
        str | None,
        typer.Option(
            "--service",
            "-s",
            help="Specific service to validate (terraform, traefik, ansible, authelia, k8s)",
        ),
    ] = None,
) -> None:
    """
    Validate generated configuration files (sanity check).
    """
    logger.section("Configuration Validation")

    try:
        success_count = 0
        total_count = 0

        services_to_validate = [service] if service else ["terraform", "traefik", "ansible", "authelia", "k8s"]

        for svc in services_to_validate:
            total_count += 1
            logger.info(f"Validating {svc} configuration...")

            try:
                # Call appropriate validator
                if svc == "terraform":
                    result = TerraformGenerator().validate()
                elif svc == "traefik":
                    result = TraefikGenerator().validate()
                elif svc == "ansible":
                    result = AnsibleGenerator().validate()
                elif svc == "authelia":
                    result = AutheliaGenerator().validate()
                elif svc == "k8s":
                    result = K8sGenerator().validate()
                else:
                    logger.error(MESSAGES.ERROR_INVALID.format("service", svc))
                    continue

                if result:
                    success_count += 1
                    logger.success(MESSAGES.SUCCESS_CONFIG_VALIDATION_PASSED.format(svc))
                else:
                    logger.warning(MESSAGES.WARNING_CONFIG_VALIDATION_FAILED.format(svc))

            except Exception as e:
                logger.error(MESSAGES.ERROR_CONFIG_VALIDATION_ERROR.format(svc, e))

        # Summary
        if success_count == total_count:
            logger.success(MESSAGES.SUCCESS_CONFIG_ALL_VALIDATIONS_PASSED)
        else:
            logger.warning(MESSAGES.WARNING_CONFIG_SOME_VALIDATIONS_FAILED.format(success_count, total_count))
            raise typer.Exit(1) from None

    except Exception as e:
        logger.error(MESSAGES.ERROR_CONFIG_VALIDATION_FAILED_WITH_ERROR.format(e))
        raise typer.Exit(1) from None


@app.command("get")
def config_get(
    path: Annotated[str, typer.Argument(help="Dotted path into common.yaml, e.g. argocd.chart_version")],
) -> None:
    """Print one NON-SECRET value from the SSOT, for scripts and Makefile targets.

    Exists so a Makefile target can read `common.yaml` without an inline
    `python -c "import yaml; ..."`. Those one-liners are a second reader of the
    SSOT with its own error handling (usually none): a typo'd path yields an
    empty string, the caller interpolates it, and the failure surfaces somewhere
    else entirely. This fails loudly with the path it could not resolve.

    Reads the PLAINTEXT config only -- never SOPS. Use `toolkit secrets show`
    for anything encrypted; keeping the two commands separate is what stops a
    secret being printed by a target that thought it was reading a version
    number.

    Example:
      toolkit config get argocd.chart_version
      toolkit config get networking.gcp.region
    """
    import yaml

    from toolkit.config.settings import settings

    common = settings.project_root / "infra" / "config" / "values" / "common.yaml"
    node = yaml.safe_load(common.read_text())

    walked: list[str] = []
    for part in path.split("."):
        walked.append(part)
        if not isinstance(node, dict) or part not in node:
            logger.error(f"{path} is not in common.yaml (resolved as far as {'.'.join(walked[:-1]) or '<root>'})")
            raise typer.Exit(1)
        node = node[part]

    if isinstance(node, dict | list):
        logger.error(f"{path} resolves to a {type(node).__name__}, not a scalar")
        raise typer.Exit(1)

    # print(), not logger: the caller is `$(...)` in a shell and wants the bare
    # value on stdout with no formatting, prefix or colour.
    print(node)
