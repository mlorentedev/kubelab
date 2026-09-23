"""Identity operations (AUTH-004): the way in when Authelia is down."""

from __future__ import annotations

import getpass
import json
import shutil
import socket
import subprocess
from typing import Annotated, Any

import typer
import yaml

from toolkit.config.settings import PROJECT_ROOT
from toolkit.core.logging import logger
from toolkit.features import break_glass as bg
from toolkit.features.k8s_kubeconfig import output_path as kubeconfig_path

app = typer.Typer(help="Identity operations (AUTH-004): break-glass access while the IdP is down.")

_ENVS = ("staging", "prod")
_SECRETS_DIR = PROJECT_ROOT / "infra" / "config" / "secrets"
#: Exit code for "no break-glass, by declaration". Distinct from failure (1), so
#: a caller never reads a deliberate absence as a broken path, or the reverse.
EXIT_DECLARED_NONE = 3


def _render(env: str) -> list[dict[str, Any]]:
    """The overlay as the cluster receives it. It renders the repo locally and needs no cluster.

    A failure here means the checkout itself is broken, and the operator is told
    so in one line rather than handed a traceback in the middle of an incident.
    """
    result = subprocess.run(
        ["kubectl", "kustomize", str(PROJECT_ROOT / "infra" / "k8s" / "overlays" / env)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()[-1:] or ["no output"]
        raise bg.BreakGlassError(f"could not render the {env} overlay from this checkout: {detail[0]}")
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _kubectl_json(env: str, *args: str) -> Any:
    result = subprocess.run(
        ["kubectl", "--kubeconfig", str(kubeconfig_path(env)), *args, "-o", "json"],
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout) if result.returncode == 0 and result.stdout else None


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _announce(env: str, service: str) -> None:
    from toolkit.features.configuration import ConfigurationManager
    from toolkit.features.notify_smoke import NOTIFY_SECRET_KEY

    who = f"{getpass.getuser()}@{socket.gethostname()}"
    logger.warning(f"break-glass: {who} is opening {service} in {env}")
    cm = ConfigurationManager(env, PROJECT_ROOT)
    announced = bg.announce_use(
        env,
        service,
        who=who,
        merged_config=cm.get_merged_config(),
        webhook_secret=cm.get_secret_by_path(NOTIFY_SECRET_KEY),
    )
    if announced:
        logger.info("  announced to the operator channel")
    else:
        logger.warning("  could NOT announce this use (notify webhook unreachable); continuing -- access wins")


def _account_guidance(env: str, decl: dict[str, Any], identities: dict[str, str]) -> None:
    if "identity" not in decl:
        typer.echo("  account:  none needed")
        return
    where = bg.secret_file(decl["secret"], env, _SECRETS_DIR)
    typer.echo(f"  user:     {identities[decl['identity']]}")
    typer.echo(f"  password: run in YOUR terminal: make secrets-show KEY={decl['secret']} SECRETS_ENV={where}")
    typer.echo(f"  after:    rotate it -- toolkit secrets rotate {decl['secret']} --env {where}")


@app.command("break-glass")
def break_glass_cmd(
    service: Annotated[str, typer.Argument(help="IngressRoute name of a service that depends on Authelia")],
    env: Annotated[str, typer.Option("--env", "-e", help="staging or prod")] = "prod",
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Resolve and print the path; open no tunnel and announce nothing (read-only checks still run)",
        ),
    ] = False,
) -> None:
    """Open the private way into SERVICE while Authelia is down (ADR-062 D4).

    Never goes through the public router or the IdP: a port-forward to the
    Service, its EndpointSlice address over the tailnet, or the cluster
    credential. Every real use is announced to the operator channel.
    """
    from toolkit.features.oidc_clients import load_values

    if env not in _ENVS:
        typer.echo(f"--env must be one of {_ENVS}", err=True)
        raise typer.Exit(1)
    if shutil.which("kubectl") is None:
        typer.echo("kubectl is not on PATH: the break-glass path needs it", err=True)
        raise typer.Exit(1)

    values = load_values(env)
    decls = bg.declarations(values)
    try:
        bg.validate(decls, values)
        deps = bg.dependents(env, _render(env), values)
    except bg.BreakGlassError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    if service not in deps:
        typer.echo(
            f"{service} does not depend on Authelia in {env}, so its normal login is unaffected. "
            f"Services that do: {', '.join(sorted(deps))}",
            err=True,
        )
        raise typer.Exit(1)
    if service not in decls:
        typer.echo(f"{service} declares no break-glass path in {bg.DECLARATION_PATH} (CI should catch this)", err=True)
        raise typer.Exit(1)

    decl, route = decls[service], deps[service]
    service_json = endpoint_slices = None
    if not ({"none", "cluster"} & set(decl)) and route.backend is not None:
        backend = route.backend
        service_json = _kubectl_json(env, "-n", backend.namespace, "get", "service", backend.name)
        slices = _kubectl_json(
            env, "-n", backend.namespace, "get", "endpointslices", "-l", f"kubernetes.io/service-name={backend.name}"
        )
        endpoint_slices = (slices or {}).get("items", [])
    plan = bg.plan_access(decl, route, service_json, endpoint_slices or [])

    if isinstance(plan, bg.NoBreakGlass):
        typer.echo(f"{service} ({env}) has no break-glass path, by design: {plan.reason}")
        raise typer.Exit(EXIT_DECLARED_NONE)

    identities = (values.get("apps", {}).get("auth", {}) or {}).get("identities", {}) or {}
    typer.echo(f"break-glass: {service} ({env})")
    if not dry_run:
        _announce(env, service)

    if isinstance(plan, bg.ClusterCredential):
        path = kubeconfig_path(plan.target)
        typer.echo(f"  way in:   the {plan.target} cluster credential -- export KUBECONFIG={path}")
        reachable = (
            subprocess.run(
                ["kubectl", "--kubeconfig", str(path), "get", "--raw", "/version"], capture_output=True
            ).returncode
            == 0
        )
        verdict = "reachable" if reachable else "NOT reachable -- check the tailnet and the kubeconfig"
        typer.echo(f"  verified: {verdict}")
        raise typer.Exit(0 if reachable else 1)

    if isinstance(plan, bg.Direct):
        typer.echo(f"  way in:   {plan.url}  (over the tailnet, bypassing the router and the IdP)")
        _account_guidance(env, decl, identities)
        return

    local = _free_port()
    typer.echo(f"  way in:   http://127.0.0.1:{local}  (port-forward to {plan.namespace}/{plan.service}:{plan.port})")
    _account_guidance(env, decl, identities)
    if dry_run:
        return
    typer.echo("  Ctrl-C closes the tunnel.")
    subprocess.run(
        [
            "kubectl",
            "--kubeconfig",
            str(kubeconfig_path(env)),
            "-n",
            plan.namespace,
            "port-forward",
            f"svc/{plan.service}",
            f"{local}:{plan.port}",
        ]
    )
