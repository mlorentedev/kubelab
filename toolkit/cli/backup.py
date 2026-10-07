"""Backup pipeline commands (BACKUP-044)."""

from pathlib import Path
from typing import Annotated, Optional

import typer

from toolkit.core.logging import logger
from toolkit.features.backup_destination import verify_destination

app = typer.Typer(
    name="backup",
    help="Offsite backup pipeline (Cloudflare R2 / restic).",
    no_args_is_help=True,
)


@app.command("verify-destination")
def verify_destination_cmd(
    env: Annotated[
        str,
        typer.Option("--env", "-e", help="Environment whose merged config is used"),
    ] = "prod",
    project_root: Annotated[
        Optional[Path],
        typer.Option("--project-root", help="Repo root (defaults to auto-detection)"),
    ] = None,
) -> None:
    """Prove the R2 destination is usable: scope, reach, and a write/read/delete round-trip.

    Writes 1 KB of throwaway data under `_smoketest/` and removes it. Safe to run
    against a live destination, and worth running before trusting a backup to it —
    a token without delete permission lets backups look healthy until the bucket
    fills and retention turns out never to have retained anything.
    """
    if not verify_destination(env=env, project_root=project_root):
        raise typer.Exit(code=1)


@app.command("verify-restic")
def verify_restic_cmd(
    node: Annotated[
        str,
        typer.Option("--node", "-n", help="Repository name (one repository per node)"),
    ] = "_smoketest-probe",
    env: Annotated[str, typer.Option("--env", "-e", help="Environment whose merged config is used")] = "prod",
    keep: Annotated[bool, typer.Option("--keep", help="Do not delete the probe repository afterwards")] = False,
    project_root: Annotated[Optional[Path], typer.Option("--project-root", help="Repo root")] = None,
) -> None:
    """Prove restic can create, use and verify a repository in R2.

    Runs the whole lifecycle — init, backup, snapshots, `restic check` — against a
    throwaway repository, then removes it. "The bucket accepts objects" and
    "restic works here" are different claims; only the second one matters.
    """
    from toolkit.features.backup_destination import verify_restic

    if not verify_restic(node=node, env=env, project_root=project_root, keep=keep):
        raise typer.Exit(code=1)


@app.command("mint-node-tokens")
def mint_node_tokens_cmd(
    env: Annotated[str, typer.Option("--env", "-e", help="Only prod: the node keys live in prod.enc.yaml")] = "prod",
    node: Annotated[Optional[str], typer.Option("--node", "-n", help="One backup.sources node; default all")] = None,
    rotate: Annotated[bool, typer.Option("--rotate", help="Replace existing pairs and revoke the old tokens")] = False,
    watcher_only: Annotated[
        bool, typer.Option("--watcher-only", help="Only the watcher's read pair; no node token is touched")
    ] = False,
) -> None:
    """Mint each node's own R2 token and restic password into SOPS (BACKUP-057).

    Each token is Object Read & Write on `kubelab-backup-<node>` only. It is
    verified by consequence before it is stored (it lists its own bucket and is
    refused on another node's), and nothing is ever printed. Idempotent: an
    existing pair is kept unless --rotate is given. A restic password is never
    replaced, --rotate or not.
    """
    from toolkit.features.backup_node_credentials import SECRETS_ENV, mint_all

    if env != SECRETS_ENV:
        logger.error(f"The node keys live in {SECRETS_ENV}.enc.yaml; --env {env} is not supported.")
        raise typer.Exit(code=1)
    if node and watcher_only:
        logger.error("--node and --watcher-only name different tokens; pass one.")
        raise typer.Exit(code=1)
    if not mint_all(node=node, rotate=rotate, watcher_only=watcher_only):
        raise typer.Exit(code=1)


@app.command("generate-password")
def generate_password_cmd(
    env: Annotated[str, typer.Option("--env", "-e", help="SOPS file to write to")] = "common",
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing password")] = False,
) -> None:
    """Generate the restic repository password and store it in SOPS.

    The value is never printed. Read it once with
    `make secrets-show KEY=backup.restic_password SECRETS_ENV=common` to place a
    copy in the offsite escrow — without that second copy the password is
    reachable only through an age key that a disaster destroys, which is the one
    scenario the backups exist for.

    Refuses to overwrite silently: replacing this value without running
    `restic key add` first locks you out of every existing snapshot.
    """
    import secrets as _secrets

    from toolkit.features.secrets_manager import SecretsManager

    key = "backup.restic_password"
    manager = SecretsManager()

    if manager.show_secret(env, key) and not force:
        logger.error(
            f"'{key}' already exists in {env}. Overwriting it locks you out of every existing "
            "snapshot unless `restic key add` ran first. Pass --force only if you mean it."
        )
        raise typer.Exit(code=1)

    if not manager.set_secret(env, key, _secrets.token_urlsafe(48)):
        logger.error(f"Failed to write '{key}' to {env}")
        raise typer.Exit(code=1)

    logger.success(f"Generated '{key}' in {env} (value not printed)")
    logger.warning("Copy it to the offsite escrow now: make secrets-show KEY=backup.restic_password SECRETS_ENV=common")


