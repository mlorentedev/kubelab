"""Product contract commands (ADR-067 D2, IDP-042).

They read files and print results: no SOPS key, no network, no forge. The
receiver workflow fetches the contract; these commands only judge it (D8).
``list`` and ``app-for-event`` answer from the product registry
(``infra/config/products.yaml``) for the callers that cannot import it: the
Makefile and the workflows.
"""

import json
from pathlib import Path
from typing import Annotated

import typer

from toolkit.features import product_registry
from toolkit.features.product_contract import ContractError, validate_contract
from toolkit.features.product_guards import validate_registered

app = typer.Typer(
    name="product",
    help="Validate kubelab.yaml product contracts and read the product registry (ADR-067).",
    no_args_is_help=True,
)


@app.command()
def validate(
    contract: Annotated[Path, typer.Option("--contract", help="Path to a kubelab.yaml contract")],
    as_json: Annotated[bool, typer.Option("--json", help="Print one JSON object instead of text")] = False,
    registry: Annotated[
        Path | None, typer.Option("--registry", help="Also check against this product registry (needs --app)")
    ] = None,
    product: Annotated[str | None, typer.Option("--app", help="The registered product the contract belongs to")] = None,
) -> None:
    """Validate a product contract against the schema, and with --registry against the platform; exit 1 if refused."""
    if (registry is None) != (product is None):
        raise typer.BadParameter("--registry and --app go together: the contract does not name its product")
    try:
        if registry is not None and product is not None:
            parsed = validate_registered(contract, product, registry)
        else:
            parsed = validate_contract(contract)
    except ContractError as e:
        if as_json:
            typer.echo(json.dumps({"ok": False, **e.as_dict()}))
        else:
            typer.echo(str(e), err=True)
        raise typer.Exit(1) from None
    if as_json:
        typer.echo(json.dumps({"ok": True, "contract": str(contract), "schema_version": parsed.schema_version}))
    else:
        typer.echo(f"OK: {contract} is a valid kubelab product contract (schema_version {parsed.schema_version})")


@app.command("list")
def list_products(
    as_json: Annotated[bool, typer.Option("--json", help="Print a JSON array instead of one name per line")] = False,
) -> None:
    """List the registered products, in registry order."""
    apps = product_registry.platform_apps()
    typer.echo(json.dumps(list(apps)) if as_json else "\n".join(apps))


@app.command("app-for-event")
def app_for_event(
    event: Annotated[str, typer.Argument(help="A repository_dispatch event type")],
    as_json: Annotated[bool, typer.Option("--json", help="Print the app and its lane as one JSON object")] = False,
) -> None:
    """Name the app a dispatch event type belongs to; exit 1 if the registry maps it to none.

    The app comes from the event type, never from the dispatch payload (AC1).
    """
    try:
        route = product_registry.event_route(event)
    except product_registry.UnknownEventError:
        refusal = {
            "error": f"event type '{event}' is not mapped to any product",
            "why": "the registry alone says which event type means which app; the dispatch payload never names it",
            "fix": f"admit the product, or add the event type to its entry, in {product_registry.registry_path()}",
        }
        if as_json:
            typer.echo(json.dumps({"ok": False, **refusal}))
        else:
            typer.echo("\n".join(f"{key.upper()}: {value}" for key, value in refusal.items()), err=True)
        raise typer.Exit(1) from None
    if as_json:
        typer.echo(json.dumps({"ok": True, "event": event, "app": route.app, "lane": route.lane}))
    else:
        typer.echo(route.app)
