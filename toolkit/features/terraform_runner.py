"""Every Terraform invocation in this repository goes through `run` (TF-007, #558).

Before this module each `tf-*` Make target carried its own copy of one sequence:
render a tfvars into the module directory, export a token, `cd`, `terraform
init`, the verb, then remove the file in the same shell line so that a failed
plan could not leave it on disk (TOOL-039). Nine copies drifted the way copies
do, and a test had to execute the Makefile with a stub `terraform` to prove each
one still cleaned up.

What every run guarantees, in one place:

- **Inputs come from the SSOT only.** Secrets are read from SOPS and reach the
  child as `TF_VAR_*`, never argv and never a file. Inherited `AWS_*` and `TF_*`
  variables are dropped first, but for the plugin cache: an operator's
  `AWS_PROFILE` or a stale `TF_VAR_region` would outrank the SSOT without a word,
  `TF_CLI_ARGS_apply=-auto-approve` would skip the guard and the prompt, and
  `TF_LOG` writes the injected values to the log.
- **Rendered tfvars live in a private temporary directory** (0600), removed on
  every exit, an exception or Ctrl-C included. A rendered file left in the module
  directory from the old targets is removed first, because Terraform auto-loads
  `*.auto.tfvars` and would read it next to the fresh render.
- **`init` runs first, every time.** A fresh clone or worktree has no
  `.terraform/`, and the verb alone fails there with a message that reads as a
  broken checkout.
- **Apply follows the root's declared mode.** `guarded` saves the plan, refuses
  any delete or replace not allowed (TF-013), and applies that same file;
  `interactive` leaves the prompt to Terraform; `auto` is for the disposable
  kill-switch fixture alone, which creates and destroys itself.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, NamedTuple, Protocol

ACTIONS = ("plan", "apply", "destroy", "output", "untaint")

# Every name a pre-runner Make target rendered into a module directory. One left
# behind is removed before a run: it is a second, stale declaration of the SSOT,
# and two of them carried secrets.
LEGACY_RENDERED = frozenset(
    {
        "aws.tfvars",
        "gcp.tfvars",
        "gcp-bootstrap.tfvars",
        "killswitch-test.tfvars",
        "r2.tfvars",
        "vps-firewall.auto.tfvars",
    }
)


# The only Terraform variables a run inherits: where downloaded providers are
# cached. Nothing here changes what Terraform does, only how fast init is.
INHERITED_TF = frozenset({"TF_PLUGIN_CACHE_DIR", "TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE"})


class RunnerError(Exception):
    """The run cannot start; the message names what to fix."""


class Result(NamedTuple):
    returncode: int
    stdout: str


class Terraform(Protocol):
    def __call__(self, args: list[str], *, env: dict[str, str], capture: bool, quiet: bool) -> Result: ...


Outputs = Callable[[str, str], str]


@dataclass(frozen=True)
class Context:
    """What a renderer may read: the merged SSOT, the module, other roots' outputs."""

    config: Mapping[str, Any]
    module_dir: Path
    outputs: Outputs


@dataclass(frozen=True)
class Root:
    name: str
    apply: Literal["guarded", "interactive", "auto"]
    # Terraform variable -> dotted SOPS path, injected as TF_VAR_<variable>.
    secrets: Mapping[str, str] = field(default_factory=dict)
    # Committed var files, relative to the module directory.
    var_files: tuple[str, ...] = ()
    # Renders a tfvars from the SSOT; written to the private temp dir.
    render: Callable[[Context], str] | None = None


def _render_gcp(ctx: Context) -> str:
    from toolkit.features import gcp_tfvars

    names = gcp_tfvars.declared_variables((ctx.module_dir / "variables.tf").read_text())
    return gcp_tfvars.render(dict(ctx.config), names)


def _render_dns(ctx: Context) -> str:
    """The VPS address the apex records point at, from the SSOT.

    It was typed into dns.tfvars as well, so a rebuilt VPS (runbook-disaster-
    recovery) needed the same edit in two places, and nothing compared them.
    """
    return f'vps_ip = "{ctx.config["networking"]["vps"]["public_ip"]}"\n'


def _render_r2(ctx: Context) -> str:
    from toolkit.features import r2_tfvars

    return r2_tfvars.render(dict(ctx.config))


def _render_vps_firewall(ctx: Context) -> str:
    from toolkit.features import vps_firewall_tfvars

    return vps_firewall_tfvars.render(dict(ctx.config))


