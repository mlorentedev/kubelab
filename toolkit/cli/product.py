"""Product contract commands (ADR-067 D2, IDP-042).

They read files and print results: no SOPS key, no network, no forge. The
receiver workflow fetches the contract; these commands only judge it (D8).
``ready`` is the one exception: the operator's gate before a product moves to
the generic receiver reads the product repository through ``gh``.
``list`` and ``app-for-event`` answer from the product registry
(``infra/config/products.yaml``) for the callers that cannot import it: the
Makefile and the workflows.
"""

import dataclasses
import json
from pathlib import Path
from typing import Annotated

import typer
import yaml

from toolkit.features import product_ready, product_registry, product_render
from toolkit.features.product_contract import ContractError, validate_contract
from toolkit.features.product_guards import validate_registered

app = typer.Typer(
    name="product",
    help="Validate and render kubelab.yaml product contracts, and read the product registry (ADR-067).",
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


@app.command()
def render(
    contract: Annotated[Path, typer.Option("--contract", help="Path to a kubelab.yaml contract")],
    env: Annotated[str, typer.Option("--env", help="staging or prod")],
    product: Annotated[
        str | None,
        typer.Option("--app", help="Registered product; required unless the contract is a committed snapshot"),
    ] = None,
    check: Annotated[bool, typer.Option("--check", help="Exit 1 if the values drift from the contract")] = False,
    write: Annotated[bool, typer.Option("--write", help="Correct the drifted keys in values/<env>.yaml")] = False,
) -> None:
    """Render a contract into apps.platform.<app>; without a flag, print the contract-owned keys."""
    if check and write:
        raise typer.BadParameter("pass --check or --write, not both")
    if env not in ("staging", "prod"):
        raise typer.BadParameter(f"--env must be staging or prod, got {env!r}")
    if product is None and contract.resolve().parent != product_render.SNAPSHOT_DIR.resolve():
        # A product repository's contract is kubelab.yaml, whose stem names no app.
        raise typer.BadParameter(
            "--app is required unless the contract is a snapshot in infra/config/products/contracts/"
        )
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


@app.command("show")
def show(
    name: Annotated[str, typer.Argument(help="A registered product")],
    as_json: Annotated[bool, typer.Option("--json", help="Print the entry as one JSON object")] = False,
) -> None:
    """Print where a product comes from: its forge, repository and receiver; exit 1 if unregistered."""
    try:
        entry = product_registry.product(name)
    except product_registry.UnknownProductError:
        refusal = {
            "error": f"'{name}' is not a registered product",
            "why": "the registry alone admits a product, and names the repository its contract is fetched from",
            "fix": f"admit the product with an entry in {product_registry.registry_path()}",
        }
        if as_json:
            typer.echo(json.dumps({"ok": False, **refusal}))
        else:
            typer.echo("\n".join(f"{key.upper()}: {value}" for key, value in refusal.items()), err=True)
        raise typer.Exit(1) from None
    fields = {"forge": entry.forge, "repository": entry.repository, "receiver": entry.receiver}
    if as_json:
        typer.echo(json.dumps({"ok": True, "app": name, **fields}))
    else:
        typer.echo("\n".join(f"{key}: {value}" for key, value in fields.items() if value is not None))


@app.command("ready")
def ready(
    name: Annotated[str, typer.Option("--app", help="A registered product with a remote repository")],
    as_json: Annotated[bool, typer.Option("--json", help="Print one JSON object instead of text")] = False,
) -> None:
    """Check the contract at the commit staging runs, as the generic receiver would; exit 1 if it would refuse."""
    try:
        answer = product_ready.check_ready(name)
    except ContractError as e:
        if as_json:
            typer.echo(json.dumps({"ok": False, **e.as_dict()}))
        else:
            typer.echo(str(e), err=True)
        raise typer.Exit(1) from None
    if as_json:
        typer.echo(json.dumps({"ok": True, **dataclasses.asdict(answer)}))
    else:
        typer.echo(f"OK: {answer.repository} carries a valid kubelab.yaml at {answer.tag} ({answer.sha})")