@app.command("coverage")
def coverage_cmd(
    env: Annotated[str, typer.Option("--env", "-e", help="Environment whose merged config is used")] = "prod",
    project_root: Annotated[Optional[Path], typer.Option("--project-root", help="Repo root")] = None,
) -> None:
    """Report the newest snapshot for every node in `backup.sources`, read from R2.

    BACKUP-044 AC1 asks for this to be answered "from a machine that is not the
    source node", and that constraint is the point: every other backup control
    runs ON the node it checks, so it shares the node's fate. This asks the
    destination, works with the homelab powered off, and exits non-zero when a
    declared node has no repository or no snapshot.

    It reports snapshot AGE without judging it — the two node classes have
    different expectations, and that judgement belongs to the coverage monitor
    in Uptime Kuma, which knows the class.
    """
    from toolkit.features.backup_destination import coverage

    if not coverage(env=env, project_root=project_root):
        raise typer.Exit(code=1)


@app.command("drill-postgres")
def drill_postgres_cmd(
    env: Annotated[str, typer.Option("--env", "-e", help="Environment whose merged config is used")] = "prod",
    project_root: Annotated[Optional[Path], typer.Option("--project-root", help="Repo root")] = None,
) -> None:
    """Restore the newest Postgres dump from R2 into a scratch container and check it is complete.

    Passes when the dump carries its trailer, every live database and table exists
    in the restore, and no table with rows live came back empty. Prints names and
    counts only, and removes the container and the dump on every exit path.
    """
    from toolkit.features.postgres_drill import drill_postgres

    if not drill_postgres(env=env, project_root=project_root):
        raise typer.Exit(code=1)


_HOST_HELP = "Run the drill on this homelab node, from the commit this tree is at (it must be pushed)"
_INPUTS_HELP = "Read resolved inputs as JSON on stdin and read no config (the host side of --host)"


def _drill(drill: str, *, env: str, project_root: Optional[Path], host: Optional[str], inputs_stdin: bool) -> bool:
    """Dispatch a drill: here, on `host` (BACKUP-071), or as the host side reading its inputs from stdin."""
    import sys

    from toolkit.features import drill_remote

    if host and inputs_stdin:
        logger.error("drill: --host and --inputs-stdin are the two ends of one run; pass one")
        return False
    if inputs_stdin:
        return drill_remote.run_from_stdin(drill, sys.stdin.read())
    if host:
        return drill_remote.drill_on_host(drill, env=env, host=host, project_root=project_root)
    module = drill_remote.module_for(drill)
    return bool(getattr(module, f"drill_{drill}")(env=env, project_root=project_root))


@app.command("drill-gitea")
def drill_gitea_cmd(
    env: Annotated[str, typer.Option("--env", "-e", help="Environment whose merged config is used")] = "prod",
    project_root: Annotated[Optional[Path], typer.Option("--project-root", help="Repo root")] = None,
    host: Annotated[Optional[str], typer.Option("--host", help=_HOST_HELP)] = None,
    inputs_stdin: Annotated[bool, typer.Option("--inputs-stdin", help=_INPUTS_HELP)] = False,
) -> None:
    """Restore the newest Gitea capture from R2 into a scratch server and check it brings the forge back.

    Passes when every restored repository passes `git fsck --full`, the pinned
    image starts on the restored data with no network, and every repository live
    lists is restored with branch heads live knows. Prints names and counts only,
    and removes the container, its volumes and the data on every exit path.
    """
    if not _drill("gitea", env=env, project_root=project_root, host=host, inputs_stdin=inputs_stdin):
        raise typer.Exit(code=1)


@app.command("drill-headscale")
def drill_headscale_cmd(
    env: Annotated[str, typer.Option("--env", "-e", help="Environment whose merged config is used")] = "prod",
    project_root: Annotated[Optional[Path], typer.Option("--project-root", help="Repo root")] = None,
    host: Annotated[Optional[str], typer.Option("--host", help=_HOST_HELP)] = None,
    inputs_stdin: Annotated[bool, typer.Option("--inputs-stdin", help=_INPUTS_HELP)] = False,
) -> None:
    """Restore the newest Headscale capture from R2 into a scratch container and check it is complete.

    Passes when the database is intact, both server keys match live, the restored
    server starts with no network, and every node and user live had at snapshot
    time is in it. Prints names and ids only, never a key, and removes the
    container and the restore on every exit path.
    """
    if not _drill("headscale", env=env, project_root=project_root, host=host, inputs_stdin=inputs_stdin):
        raise typer.Exit(code=1)


