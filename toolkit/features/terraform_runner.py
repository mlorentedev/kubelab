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
- **`init` runs first, every time, against the shared R2 backend.** A fresh
  clone or worktree has no `.terraform/`, and the verb alone fails there with a
  message that reads as a broken checkout. `-backend-config` passes the one
  generated `backend.s3.tfbackend`; the bucket's credentials reach the child as
  AWS_* from SOPS `terraform.state.*`, for every action.
- **No root runs against a state the backend does not hold.** A local
  `terraform.tfstate` left in a module refuses every action but `migrate`, and
  a root whose state was lost refuses every write until it is recovered.
- **Every write leaves a copy of the state in history.** R2 has no object
  versioning, so before and after each write the state is put under a locked
  `history/<root>/<lineage>/<serial>.tfstate` key that cannot be overwritten.
- **Apply follows the root's declared mode.** `guarded` saves the plan, refuses
  any delete or replace not allowed (TF-013), and applies that same file;
  `interactive` leaves the prompt to Terraform; `auto` is for the disposable
  kill-switch fixture alone, which creates and destroys itself.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, NamedTuple, Protocol

from toolkit.features import terraform_backend

ACTIONS = (
    "plan",
    "apply",
    "destroy",
    "output",
    "untaint",
    "migrate",
    "state-list",
    "history",
    "restore",
    "unlock",
)

# Actions that read or write state and nothing else: no variables, so no secret
# of the root's. They still need the backend's credentials.
STATE_ONLY = frozenset({"output", "untaint", "migrate", "state-list", "history", "restore", "unlock"})

# Actions that write state, snapshotted to history before and after.
WRITES = frozenset({"apply", "destroy", "untaint", "migrate", "restore"})

# What `restore` takes: one history copy, named as its key names it.
HISTORY_REF = re.compile(r"^[A-Za-z0-9-]+/[0-9]+$")

# The bucket's credentials, as the S3 backend reads them, from SOPS. Minted with
# a token scoped to the state bucket alone by `make tf-state-bootstrap`.
STATE_CREDENTIALS = {
    "AWS_ACCESS_KEY_ID": "terraform.state.access_key_id",
    "AWS_SECRET_ACCESS_KEY": "terraform.state.secret_access_key",
}

