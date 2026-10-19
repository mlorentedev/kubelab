"""Product contract commands (ADR-067 D2, IDP-042).

They read files and print results: no SOPS key, no network, no forge. The
receiver workflow fetches the contract; these commands only judge it (D8).
"""

import json
from pathlib import Path
from typing import Annotated

import typer

from toolkit.features.product_contract import ContractError, validate_contract
from toolkit.features.product_guards import validate_registered

app = typer.Typer(
    name="product",
    help="Validate kubelab.yaml product contracts (ADR-067).",
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