def _render_killswitch_test(ctx: Context) -> str:
    """The scratch project's id and the service account the switch runs as.

    The account is READ FROM THE BOOTSTRAP ROOT'S OUTPUT rather than retyped.
    The detach permission is per project, so a stale copy grants the wrong
    identity and the proof then fails as a 403, which reads as "the kill switch
    does not work" when what failed was the test's own setup.

    The project id is unique per SECOND. GCP keeps a deleted project in
    DELETE_REQUESTED for ~30 days and reserves its id throughout, so a fixed id
    collides even after a clean destroy (measured 2026-08-23), and a minute is
    too coarse for a retry after a fast failure (#1310). The year is dropped to
    fit GCP's 30-character cap: the project lives ~90 seconds and is purged
    after 30 days, so month-day-time identifies an orphan completely.
    """
    sa = ctx.outputs("gcp-bootstrap", "kill_switch_service_account")
    if not sa:
        raise RunnerError(
            "could not read kill_switch_service_account from the gcp-bootstrap root. Apply that root first."
        )
    stamp = datetime.now(timezone.utc).strftime("%m%d%H%M%S")
    return f'kill_switch_service_account = "{sa}"\nproject_id = "kubelab-killswitch-{stamp}"\n'


ROOTS: dict[str, Root] = {
    r.name: r
    for r in (
        Root(
            "dns",
            apply="guarded",
            secrets={"cloudflare_api_token": "cloudflare.api_token"},
            var_files=("dns.tfvars",),
            render=_render_dns,
        ),
        # r2's lock rules cannot be lifted by a node; read the plan first. Its
        # token is not the DNS one, which the R2 bucket API refused (2026-10-02).
        Root(
            "r2",
            apply="interactive",
            secrets={"cloudflare_api_token": "cloudflare.r2_admin_token"},
            render=_render_r2,
        ),
        # An allow-list mistake locks the operator out of the host that runs
        # Headscale, so the VPN is no way back in. Read the plan.
        Root(
            "vps-firewall",
            apply="interactive",
            secrets={"hetzner_api_token": "hetzner.api_key"},
            render=_render_vps_firewall,
        ),
        Root(
            "aws",
            apply="guarded",
            secrets={
                "tailscale_authkey": "aws.headscale_preauth_key",
                "headscale_api_key": "aws.headscale_api_key",
            },
        ),
        # The project, its budgets and the kill switch. Runs once, before
        # anything billable exists, and is never part of the hub's lifecycle.
        Root(
            "gcp-bootstrap",
            apply="interactive",
            secrets={"billing_account_id": "gcp.billing_account_id"},
        ),
        # Disaster recovery only: how to create the VPS from scratch, never
        # imported against the running one. Its inputs are the defaults in
        # variables.tf; its deployer key is TF-018 (#2230).
        Root("compute", apply="guarded", secrets={"hetzner_api_token": "hetzner.api_key"}),
        # Carries no secret: the hub reads its credentials from Secret Manager.
        Root("gcp", apply="guarded", render=_render_gcp),
        Root(
            "gcp-killswitch-test",
            apply="auto",
            secrets={"billing_account_id": "gcp.billing_account_id"},
            render=_render_killswitch_test,
        ),
    )
}


def subprocess_terraform(args: list[str], *, env: dict[str, str], capture: bool, quiet: bool) -> Result:
    """The real seam. stdin stays inherited, so an interactive apply can prompt."""
    try:
        proc = subprocess.run(
            ["terraform", *args],
            env=env,
            stdout=subprocess.PIPE if capture else (subprocess.DEVNULL if quiet else None),
            text=True,
            check=False,
        )
    except FileNotFoundError:
        raise RunnerError(
            "terraform is not on PATH. Install the pinned version with `dotf tools sync` "
            "(TERRAFORM_VERSION in dotfiles versions.conf)."
        ) from None
    return Result(proc.returncode, proc.stdout or "")


def _dig(config: Mapping[str, Any], dotted: str) -> Any:
    node: Any = config
    for part in dotted.split("."):
        if not isinstance(node, Mapping):
            return None
        node = node.get(part)
    return node


