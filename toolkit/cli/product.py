"""Product contract commands (ADR-067 D2, IDP-042).

They read files and print results: no SOPS key, no network, no forge. The
receiver workflow fetches the contract; these commands only judge it (D8).
"""

import json
from pathlib import Path
from typing import Annotated

import typer
import yaml

from toolkit.features import product_render
from toolkit.features.product_contract import ContractError, validate_contract

app = typer.Typer(
    name="product",
    help="Validate and render kubelab.yaml product contracts (ADR-067).",
    no_args_is_help=True,
)


@app.command()
def validate(
    contract: Annotated[Path, typer.Option("--contract", help="Path to a kubelab.yaml contract")],
    as_json: Annotated[bool, typer.Option("--json", help="Print one JSON object instead of text")] = False,
) -> None:
    """Validate a product contract against the kubelab.yaml schema; exit 1 if it is refused."""
    try:
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


@app.command()
def render(
    contract: Annotated[Path, typer.Option("--contract", help="Path to a kubelab.yaml contract")],
    env: Annotated[str, typer.Option("--env", help="staging or prod")],
    product: Annotated[
        str | None, typer.Option("--app", help="Registered product; defaults to the contract file's stem")
    ] = None,
    check: Annotated[bool, typer.Option("--check", help="Exit 1 if the values drift from the contract")] = False,
    write: Annotated[bool, typer.Option("--write", help="Correct the drifted keys in values/<env>.yaml")] = False,
) -> None:
    """Render a contract into apps.platform.<app>; without a flag, print the contract-owned keys."""
    if check and write:
        raise typer.BadParameter("pass --check or --write, not both")
    if env not in ("staging", "prod"):
        raise typer.BadParameter(f"--env must be staging or prod, got {env!r}")
    name = product or contract.stem
    try:
        parsed = validate_contract(contract)
        if write:
            changed = product_render.write(parsed, name, env, values_dir=product_render.VALUES_DIR)
            typer.echo(f"{name}/{env}: wrote {', '.join(changed)}" if changed else f"{name}/{env}: nothing to write")
        elif check:
            differences, compared = product_render.drift(parsed, name, env, values_dir=product_render.VALUES_DIR)
            typer.echo(f"compared {compared} contract-owned keys for {name}/{env}")
            for key, (want, have) in differences.items():
                typer.echo(f"DRIFT {key}: contract renders {want!r}, values have {have!r}")
            if differences:
                raise typer.Exit(1)
        else:
            typer.echo(yaml.safe_dump(product_render.rendered(parsed, name, env), sort_keys=False), nl=False)
    except ContractError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from None