LOCAL_STATE = "terraform.tfstate"
# Where `migrate` moves the local file once R2 holds the same state. Still
# ignored by git (`*.tfstate`), kept rather than deleted: it is the last copy
# from before the backend existed.
MIGRATED_STATE = "terraform.pre-remote.tfstate"
# Where `migrate` keeps the local file while it runs. An init that finds a
# terraform.tfstate next to a new backend wants to ask whether to copy it, and
# with -input=false refuses outright, so init must not see it. Left behind only
# if the run is killed; the next migrate resumes from it.
MIGRATING_STATE = "terraform.migrating.tfstate"

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
    # Secrets an apply needs and a plan does not: injected when SOPS has them,
    # and an apply refuses to start without them. For a dormant root whose
    # credentials were retired with the host they admitted.
    apply_secrets: Mapping[str, str] = field(default_factory=dict)
    # The ticket that recovers a lost state. While set, every write is refused:
    # against an empty state an apply creates a second copy of what exists.
    unrecovered: str = ""


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
            "could not read kill_switch_service_account from the gcp-bootstrap root. Its state was lost and "
            "is recovered by TF-015 (#2226); until then the proof cannot run."
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
            unrecovered="TF-015 (#2226)",
        ),
        # Dormant since aws1 was destroyed (ADR-063), kept for the portability
        # claim. The provider takes its keys explicitly: the backend's R2 pair
        # is in the same environment, and AWS_* there would be read as AWS's.
        # The Headscale keys were retired with the host (#1353); a re-apply
        # mints new ones first (docs/runbooks/aws1-destroy-replace.md).
        Root(
            "aws",
            apply="guarded",
            secrets={
                "aws_access_key_id": "aws.access_key_id",
                "aws_secret_access_key": "aws.secret_access_key",
            },
            apply_secrets={
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
            unrecovered="TF-015 (#2226)",
        ),
        # Disaster recovery only: how to create the VPS from scratch, never
        # imported against the running one. Its inputs are the defaults in
        # variables.tf; its deployer key is TF-018 (#2230).
        Root("compute", apply="guarded", secrets={"hetzner_api_token": "hetzner.api_key"}),
        # Carries no secret: the hub reads its credentials from Secret Manager.
        Root("gcp", apply="guarded", render=_render_gcp, unrecovered="TF-015 (#2226)"),
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


def subprocess_aws(args: list[str], *, env: dict[str, str]) -> Result:
    """The aws CLI, for the history snapshot. Its stdout is kept; stderr names a refusal."""
    try:
        proc = subprocess.run(["aws", *args], env=env, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        raise RunnerError("the aws CLI is not on PATH; install it with `dotf tools sync`.") from None
    return Result(proc.returncode, proc.stdout + proc.stderr)


def _dig(config: Mapping[str, Any], dotted: str) -> Any:
    node: Any = config
    for part in dotted.split("."):
        if not isinstance(node, Mapping):
            return None
        node = node.get(part)
    return node


def child_env(
    config: Mapping[str, Any],
    root: Root,
    base: Mapping[str, str] | None = None,
    *,
    applying: bool = False,
) -> dict[str, str]:
    """The child's environment: inherited minus AWS_* and TF_* (see INHERITED_TF),
    plus the state bucket's credentials and the root's secrets."""
    env = {
        k: v
        for k, v in (os.environ if base is None else base).items()
        if not k.startswith("AWS_") and (not k.startswith("TF_") or k in INHERITED_TF)
    }
    for name, path in STATE_CREDENTIALS.items():
        value = _dig(config, path)
        if value in (None, ""):
            raise RunnerError(
                f"{path} is empty or absent in SOPS; every root needs it to reach its state in R2. "
                "Mint the state bucket's credentials with `make tf-state-bootstrap` (docs/runbooks/terraform-state.md)."
            )
        env[name] = str(value)
    for variable, path in root.secrets.items():
        value = _dig(config, path)
        if value in (None, ""):
            raise RunnerError(
                f"{path} is empty or absent in SOPS; the {root.name} root needs it as {variable}. "
                f"Set it with: toolkit secrets set {path} --stdin --env common"
            )
        env[f"TF_VAR_{variable}"] = str(value)
    for variable, path in root.apply_secrets.items():
        value = _dig(config, path)
        if value not in (None, ""):
            env[f"TF_VAR_{variable}"] = str(value)
        elif applying:
            raise RunnerError(
                f"{path} is absent in SOPS; a plan of {root.name} runs without it, an apply does not. "
                f"Mint it, then: toolkit secrets set {path} --stdin --env common"
            )
    return env


def _state_env(config: Mapping[str, Any], root_name: str) -> dict[str, str]:
    """The environment of a state-only action: the backend's credentials, no root secret."""
    return child_env(config, Root(root_name, apply="guarded"))


def _remove_legacy_renders(module_dir: Path) -> None:
    for name in LEGACY_RENDERED:
        (module_dir / name).unlink(missing_ok=True)


def _default_config() -> Mapping[str, Any]:
    from toolkit.features.configuration import ConfigurationManager

    return ConfigurationManager("common").get_merged_config()


def _init_args(terraform_dir: Path) -> list[str]:
    """`-reconfigure`: the backend is whatever the generated file says, never a
    previous checkout's cached choice, and never a prompt to migrate."""
    backend = (terraform_dir / terraform_backend.BACKEND_FILE).resolve()
    return ["init", "-input=false", "-reconfigure", f"-backend-config={backend}"]


def output(
    root: str,
    name: str,
    *,
    terraform_dir: Path,
    terraform: Terraform = subprocess_terraform,
    load_config: Callable[[], Mapping[str, Any]] = _default_config,
) -> str:
    """One output of another root, read through the runner (no root secret needed)."""
    module = terraform_dir / root
    chdir = f"-chdir={module}"
    env = _state_env(load_config(), root)
    if terraform([chdir, *_init_args(terraform_dir)], env=env, capture=False, quiet=True).returncode != 0:
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
    aws: AwsCli = subprocess_aws,
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
    if action == "unlock" and len(extra) != 1:
        raise RunnerError("unlock needs exactly one lock id, the one Terraform printed when it refused")
    if action == "restore" and (len(extra) != 1 or not HISTORY_REF.match(extra[0])):
        raise RunnerError("restore needs exactly one history copy as <lineage>/<serial> (see make tf-state-history)")
    if root.apply != "auto" and any(a.lstrip("-").split("=", 1)[0] == "auto-approve" for a in extra):
        raise RunnerError(f"the {root.name} root never applies or destroys unattended; drop -auto-approve")
    if any(_turns_off_the_lock(a) for a in extra):
        raise RunnerError("the runner never turns off the state lock; two writers would race on one state")

    module = terraform_dir / root.name
    _refuse_a_state_the_backend_does_not_hold(root, action, module)
    state_only = action in STATE_ONLY
    config = load_config()
    env = _state_env(config, root.name) if state_only else child_env(config, root, applying=action == "apply")
    history = _History(root.name, config, aws, env)
    if action == "history":
        return history.list()
    if outputs is None:

        def outputs(other: str, name: str) -> str:
            return output(other, name, terraform_dir=terraform_dir, terraform=terraform, load_config=lambda: config)

    _remove_legacy_renders(module)
    staged = _stage_for_migration(root, module) if action == "migrate" else None
    try:
        return _run_in(
            root, action, module, terraform_dir, config, env, history, terraform, outputs, extra, allow_destroy, allowed
        )
    finally:
        # A migration that did not finish leaves the file where it was found.
        if staged is not None and staged.exists():
            staged.rename(module / LOCAL_STATE)


def _run_in(
    root: Root,
    action: str,
    module: Path,
    terraform_dir: Path,
    config: Mapping[str, Any],
    env: dict[str, str],
    history: _History,
    terraform: Terraform,
    outputs: Outputs,
    extra: Sequence[str],
    allow_destroy: bool,
    allowed: Sequence[str],
) -> int:
    chdir = f"-chdir={module}"
    state_only = action in STATE_ONLY
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

        rc = tf(*_init_args(terraform_dir), quiet=True).returncode
        if rc != 0:
            return rc
        if action == "unlock":
            # The lock object only: the state is not read or written.
            return tf("force-unlock", "-force", extra[0]).returncode
        if action not in WRITES:
            return _read(tf, root, action, var_args, extra)
        # Before: a write must not start from a state history does not hold,
        # which is also how a snapshot missed by an earlier run is caught up.
        rc = history.snapshot(tf, Path(tmp))
        if rc != 0:
            from toolkit.core.logging import logger

            logger.error(f"{root.name}: the state could not be copied to history; nothing was changed.")
            return rc
        if action == "restore":
            rc = _restore(tf, root, history, Path(tmp), extra[0])
        else:
            rc = _write(tf, root, action, module, Path(tmp), var_args, extra, allow_destroy, allowed)
        # After, whatever the write returned: a failed apply can still have
        # written a new serial.
        after = history.snapshot(tf, Path(tmp))
        return rc or after


def _refuse_a_state_the_backend_does_not_hold(root: Root, action: str, module: Path) -> None:
    for name in (LOCAL_STATE, MIGRATING_STATE):
        if (module / name).exists() and action != "migrate":
            raise RunnerError(
                f"{module / name} is a local state, and the {root.name} root keeps its state in R2. "
                f"Running against R2 now would ignore it. Move it first: make tf-state-migrate ROOT={root.name}"
            )
    if root.unrecovered and action in ("apply", "destroy", "untaint", "restore"):
        raise RunnerError(
            f"the {root.name} root's state was lost and is not recovered yet ({root.unrecovered}). "
            "Against an empty state Terraform does not know what exists, so an apply would create it again. "
            "A plan is allowed and shows what the import must cover."
        )


def _read(tf: Callable[..., Result], root: Root, action: str, var_args: list[str], extra: Sequence[str]) -> int:
    if action == "plan":
        return tf("plan", "-input=false", *var_args, *extra).returncode
    if action == "output":
        return tf("output", *extra).returncode
    # state-list: resource addresses only. `state show` and `show` are not
    # offered: they print attribute values, and a state holds secrets in clear.
    return tf("state", "list", *extra).returncode


def _write(
    tf: Callable[..., Result],
    root: Root,
    action: str,
    module: Path,
    tmp: Path,
    var_args: list[str],
    extra: Sequence[str],
    allow_destroy: bool,
    allowed: Sequence[str],
) -> int:
    if action == "migrate":
        return _migrate(tf, root, module)
    if action == "untaint":
        return tf("untaint", *extra).returncode
    if action == "destroy":
        auto = ("-auto-approve",) if root.apply == "auto" else ()
        return tf("destroy", *auto, *var_args, *extra).returncode
    if root.apply == "interactive":
        return tf("apply", *var_args, *extra).returncode
    if root.apply == "auto":
        return tf("apply", "-auto-approve", *var_args, *extra).returncode
    return _guarded_apply(tf, tmp, var_args, extra, allow_destroy, allowed)


class AwsCli(Protocol):
    def __call__(self, args: list[str], *, env: dict[str, str]) -> Result: ...


def _turns_off_the_lock(arg: str) -> bool:
    """`-lock=false` and its spellings. A bare `-lock` is a Go boolean flag set to true."""
    name, given, value = arg.lstrip("-").partition("=")
    return name == "lock" and bool(given) and value not in ("true", "1")


def _pull(tf: Callable[..., Result]) -> dict[str, Any] | None:
    """The remote state, parsed in memory. None when the backend holds none yet.

    Never printed and never put in a message: a state holds secrets in clear.
    """
    pulled = tf("state", "pull", capture=True)
    if pulled.returncode != 0:
        raise RunnerError("terraform state pull failed; the backend could not be read.")
    if not pulled.stdout.strip():
        return None
    try:
        return dict(json.loads(pulled.stdout))
    except ValueError:
        raise RunnerError("terraform state pull returned something that is not a state.") from None


def _shape(state: Mapping[str, Any]) -> tuple[str, int, int]:
    return str(state.get("lineage", "")), int(state.get("serial", 0)), len(state.get("resources") or [])


def _address(resource: Mapping[str, Any]) -> str:
    """`module.x.data.type.name`, the form `terraform state list` prints."""
    parts = [str(resource.get("module") or ""), "data" if resource.get("mode") == "data" else ""]
    return ".".join(p for p in [*parts, str(resource.get("type", "")), str(resource.get("name", ""))] if p)


def _content(state: Mapping[str, Any]) -> dict[str, str]:
    """Each resource address, and `outputs`, mapped to a canonical rendering of what it holds."""
    held = {_address(r): json.dumps(r, sort_keys=True) for r in state.get("resources") or []}
    return {**held, "outputs": json.dumps(state.get("outputs") or {}, sort_keys=True)}


def _differing(local: Mapping[str, Any], remote: Mapping[str, Any]) -> list[str]:
    """The addresses whose content differs or exists on one side only. Names, never values."""
    mine, theirs = _content(local), _content(remote)
    return sorted(a for a in mine.keys() | theirs.keys() if mine.get(a) != theirs.get(a))


def _persisted(state: Mapping[str, Any] | None) -> bool:
    """Serial 0 is the empty state a backend answers before anything was written to it."""
    return state is not None and int(state.get("serial", 0)) >= 1


def _arrived(local: Mapping[str, Any], remote: Mapping[str, Any] | None) -> bool:
    """R2 holds what the local state holds: every resource and every output, as they are.

    Lineage and serial are not compared. Both are Terraform's business, and it
    does not keep them across a migration: against an untouched S3 key, `state
    pull` answers an empty state with no lineage at serial 0, and `state push`
    into it imports the resources under a lineage minted for that write, at
    serial 1 (measured on msi, 2026-10-13). A
    gate on lineage refused a migration that had worked, and then every retry
    was refused by Terraform itself, across lineages.

    The remote must also have been written: a state that holds nothing has the
    content of the empty answer an untouched key gives.
    """
    return remote is not None and _persisted(remote) and not _differing(local, remote)


class _History:
    """`history/<root>/<lineage>/<serial>.tfstate` in the state bucket.

    The prefix is under a bucket lock rule, and every put is conditional
    (`If-None-Match: *`), so a serial once copied can be neither overwritten nor
    deleted. A put that finds its key already there is the same state: lineage
    and serial name one state, and Terraform never reuses them.
    """

    def __init__(self, root_name: str, config: Mapping[str, Any], aws: AwsCli, env: Mapping[str, str]) -> None:
        from toolkit.features.backup_node_credentials import _s3_env

        self.root_name = root_name
        self.config = config
        self.aws = aws
        # The child's environment, already stripped of the shell's AWS_* and
        # TF_*, without the root's variables, plus what the CLI needs for R2.
        self.env = {
            **{k: v for k, v in env.items() if not k.startswith("TF_VAR_")},
            **_s3_env(env["AWS_ACCESS_KEY_ID"], env["AWS_SECRET_ACCESS_KEY"]),
        }

    def _prefix(self) -> str:
        return f"{self.config['terraform']['state']['history_prefix']}{self.root_name}/"

    def _s3api(self, op: str, *args: str) -> Result:
        return self.aws(
            [
                "--endpoint-url",
                self.config["backup"]["r2"]["endpoint"],
                "s3api",
                op,
                "--bucket",
                self.config["terraform"]["state"]["bucket"],
                *args,
            ],
            env=self.env,
        )

    def list(self) -> int:
        """Every copy of this root: key and date. Keys only, never a body."""
        listed = self._s3api(
            "list-objects-v2",
            "--prefix",
            self._prefix(),
            "--query",
            "Contents[].[Key,LastModified]",
            "--output",
            "text",
        )
        print(listed.stdout, end="")
        return listed.returncode

    def fetch(self, ref: str, tmp: Path) -> dict[str, Any]:
        """The copy named `<lineage>/<serial>`, parsed in memory; its file never outlives the call."""
        key = f"{self._prefix()}{ref}.tfstate"
        body = tmp / "restore-source.tfstate"
        # Created private before the CLI writes into it: it opens the path for
        # writing and keeps its mode, so the body is never readable by others.
        os.close(os.open(body, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        try:
            got = self._s3api("get-object", "--key", key, str(body))
            if got.returncode != 0:
                raise RunnerError(f"history has no copy {ref} of {self.root_name} ({key}): {got.stdout.strip()[-200:]}")
            try:
                return dict(json.loads(body.read_text(encoding="utf-8")))
            except ValueError:
                raise RunnerError(f"{key} is not a Terraform state; nothing was pushed.") from None
        finally:
            body.unlink(missing_ok=True)

    def snapshot(self, tf: Callable[..., Result], tmp: Path) -> int:
        from toolkit.core.logging import logger

        state = _pull(tf)
        # Serial 0 is the empty state a backend answers before anything was
        # written to it: there is nothing to keep, and a locked copy is forever.
        if state is None or not _persisted(state):
            return 0
        lineage, serial, _ = _shape(state)
        key = f"{self._prefix()}{lineage}/{serial}.tfstate"
        body = tmp / "history.tfstate"
        fd = os.open(body, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(state, fh)
        try:
            put = self._s3api("put-object", "--key", key, "--body", str(body), "--if-none-match", "*")
        finally:
            body.unlink(missing_ok=True)
        if put.returncode == 0:
            logger.info(f"{self.root_name}: state serial {serial} copied to history.")
            return 0
        # The key exists, so this lineage and serial are already copied. R2
        # checks the lock rule before If-None-Match, so a key old enough to be
        # locked answers ObjectLockedByBucketPolicy instead (measured 2026-10-13).
        if any(code in put.stdout for code in ("PreconditionFailed", "ObjectLockedByBucketPolicy")):
            return 0
        logger.error(f"{self.root_name}: copying serial {serial} to {key} failed: {put.stdout.strip()[-300:]}")
        return 1


def _stage_for_migration(root: Root, module: Path) -> Path | None:
    """Move the local file out of init's sight, under a name the guard still refuses.

    Returns the staged path, or None when there is nothing to move (already
    migrated, or nothing to migrate: `_migrate` says which).
    """
    local, staged, moved = module / LOCAL_STATE, module / MIGRATING_STATE, module / MIGRATED_STATE
    if local.exists() and staged.exists():
        raise RunnerError(
            f"both {local.name} and {staged.name} exist in {module}; which one is current is not decidable here."
        )
    if (local.exists() or staged.exists()) and moved.exists():
        raise RunnerError(f"{moved} already exists; refusing to overwrite the last pre-remote copy.")
    if local.exists():
        local.rename(staged)
    return staged if staged.exists() else None


def _migrate(tf: Callable[..., Result], root: Root, module: Path) -> int:
    """Move a root's local state into R2, without `-force`, and prove it arrived.

    A remote that already holds a written state with other content is refused
    here, before any push, rather than left to `state push`: its lineage and
    serial check is not a guarantee once the remote holds no resources. A remote
    that already holds this content is not pushed again: that is a migration
    whose rename did not happen, and finishing it is the rename. After the push the
    remote is read back and compared by content; only then is the local file
    renamed, which is what lets the next run start.

    Once renamed, the pre-remote copy is the source only while R2 holds no
    written state for the root, so a rename that ran without a write behind it
    is finished by the next run. Otherwise R2 is the state and the run is a no-op.
    """
    from toolkit.core.logging import logger

    staged, moved = module / MIGRATING_STATE, module / MIGRATED_STATE
    source = staged if staged.exists() else moved if moved.exists() else None
    if source is None:
        raise RunnerError(f"{root.name} has no local state at {module / LOCAL_STATE}; there is nothing to migrate.")
    remote = _pull(tf)
    if source == moved and _persisted(remote):
        logger.info(f"{root.name}: already migrated ({moved.name} is the pre-remote copy).")
        return 0
    try:
        state = json.loads(source.read_text(encoding="utf-8"))
    except ValueError:
        raise RunnerError(f"{source} is not a Terraform state; nothing was pushed.") from None
    if not _arrived(state, remote):
        if remote is not None and _persisted(remote):
            logger.error(
                f"{root.name}: R2 already holds a written state that differs from the local file at "
                f"{', '.join(_differing(state, remote))}. Nothing was pushed; the local file is kept."
            )
            return 1
        rc = tf("state", "push", str(source)).returncode
        if rc != 0:
            return rc
    remote = _pull(tf)
    if remote is None or not _arrived(state, remote):
        differing = _differing(state, remote) if _persisted(remote) and remote is not None else ["(no written state)"]
        logger.error(
            f"{root.name}: after the push R2 differs from the local file at {', '.join(differing)}. "
            f"The local file is kept."
        )
        return 1
    if source == staged:
        staged.rename(moved)
    lineage, serial, count = _shape(remote)
    logger.info(
        f"{root.name}: {count} resources are in R2, lineage {lineage} serial {serial}; the local file is {moved.name}."
    )
    return 0


def _restore(tf: Callable[..., Result], root: Root, history: _History, tmp: Path, ref: str) -> int:
    """Write an old copy back as the newest state, without `-force`.

    A restore is a new write of old content, like a revert: it takes the serial
    after the current one, so `state push` accepts it as a newer state of the
    same lineage, and the history key it lands on has never been used. Pushing
    the copy at its own serial would need `-force`, and its after-snapshot would
    collide with the copy already filed under that serial.
    """
    from toolkit.core.logging import logger

    lineage, serial = ref.split("/")
    old = history.fetch(ref, tmp)
    if (str(old.get("lineage")), int(old.get("serial", -1))) != (lineage, int(serial)):
        raise RunnerError(f"the history copy {ref} does not hold the state its key names; nothing was pushed.")
    current = _pull(tf)
    if current is not None and current.get("lineage") != lineage:
        raise RunnerError(
            f"{root.name} holds lineage {current.get('lineage')}, the copy {lineage}: another state, "
            "which only `-force` would replace. The runner never passes it; nothing was pushed."
        )
    restored = {**old, "serial": int(current["serial"]) + 1 if current is not None else int(serial)}
    body = tmp / "restore.tfstate"
    fd = os.open(body, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(restored, fh)
    try:
        rc = tf("state", "push", str(body)).returncode
    finally:
        body.unlink(missing_ok=True)
    if rc != 0:
        return rc
    if not _arrived(restored, _pull(tf)):
        logger.error(f"{root.name}: R2 does not hold the restored copy {ref} after the push.")
        return 1
    logger.info(f"{root.name}: copy {ref} restored as serial {restored['serial']}.")
    return 0


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