def child_env(config: Mapping[str, Any], root: Root, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """The child's environment: inherited minus AWS_* and TF_* (see INHERITED_TF), plus the root's secrets."""
    env = {
        k: v
        for k, v in (os.environ if base is None else base).items()
        if not k.startswith("AWS_") and (not k.startswith("TF_") or k in INHERITED_TF)
    }
    for variable, path in root.secrets.items():
        value = _dig(config, path)
        if value in (None, ""):
            raise RunnerError(
                f"{path} is empty or absent in SOPS; the {root.name} root needs it as {variable}. "
                f"Set it with: toolkit secrets set {path} --stdin --env common"
            )
        env[f"TF_VAR_{variable}"] = str(value)
    return env


def _remove_legacy_renders(module_dir: Path) -> None:
    for name in LEGACY_RENDERED:
        (module_dir / name).unlink(missing_ok=True)


def _default_config() -> Mapping[str, Any]:
    from toolkit.features.configuration import ConfigurationManager

    return ConfigurationManager("common").get_merged_config()


def output(
    root: str,
    name: str,
    *,
    terraform_dir: Path,
    terraform: Terraform = subprocess_terraform,
) -> str:
    """One output of another root, read through the runner (no secret needed)."""
    module = terraform_dir / root
    chdir = f"-chdir={module}"
    env = child_env({}, Root(root, apply="guarded"))
    if terraform([chdir, "init", "-input=false"], env=env, capture=False, quiet=True).returncode != 0:
        return ""
    result = terraform([chdir, "output", "-raw", name], env=env, capture=True, quiet=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def run(
    root_name: str,
    action: str,
    *,
    terraform_dir: Path,
    extra: Sequence[str] = (),
    allow_destroy: bool = False,
    allowed: Sequence[str] = (),
    load_config: Callable[[], Mapping[str, Any]] = _default_config,
    terraform: Terraform = subprocess_terraform,
    outputs: Outputs | None = None,
) -> int:
    """Run one Terraform action against one root. Returns Terraform's exit code."""
    root = ROOTS.get(root_name)
    if root is None:
        raise RunnerError(f"unknown root {root_name!r}; known: {', '.join(sorted(ROOTS))}")
    if action not in ACTIONS:
        raise RunnerError(f"unknown action {action!r}; known: {', '.join(ACTIONS)}")
    if action == "untaint" and not extra:
        raise RunnerError("untaint needs the resource address to clear")

    module = terraform_dir / root.name
    chdir = f"-chdir={module}"
    state_only = action in ("output", "untaint")
    config = {} if state_only else load_config()
    env = child_env(config, Root(root.name, root.apply) if state_only else root)
    if outputs is None:

        def outputs(other: str, name: str) -> str:
            return output(other, name, terraform_dir=terraform_dir, terraform=terraform)

    _remove_legacy_renders(module)
    with tempfile.TemporaryDirectory(prefix=f"tf-{root.name}-") as tmp:
        var_args = [f"-var-file={module / f}" for f in root.var_files]
        if root.render is not None and not state_only:
            rendered = Path(tmp) / f"{root.name}.tfvars"
            try:
                content = root.render(Context(config, module, outputs))
            except (KeyError, ValueError) as exc:
                # A renderer refusing the SSOT names the key to fix; a KeyError's
                # message is the missing key itself.
                raise RunnerError(f"cannot render the {root.name} inputs from common.yaml: {exc}") from exc
            fd = os.open(rendered, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(content)
            var_args.append(f"-var-file={rendered}")

        def tf(*args: str, capture: bool = False, quiet: bool = False) -> Result:
            return terraform([chdir, *args], env=env, capture=capture, quiet=quiet)

        rc = tf("init", "-input=false", quiet=True).returncode
        if rc != 0:
            return rc

        if action == "plan":
            return tf("plan", "-input=false", *var_args, *extra).returncode
        if action == "output":
            return tf("output", *extra).returncode
        if action == "untaint":
            return tf("untaint", *extra).returncode
        if action == "destroy":
            auto = ("-auto-approve",) if root.apply == "auto" else ()
            return tf("destroy", *auto, *var_args, *extra).returncode
        # apply
        if root.apply == "interactive":
            return tf("apply", *var_args, *extra).returncode
        if root.apply == "auto":
            return tf("apply", "-auto-approve", *var_args, *extra).returncode
        return _guarded_apply(tf, Path(tmp), var_args, extra, allow_destroy, allowed)


def _guarded_apply(
    tf: Callable[..., Result],
    tmp: Path,
    var_args: list[str],
    extra: Sequence[str],
    allow_destroy: bool,
    allowed: Sequence[str],
) -> int:
    """TF-013: save the plan, refuse an unallowed delete, apply that same file.

    The saved plan holds the input variables, token included, so it lives in the
    private temp dir and its JSON is read into memory, never printed.
    """
    import json

    from toolkit.core.logging import logger
    from toolkit.features.terraform_plan_guard import refused, summary

    planfile = str(tmp / "plan")
    rc = tf("plan", "-input=false", f"-out={planfile}", *var_args, *extra).returncode
    if rc != 0:
        return rc
    shown = tf("show", "-json", planfile, capture=True)
    if shown.returncode != 0:
        return shown.returncode
    try:
        plan = json.loads(shown.stdout)
    except ValueError:
        logger.error("terraform show -json returned no plan JSON; nothing was applied")
        return 1
    counts = summary(plan)
    logger.info(f"Plan: {counts['create']} to add, {counts['update']} to change, {counts['delete']} to destroy.")
    blocked = refused(plan, allow_destroy=allow_destroy, allowed=frozenset(allowed))
    if blocked:
        for change in blocked:
            logger.error(f"refused: {change.describe()}")
        if any(c.reason == "replace_because_tainted" for c in blocked):
            logger.info("A tainted resource may already exist (lesson-543). Check it, then:")
            logger.info("  make tf-untaint ROOT=<root> RES='<address>'")
        logger.info("To delete on purpose, re-run with ALLOW_DESTROY=1.")
        return 1
    return tf("apply", "-input=false", planfile).returncode
