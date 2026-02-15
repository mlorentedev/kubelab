"""Configuration management commands."""

from typing import Annotated

import typer

from toolkit.config.constants import MESSAGES
from toolkit.core.logging import logger
from toolkit.features.generator_ansible import AnsibleGenerator
from toolkit.features.generator_authelia import AutheliaGenerator
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
        help="Specific service (traefik, ansible, terraform, authelia)",
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
    confirm_dangerous_operation(env_config, "Generate configs")

    try:
        success_count = 0
        total_count = 0

        if env == "dev":
            services_to_generate = [service] if service else ["traefik", "wiki", "authelia"]
        else:
            services_to_generate = [service] if service else ["terraform", "traefik", "ansible", "wiki", "authelia"]

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
            help="Specific service to validate (terraform, traefik, ansible, authelia)",
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

        services_to_validate = [service] if service else ["terraform", "traefik", "ansible", "authelia"]

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
