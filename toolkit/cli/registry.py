"""Container registry commands."""

from typing import Annotated

import typer

from toolkit.core.logging import logger
from toolkit.features import promotion, registry
from toolkit.features.registry import SHA_TAG_PREFIX

app = typer.Typer(
    name="registry",
    help="Container registry maintenance (tag pruning).",
    no_args_is_help=True,
)


@app.command()
def prune(
    apps: Annotated[
        str,
        typer.Option("--apps", help="Comma-separated app names (repo = <prefix>-<app>)"),
    ] = "api,web,errors",
    retention: Annotated[
        int,
        typer.Option("--retention", "-n", help="Keep this many most-recent sha-* tags per app"),
    ] = 15,
    registry_prefix: Annotated[
        str,
        typer.Option("--registry-prefix", help="Image repo prefix"),
    ] = "kubelab",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="List what would be deleted without deleting"),
    ] = False,
) -> None:
    """
    Prune ephemeral image tags (ADR-046).

    Keeps the N most recent immutable ``sha-*`` tags per app (rollback headroom)
    and deletes the rest, plus any leftover ``-rc.*`` tags. Prod runs semver and
    is never touched. Needs ``DOCKERHUB_USERNAME``/``DOCKERHUB_TOKEN`` in the env.
    """
    logger.section(f"Registry Prune{' (dry-run)' if dry_run else ''}")
    app_list = [a.strip() for a in apps.split(",") if a.strip()]
    # Never prune a sha referenced by a committed overlay (ADR-056 prune guard):
    # gather the per-app sha pins from every env's values and protect them.
    protected: dict[str, set[str]] = {}
    for app_name in app_list:
        pins = {
            pin
            for env in ("staging", "prod")
            if (pin := promotion.read_pinned_version(env, app_name)) and pin.startswith(SHA_TAG_PREFIX)
        }
        if pins:
            protected[app_name] = pins
            logger.info(f"{app_name}: protecting overlay-pinned {sorted(pins)}")
    try:
        registry.prune(app_list, registry_prefix, retention, dry_run, protected=protected)
    except Exception as e:
        logger.error(f"Registry prune failed: {e}")
        raise typer.Exit(1) from None
