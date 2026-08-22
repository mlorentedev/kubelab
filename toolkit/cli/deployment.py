"""Deployment management commands."""

from typing import Annotated

import typer

from toolkit.config.constants import MESSAGES
from toolkit.core.logging import logger
from toolkit.features import promotion
from toolkit.features.validation import (
    validate_environment_config,
)

app = typer.Typer(
    name="deployment",
    help="High-level deployment orchestration (setup, deploy, rollback).",
    no_args_is_help=True,
)


@app.command()
def promote(
    app_name: Annotated[
        str,
        typer.Option("--app", "-a", help="App to promote (api|web|errors)"),
    ],
    version: Annotated[
        str,
        typer.Option("--version", "-v", help="Immutable image tag (e.g. 1.2.0 or sha-abc1234)"),
    ],
    env: Annotated[
        str | None,
        typer.Option("--env", "-e", help="Environment (staging|prod); required for api/web, ignored for errors"),
    ] = None,
) -> None:
    """
    Promote an app to an immutable image tag (ADR-046 D6).

    Verifies the tag exists in the registry, then: api/web set apps.platform.<app>.version
    in values/<env>.yaml and regenerate the overlay (staging tracks SHA, prod tracks semver);
    errors sets the single edge.errors.version in common.yaml and re-syncs the kustomization
    (env-agnostic single SSOT, DELIVERY-003).
    """
    if app_name == "errors":
        logger.section(f"Promote errors -> {version}")
    else:
        if not env:
            logger.error("--env is required for platform apps (api|web)")
            raise typer.Exit(1)
        logger.section(f"Promote {app_name} -> {version} ({env.upper()})")
        validate_environment_config(env)
    try:
        promotion.promote(env or "prod", app_name, version)
        target = "errors" if app_name == "errors" else f"{app_name} in {env}"
        logger.success(MESSAGES.SUCCESS_COMPLETED.format(f"Promote {target} to {version}"))
    except Exception as e:
        logger.error(MESSAGES.ERROR_FAILED_WITH_REASON.format("Promote", str(e)))
        raise typer.Exit(1) from None


@app.command(name="image-tag")
def image_tag(
    env: Annotated[
        str,
        typer.Option("--env", "-e", help="Source environment whose SSOT pin to read (staging)"),
    ],
    app_name: Annotated[
        str,
        typer.Option("--app", "-a", help="Platform app (api|web)"),
    ],
) -> None:
    """
    Print the immutable ``sha-<short>`` tag pinned for a platform app (ADR-056 build-once).

    Resolves ``apps.platform.<app>.version`` from ``values/<env>.yaml`` — the staging-
    validated digest release.yml re-tags as the prod semver (never a rebuild). Prints the
    bare tag to stdout for CI capture; errors (exit 1) if the pin is absent or not a sha.
    """
    try:
        typer.echo(promotion.resolve_image_sha(env, app_name))
    except Exception as e:
        logger.error(MESSAGES.ERROR_FAILED_WITH_REASON.format("Resolve image tag", str(e)))
        raise typer.Exit(1) from None