@app.command("drill-apps")
def drill_apps_cmd(
    env: Annotated[str, typer.Option("--env", "-e", help="Environment whose merged config is used")] = "prod",
    project_root: Annotated[Optional[Path], typer.Option("--project-root", help="Repo root")] = None,
) -> None:
    """Restore the newest Authelia and n8n captures from R2 and check the SOPS keys open them.

    Passes when each database is intact, every durable row live had at snapshot
    time is in it, and the image live runs opens it with the SOPS key and no
    network. Reads live from the files on the node, never through the apps'
    CLIs. Prints table names, ids and counts only, and removes the containers
    and the restores on every exit path.
    """
    from toolkit.features.app_drill import drill_apps

    if not drill_apps(env=env, project_root=project_root):
        raise typer.Exit(code=1)


@app.command("restore-window")
def restore_window_cmd(
    deployment: Annotated[str, typer.Option("--app", help="Deployment whose data is being restored, e.g. n8n")],
    env: Annotated[str, typer.Option("--env", "-e", help="staging or prod")] = "prod",
    end: Annotated[bool, typer.Option("--end", help="Close the window (restore git's sync policy and sync)")] = False,
    project_root: Annotated[Optional[Path], typer.Option("--project-root", help="Repo root")] = None,
) -> None:
    """Pause an env's Argo CD auto-sync and stop one app, so its data can be replaced (BACKUP-070).

    Opening sets `automated.enabled: false` on `kubelab-<env>`, records who holds
    the window, scales the Deployment to zero and waits until no pod mounts its
    claims. While it is open, that env receives no merges. `--end` restores the
    sync policy declared in git, triggers a sync, and waits for Synced/Healthy
    and the app's replicas. Closing with no window open says so and exits 0.
    """
    import getpass
    import socket

    from toolkit.features.k8s_kubeconfig import output_path
    from toolkit.features.restore_window import WindowError, close_window, open_window

    if env not in ("staging", "prod"):
        logger.error(f"--env must be staging or prod, not '{env}'")
        raise typer.Exit(code=1)
    root = Path(project_root or Path.cwd())
    hub, spoke = str(output_path("hub")), str(output_path(env))
    try:
        if end:
            logger.section(f"restore window — closing on kubelab-{env}")
            replaced = close_window(
                env=env,
                applications_dir=root / "infra/k8s/argocd/applications",
                hub_kubeconfig=hub,
                spoke_kubeconfig=spoke,
            )
            if replaced is None:
                logger.info(f"no window open on kubelab-{env}; nothing to close")
                return
            logger.info(f"replaced sync policy: {replaced}")
            logger.success(f"window closed: kubelab-{env} syncs from git again and the app is back")
            return
        logger.section(f"restore window — opening on kubelab-{env} for {deployment}")
        replaced = open_window(
            env=env,
            deployment=deployment,
            hub_kubeconfig=hub,
            spoke_kubeconfig=spoke,
            holder=f"{getpass.getuser()}@{socket.gethostname()}",
        )
    except WindowError as exc:
        logger.error(str(exc))
        raise typer.Exit(code=1) from exc
    logger.info(f"replaced sync policy: {replaced}")
    logger.success(
        f"window open: {deployment} is at zero and kubelab-{env} will not sync. "
        f"Close it with `make restore-window APP={deployment} ENV={env} END=1`."
    )


@app.command("health-check")
def health_check_cmd(
    env: Annotated[str, typer.Option("--env", "-e", help="Environment whose merged config is used")] = "prod",
    notify: Annotated[bool, typer.Option("--notify/--no-notify", help="Dispatch notification to Slack")] = True,
    project_root: Annotated[Optional[Path], typer.Option("--project-root", help="Repo root")] = None,
) -> None:
    """Run full R2 destination verification + fleet coverage check and notify Slack.

    Executes verify-destination (scope, reach, write/read/delete round-trip) and
    coverage (fleet snapshot checks), then dispatches a structured SRE report
    to Slack #ops-log (on success) or #alerts (on failure).
    """
    from toolkit.features.r2_backup_health import run_r2_backup_health_check

    if not run_r2_backup_health_check(env=env, notify=notify, project_root=project_root):
        raise typer.Exit(code=1)
