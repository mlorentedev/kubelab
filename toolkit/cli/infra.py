"Infrastructure management commands for deployment and status checking."

import os
from pathlib import Path
from typing import Annotated

import typer
import yaml

from toolkit.config.constants import MESSAGES, NETWORK_DEFAULTS, PATH_STRUCTURES
from toolkit.config.settings import get_settings, settings
from toolkit.core.logging import console, logger
from toolkit.features import command
from toolkit.features.argo_manager import (
    ApplicationNotFoundError,
    HubUnreachableError,
)
from toolkit.features.argo_manager import (
    check_drift as argo_check_drift_feature,
)
from toolkit.features.argo_manager import (
    set_revision as argo_set_revision_feature,
)
from toolkit.features.k8s_kubeconfig import output_path
from toolkit.features.k8s_render import BootstrapEntry, render_and_apply
from toolkit.features.validation import (
    confirm_dangerous_operation,
    validate_environment_config,
)

app = typer.Typer(
    name="infra",
    help="Infrastructure deployment and status commands",
    no_args_is_help=True,
)

ansible_app = typer.Typer(
    name="ansible",
    help="Ansible management commands",
    no_args_is_help=True,
)

terraform_app = typer.Typer(
    name="terraform",
    help="Terraform management commands",
    no_args_is_help=True,
)

k8s_app = typer.Typer(
    name="k8s",
    help="Kubernetes management commands",
    no_args_is_help=True,
)

k8s_access_app = typer.Typer(
    name="access",
    help="Cluster-access transport (ADR-052): bring up/tear down/inspect the local->apiserver tunnel",
    no_args_is_help=True,
)

argo_app = typer.Typer(
    name="argo",
    help="Argo CD hub management (targetRevision swap, etc.)",
    no_args_is_help=True,
)

headscale_app = typer.Typer(
    name="headscale",
    help="Headscale VPN ACL policy + mesh probe (ADR-041)",
    no_args_is_help=True,
)

n8n_app = typer.Typer(
    name="n8n",
    help="n8n workflow import (TOOL-009) + notification-fabric smoke (NOTIFY-001)",
    no_args_is_help=True,
)

app.add_typer(ansible_app, name="ansible")
app.add_typer(terraform_app, name="terraform")
app.add_typer(k8s_app, name="k8s")
k8s_app.add_typer(k8s_access_app, name="access")
app.add_typer(argo_app, name="argo")
app.add_typer(headscale_app, name="headscale")
app.add_typer(n8n_app, name="n8n")


@headscale_app.command("policy-check")
def headscale_policy_check() -> None:
    """Render policy.hujson from the SSOT and validate it with `headscale policy check` (Docker)."""
    from toolkit.scripts.render_headscale_policy import policy_check, render_policy

    rc = policy_check(render_policy())
    if rc != 0:
        raise typer.Exit(rc)


@headscale_app.command("probe")
def headscale_probe() -> None:
    """Probe the preserved mesh flows after a policy reload (auto-revert gate, ADR-041)."""
    from toolkit.scripts.headscale_probe import run_probe

    rc = run_probe()
    if rc != 0:
        raise typer.Exit(rc)


@argo_app.command("set-revision")
def argo_set_revision(
    application: Annotated[str, typer.Option("--app", help="Argo CD Application name")],
    revision: Annotated[str, typer.Option("--rev", help="Git revision (branch, tag, sha)")],
    kubeconfig: Annotated[
        str,
        typer.Option(
            "--kubeconfig",
            help="Hub kubeconfig path (env: KUBECONFIG_HUB)",
            envvar="KUBECONFIG_HUB",
        ),
    ] = str(output_path("hub")),
    namespace: Annotated[str, typer.Option("--namespace", "-n")] = "argocd",
) -> None:
    """Patch an Argo CD Application's spec.source.targetRevision.

    Encapsulates the preview-per-PR and patch-back operations so they
    stop being manual kubectl calls.
    """
    logger.section(f"Argo set-revision — {application} → {revision}")
    try:
        result = argo_set_revision_feature(
            app=application,
            rev=revision,
            kubeconfig=kubeconfig,
            namespace=namespace,
        )
    except ApplicationNotFoundError as exc:
        logger.error(str(exc))
        raise typer.Exit(1) from exc

    logger.info(f"targetRevision: {result.old_revision} → {result.new_revision}")
    logger.info(f"sync status: {result.sync_status}")
    logger.success("Application patched")


@argo_app.command("spoke-url")
def argo_spoke_url(
    env: Annotated[str, typer.Option("--env", "-e", help="Spoke environment, e.g. staging or prod")],
) -> None:
    """Print one spoke's K3s apiserver URL, resolved from the SSOT (#1215).

    Exists so a Makefile target can stop re-deriving
    `argocd.spokes.<env>.node -> tailscale_ip -> k3s.api_port` with its own
    inline `python -c "import yaml; ..."`. See
    toolkit/features/argocd_spokes.py for why the node lookup is awkward.

    Reads the PLAINTEXT common.yaml directly, never SOPS -- the same rule
    `config get` follows, and here it is load-bearing rather than tidy. The
    caller is `$(...)` in a shell, so EVERY byte this process writes to stdout
    lands inside the variable. `ConfigurationManager` prints
    "[WARNING] SOPS is not installed" to stdout when sops is absent, which on a
    runner without it silently produced a two-line warning banner followed by
    the URL -- and `register-spoke` would have written that whole blob into a
    cluster secret's server field. Caught by CI on #1223, never seen locally,
    because a workstation has sops installed and a runner does not.

    Nothing in this derivation is a secret, so the SOPS path bought nothing in
    exchange for that hazard.
    """
    import yaml

    from toolkit.features import argocd_spokes

    common = settings.project_root / "infra" / "config" / "values" / "common.yaml"
    try:
        url = argocd_spokes.apiserver_url(yaml.safe_load(common.read_text()), env)
    except KeyError as exc:
        logger.error(str(exc))
        raise typer.Exit(1) from exc

    # print(), not logger: the caller is `$(...)` in a shell and wants the
    # bare URL on stdout with no formatting, prefix or colour.
    print(url)


@argo_app.command("check-drift")
def argo_check_drift(
    kubeconfig: Annotated[
        str,
        typer.Option(
            "--kubeconfig",
            help="Hub kubeconfig path (env: KUBECONFIG_HUB)",
            envvar="KUBECONFIG_HUB",
        ),
    ] = str(output_path("hub")),
    applications_dir: Annotated[
        str, typer.Option("--dir", help="Directory of Argo CD Application manifests")
    ] = "infra/k8s/argocd/applications",
) -> None:
    """Compare live Argo CD Applications against their git manifests (#1016).

    A manifest changed in git is a claim, not a deployed fact, until this
    reads back the live object. Exit 0 = clean, 1 = drift found, 2 = the hub
    could not be reached — the last case is deliberately distinct from
    "clean": a check that cannot run must never report success.
    """
    logger.section("Argo CD Application drift check")
    try:
        result = argo_check_drift_feature(applications_dir=applications_dir, kubeconfig=kubeconfig)
    except HubUnreachableError as exc:
        logger.error(f"CANNOT CHECK: {exc}")
        raise typer.Exit(2) from exc

    if result.clean:
        logger.success("No drift — live Applications match git.")
        return

    logger.error("Drift detected between live Argo CD Applications and git:")
    console.print(result.diff)
    logger.error("Fix with: make deploy-apps")
    raise typer.Exit(1)


@argo_app.command("unregister-spoke")
def argo_unregister_spoke(
    env: Annotated[str, typer.Option("--env", "-e", help="Spoke environment to detach")],
    kubeconfig: Annotated[
        str,
        typer.Option("--kubeconfig", help="Kubeconfig of the hub to detach FROM (required: two hubs exist)"),
    ],
    remove_shared_rbac: Annotated[
        bool,
        typer.Option(
            "--remove-shared-rbac",
            help="Also delete the spoke's RBAC. Correct ONLY when no other hub reconciles it.",
        ),
    ] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print the plan and change nothing")] = False,
) -> None:
    """Detach ONE hub from ONE spoke, without pruning the spoke.

    `--kubeconfig` is required rather than defaulted: two hubs are live during
    the migration, and the old global default resolves to the hub being migrated
    TO -- so detaching the old one would delete the new one's credential.

    The Application's `resources-finalizer.argocd.argoproj.io` is stripped
    BEFORE the Application is deleted. Without that the delete CASCADES and
    prunes every resource the Application manages, which is the whole spoke
    namespace.
    """
    from toolkit.features.spoke_unregistration import unregister_spoke

    logger.section(f"Detaching {env} from the hub at {kubeconfig}")
    steps = unregister_spoke(env, Path(kubeconfig), remove_shared_rbac, dry_run)
    for i, step in enumerate(steps, 1):
        prefix = "would" if dry_run else "did"
        logger.info(f"  {i}. {prefix}: {step.what}")
    if dry_run:
        logger.warning("dry-run — nothing was changed")
        return
    logger.success(f"{env} detached. The spoke's workloads were not touched.")


@argo_app.command("check-spokes")
def argo_check_spokes(
    kubeconfig: Annotated[
        str,
        typer.Option(
            "--kubeconfig",
            help="Hub kubeconfig path (env: KUBECONFIG_HUB)",
            envvar="KUBECONFIG_HUB",
        ),
    ] = str(output_path("hub")),
) -> None:
    """Probe every spoke with the credential THE HUB stores (#1277).

    The previous check read the operator's own per-env kubeconfig, so it
    measured whether YOU can reach the spoke -- true whenever you are running
    the command -- and never exercised the hub's credential at all. It printed
    `OK (registered + reachable)` for a hub that could not authenticate, every
    time it ran, for that hub's whole life.

    Four outcomes, because "the spoke is down" and "the spoke is fine and
    refuses us" need different fixes and only the second is what a hub
    migration produces.

    Exit 0 = every spoke OK, 1 = at least one is not.
    """
    from toolkit.features.argocd_spokes import spoke_envs
    from toolkit.features.configuration import ConfigurationManager
    from toolkit.features.spoke_reachability import Status, check_all

    logger.section("Spoke reachability, from the hub's credential")

    cm = ConfigurationManager("common", settings.project_root)
    envs = spoke_envs(cm.get_merged_config())
    results = check_all(envs, Path(kubeconfig))

    for result in results:
        line = f"{result.env}: {result.status.value}"
        if result.status is Status.OK:
            logger.success(f"  {line} — {result.detail}")
        elif result.status is Status.NOT_REGISTERED:
            logger.warning(f"  {line} — {result.detail}")
        else:
            logger.error(f"  {line} — {result.detail}")

    # NOT_REGISTERED is reported and does NOT fail the run. This command asks one
    # question -- does the credential the hub stores actually work -- and an
    # absent registration is a different question with a different tool
    # (`check-drift`, `register-spoke`). It is also the NORMAL state during the
    # AWS->GCP migration: `networking.gcp.managed_spokes` is ["staging"] while
    # `argocd.spokes` declares both, so gcp1 legitimately holds no prod secret.
    # Failing on it would make the command red for months and train everyone to
    # ignore it -- which is how the false green it replaces survived so long.
    broken = [r for r in results if not r.ok and r.status is not Status.NOT_REGISTERED]
    if not broken:
        return
    raise typer.Exit(1)


# =============================================================================
# N8N COMMANDS
# =============================================================================


@n8n_app.command("import")
def n8n_import(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Render plan only, do not exec into the pod")] = False,
) -> None:
    """Reconstruct the n8n workflow + Header Auth credential from Git + SOPS (TOOL-009).

    Reads N8N_IMPORT_CATALOG (toolkit/features/n8n_import.py): for each workflow
    targeting the env, decrypts the webhook secret, renders the credential, and
    pipes it into the n8n pod via /dev/shm (never persistent disk, never argv),
    then imports the workflow and activates it. Idempotent upsert (fixed ids).
    Workflows whose `envs` excludes the target are skipped (successful no-op).
    """
    if env == "dev":
        logger.info("Dev environment uses Docker Compose, not K8s")
        raise typer.Exit(0)

    validate_environment_config(env)

    from toolkit.features.n8n_import import import_n8n_workflow

    if not import_n8n_workflow(env, settings.project_root, dry_run=dry_run):
        raise typer.Exit(1)


@n8n_app.command("smoke")
def n8n_smoke(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")],
    verify_tls: Annotated[
        bool,
        typer.Option(
            "--verify-tls/--no-verify-tls",
            help="Verify the webhook TLS cert (off by default: staging is VPN-only, self-signed)",
        ),
    ] = False,
) -> None:
    """Smoke-test the notification fabric end to end (NOTIFY-001).

    POSTs page + log envelopes to the real n8n webhook with the Bearer secret from
    SOPS and asserts each is accepted (HTTP 200), plus that an unauthenticated POST
    is rejected (HTTP 403). A 200 means n8n routed it and apprise accepted delivery
    — confirm the messages landed in Telegram. Staging-only today.
    """
    if env == "dev":
        logger.info("Dev environment uses Docker Compose, not K8s")
        raise typer.Exit(0)

    validate_environment_config(env)

    from toolkit.features.notify_smoke import run_notify_smoke

    if not run_notify_smoke(env, settings.project_root, verify_tls=verify_tls):
        raise typer.Exit(1)


@k8s_app.command("alert-smoke")
def k8s_alert_smoke(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment (staging only)")],
) -> None:
    """Prove the certificate-alerting path still works, end to end (OBS-007).

    Induces a REAL ACME failure with a throwaway IngressRoute, waits for the alert
    rule to fire, confirms Apprise delivered a notification, removes the failure,
    and confirms the rule clears with a resolved notification.

    Takes 10-20 minutes: the rule evaluates every 5m with a 5m pending period, and
    recovery needs the failures to age out of its own 10m window.

    Staging only, and refused elsewhere rather than merely discouraged — prod's
    policy routes to the page tier, so running it there would wake someone up to
    demonstrate that waking someone up works.
    """
    validate_environment_config(env)

    from toolkit.features.alert_smoke import run_alert_smoke

    if not run_alert_smoke(env).ok:
        raise typer.Exit(1)


# =============================================================================
# BACKUP COMMANDS
# =============================================================================


# The VPS volume-backup surface lived here until 2026-08-22 (#1178, TOOL-038).
# Removed rather than repaired: it was a second, independent implementation --
# raw SSH plus inline `docker volume ls` and `tar` -- of a job BACKUP-044 now
# does with restic to R2, and once `roles/backup` stopped writing to
# `/opt/backups` its `list` command reported FOSSILS: a real directory that
# simply stops growing, indistinguishable from a healthy backup until someone
# needs a restore.
#
# The replacement is `make backup-node` / `make backup-verify-restic`, and the
# restore procedure is docs/runbooks/offsite-backup-restore.md.
#
# `networking.vps.backup.*` in common.yaml is now read by nothing. Left in
# place deliberately: deleting config in the same change that removes its only
# reader makes the diff two decisions, and that key is also the audit trail for
# what the old pipeline covered.


def _get_kubeconfig(env: str) -> str:
    """Get kubeconfig path for the given environment.

    Always derives from --env to ensure deterministic behavior
    regardless of shell KUBECONFIG env var.
    """
    return str(output_path(env))


def _kubectl_cmd(kubeconfig: str) -> str:
    """Build kubectl base command with kubeconfig."""
    return f"kubectl --kubeconfig {kubeconfig}"


#: Escape hatch for `k8s deploy`: apply with the operator's own credentials
#: instead of impersonating the spoke service account. See `_impersonation_flag`.
DEPLOY_AS_OPERATOR_ENV = "KUBELAB_DEPLOY_AS_OPERATOR"

#: Where the spoke's identity is declared. Single source of truth for both the
#: ServiceAccount that Argo CD authenticates as and the RBAC it is granted.
SPOKE_RBAC_MANIFEST = Path("infra/k8s/argocd/spoke-rbac.yaml")


def _spoke_service_account() -> str:
    """Resolve the spoke ServiceAccount Argo CD delivers as, from the RBAC manifest.

    Returned in impersonation form: ``system:serviceaccount:<ns>:<name>``.

    Parsed rather than hardcoded so renaming the ServiceAccount cannot silently
    detach this from the identity it is meant to mirror — the manifest is the
    SSOT for who Argo CD is, and duplicating that here would create exactly the
    kind of drift TOOL-029 exists to prevent.
    """
    manifest = settings.project_root / SPOKE_RBAC_MANIFEST
    for doc in yaml.safe_load_all(manifest.read_text(encoding="utf-8")):
        if doc and doc.get("kind") == "ServiceAccount":
            meta = doc["metadata"]
            return f"system:serviceaccount:{meta['namespace']}:{meta['name']}"
    raise ValueError(f"No ServiceAccount found in {SPOKE_RBAC_MANIFEST} — cannot determine the spoke identity")


def _impersonation_flag() -> str:
    """Return the ``--as=`` flag for the namespaced apply, or "" if opted out.

    Why this exists (TOOL-029, from the #948 post-mortem): `make deploy-k8s` runs
    with the operator's unrestricted kubeconfig, while delivery to prod runs as a
    least-privilege ServiceAccount (ADR-041). Those are different actors, so a
    manifest the operator can apply is not necessarily one Argo CD can apply.
    IDP-031 shipped a `LimitRange` that passed lint, render, tests and a full
    staging deploy, then was refused in prod because the spoke's write role never
    granted that kind. Nothing in the pipeline could have caught it: the GitOps
    path is only exercised *after* merge.

    Impersonating the spoke here makes the manual path incapable of succeeding
    where GitOps would fail. It is not a check — there is no list of known
    failures to keep updated — but an invariant, so it also covers privilege
    divergence nobody predicted (admission webhooks, quotas, policy engines).

    Deliberately scoped to the namespaced overlay apply. `_apply_cluster_bootstrap`
    installs CRDs and cluster-scoped resources that the spoke SA legitimately
    cannot, and must keep running as the operator.
    """
    if os.environ.get(DEPLOY_AS_OPERATOR_ENV, "").strip().lower() in ("1", "true", "yes"):
        logger.warning(
            f"ESCAPE HATCH ({DEPLOY_AS_OPERATOR_ENV}): applying with YOUR credentials, "
            "not the spoke service account. Argo CD may be unable to apply what this "
            "deploy creates, and the failure will surface after merge, in prod. TOOL-029."
        )
        return ""
    return f"--as={_spoke_service_account()}"


def _generate_k8s_manifests(env: str) -> bool:
    """Generate K8s manifests via K8sGenerator. Returns True on success."""
    from toolkit.features.generator_k8s import K8sGenerator

    generator = K8sGenerator()
    result = generator.generate(env)
    if not result.get("success", False):
        logger.error(f"Manifest generation failed: {result.get('error', 'unknown')}")
        return False
    return True


def _load_cluster_bootstrap() -> list[BootstrapEntry]:
    """Load the cluster_bootstrap SSOT (ADR-047 / TOOL-009) from common.yaml.

    These are cluster-scoped foundations (CRDs, controllers, kube-system config)
    applied OUTSIDE the Argo CD overlay — the spoke RBAC is least-privilege and
    cannot create them (ADR-041). File order is preserved (stable apply order).
    """
    common_path = settings.project_root / "infra" / "config" / "values" / "common.yaml"
    with open(common_path) as f:
        config = yaml.safe_load(f)
    return [BootstrapEntry.from_dict(entry) for entry in config.get("cluster_bootstrap", [])]


def _apply_cluster_bootstrap(kubeconfig: str, *, dry_run: bool) -> bool:
    """Render + (validate or apply) every cluster_bootstrap entry, in declared order.

    Shared by `k8s deploy` (step 3), `k8s dry-run`, and `k8s bootstrap`. Returns False on
    the first hard failure (an `optional` entry whose render target is unreachable is a
    logged skip, not a failure — see render_and_apply).
    """
    for entry in _load_cluster_bootstrap():
        verb = "Validating" if dry_run else "Applying"
        logger.info(f"{verb} cluster_bootstrap '{entry.name}' (ns: {entry.namespace})...")
        if not render_and_apply(entry, kubeconfig=kubeconfig, project_root=settings.project_root, dry_run=dry_run):
            logger.error(f"cluster_bootstrap {'dry-run' if dry_run else 'apply'} failed: {entry.name}")
            return False
    return True


@k8s_app.command("bootstrap")
def k8s_bootstrap(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Validate only, do not apply")] = False,
) -> None:
    """Apply ONLY the cluster-wide bootstrap layer (cluster_bootstrap SSOT) — ADR-047 / TOOL-009.

    Installs cluster-scoped foundations (CRDs, controllers, kube-system config) that live
    OUTSIDE the Argo CD overlay, without touching namespaced workloads — useful to land a
    new operator (e.g. agent-sandbox) independently of a full `k8s deploy`.
    """
    if env == "dev":
        logger.info("Dev environment uses Docker Compose, not K8s")
        raise typer.Exit(0)

    logger.section(f"K8s Cluster Bootstrap - {env.upper()}")
    env_config = validate_environment_config(env)
    if not dry_run:
        confirm_dangerous_operation(env_config, "Apply cluster-wide bootstrap layer")

    kubeconfig = _get_kubeconfig(env)
    if not _apply_cluster_bootstrap(kubeconfig, dry_run=dry_run):
        raise typer.Exit(1)
    logger.success("cluster_bootstrap complete")


@k8s_app.command("render-apply")
def k8s_render_apply(
    manifest: Annotated[str, typer.Option("--manifest", "-m", help="Repo-relative manifest path")],
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment (selects kubeconfig)")],
    render: Annotated[
        list[str] | None,
        typer.Option("--render", help="RESOLVE_*=magicdns-host (repeatable)"),
    ] = None,
    optional: Annotated[
        bool, typer.Option("--optional", help="Skip (don't fail) if a render target is unreachable")
    ] = False,
) -> None:
    """Render RESOLVE_* placeholders (MagicDNS) in a single manifest, then server-side apply.

    Toolkit replacement for the inline `dig | sed | kubectl` Makefile pattern
    (ADR-047 D3 / TOOL-009 T4) — used for the aws1 (argocd) EndpointSlice whose
    Tailscale IP rotates on Spot replacement (ADR-025). Cluster-wide bootstrap
    resources go through `cluster_bootstrap` + `k8s deploy` instead.
    """
    render_map: dict[str, str] = {}
    for item in render or []:
        key, sep, host = item.partition("=")
        if not sep or not key or not host:
            logger.error(f"--render must be KEY=host, got: {item!r}")
            raise typer.Exit(2)
        render_map[key] = host

    entry = BootstrapEntry(
        name=Path(manifest).stem,
        namespace="",
        manifest=manifest,
        optional=optional,
        render=render_map,
    )
    kubeconfig = _get_kubeconfig(env)
    if not render_and_apply(entry, kubeconfig=kubeconfig, project_root=settings.project_root):
        raise typer.Exit(1)


@k8s_app.command("apply-secrets")
def k8s_apply_secrets(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would be applied")] = False,
) -> None:
    """Decrypt SOPS secrets and apply as K8s Secrets.

    Reads from infra/config/secrets/{env}.enc.yaml, resolves the secret
    mappings, and runs kubectl create/apply for each K8s Secret.
    """
    if env == "dev":
        logger.info("Dev environment uses Docker Compose, not K8s")
        raise typer.Exit(0)

    validate_environment_config(env)

    from toolkit.features.k8s_secrets import apply_secrets

    if not apply_secrets(env, settings.project_root, dry_run=dry_run):
        raise typer.Exit(1)


@k8s_app.command("apply-middleware-secrets")
def k8s_apply_middleware_secrets(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Render only, do not apply")] = False,
) -> None:
    """Render Traefik Middleware CRDs from templates + SOPS, then kubectl apply.

    Reads MIDDLEWARE_CATALOG (toolkit/features/k8s_middlewares.py), substitutes the
    SOPS api_key into the matching template, writes a gitignored audit copy under
    infra/k8s/overlays/<env>/middlewares/.rendered/, and applies via stdin to keep
    plaintext keys off disk persistently. Middlewares whose `envs` does not include
    the target are silently skipped (successful no-op).
    """
    if env == "dev":
        logger.info("Dev environment uses Docker Compose, not K8s")
        raise typer.Exit(0)

    validate_environment_config(env)

    from toolkit.features.k8s_middlewares import apply_middleware_secrets

    if not apply_middleware_secrets(env, settings.project_root, dry_run=dry_run):
        raise typer.Exit(1)


@k8s_app.command("deploy")
def k8s_deploy(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")],
    skip_generate: Annotated[bool, typer.Option("--skip-generate", help="Skip manifest generation")] = False,
) -> None:
    """Deploy K8s manifests to the cluster.

    Generates manifests, validates with dry-run, applies, and waits for rollout.
    """
    if env == "dev":
        logger.info("Dev environment uses Docker Compose, not K8s")
        raise typer.Exit(0)

    logger.section(f"K8s Deploy - {env.upper()}")
    env_config = validate_environment_config(env)
    confirm_dangerous_operation(env_config, "Deploy to Kubernetes")

    kubeconfig = _get_kubeconfig(env)
    kctl = _kubectl_cmd(kubeconfig)
    overlay_dir = settings.project_root / PATH_STRUCTURES.K8S_OVERLAYS_DIR / env

    # 1. Generate manifests
    if not skip_generate:
        logger.info("Generating K8s manifests...")
        if not _generate_k8s_manifests(env):
            raise typer.Exit(1)

    if not overlay_dir.exists():
        logger.error(f"Overlay directory not found: {overlay_dir}")
        raise typer.Exit(1)

    # Server-side apply, used identically by the dry-run and the real apply below
    # (OPS-015 / #938). Client-side apply stores a full copy of every object in its
    # `last-applied-configuration` annotation to compute future three-way merges,
    # and that annotation is capped at 262144 bytes. The generated homepage
    # ConfigMap exceeds it, which blocked this path and Argo CD alike. SSA keeps
    # ownership in `metadata.managedFields` and writes no such annotation.
    #
    # `--force-conflicts` is the documented pattern for a declarative pipeline
    # taking ownership, not a workaround: every object already in the cluster
    # carries `kubectl-client-side-apply` manager history, so the first SSA pass
    # conflicts on all of them by design. Scoped to this overlay apply — the
    # middleware path (`k8s_middlewares.py`) avoids SSA deliberately and is
    # untouched.
    ssa_flags = "--server-side --force-conflicts --field-manager=kubelab-toolkit"

    # Apply the namespaced overlay AS the identity that will deliver it to prod,
    # not as the operator (TOOL-029). Applied to the dry-run and the real apply
    # alike — the dry-run is where this is most valuable, since it turns a
    # post-merge prod refusal into a pre-merge local failure.
    as_flag = _impersonation_flag()
    if as_flag:
        logger.info(f"Applying manifests as {_spoke_service_account()}")

    # 2. Dry-run validation.
    #    `--dry-run=server`, not `client`: a client dry-run never contacts the API
    #    server, so it structurally cannot fail on admission, quota or field-size
    #    limits — it could not have caught #938 no matter how often it ran. Using
    #    the same flags as the real apply keeps the gate honest about what ships.
    logger.info("Running dry-run validation...")
    dry_run = command.run(
        f"{kctl} apply --dry-run=server {ssa_flags} {as_flag} -k {overlay_dir}",
        check=False,
    )
    if dry_run.returncode != 0:
        logger.error(f"Dry-run failed:\n{dry_run.stderr}")
        raise typer.Exit(1)
    logger.success("Dry-run passed")

    # 3. Apply the cluster-wide bootstrap layer (outside the Kustomize namespace
    #    override). Least-privilege spoke RBAC cannot create CRDs / cluster-scoped
    #    resources (ADR-041), so they are applied imperatively via the shared
    #    render-and-apply primitive driven by the cluster_bootstrap SSOT
    #    (ADR-047 / TOOL-009) — no hardcoded per-component branches.
    if not _apply_cluster_bootstrap(kubeconfig, dry_run=False):
        raise typer.Exit(1)

    # 4. Apply namespace-scoped manifests
    logger.info("Applying manifests...")
    apply_result = command.run(f"{kctl} apply {ssa_flags} {as_flag} -k {overlay_dir}", check=False)
    if apply_result.returncode != 0:
        logger.error(f"Apply failed:\n{apply_result.stderr}")
        raise typer.Exit(1)
    logger.console.print(apply_result.stdout)

    # 5. Wait for rollout. A timed-out/failed rollout is a FAILED deploy, not a
    #    warning: fail closed like every step above so `make deploy-k8s && <next>`
    #    and CI/agents chaining on the exit code stop instead of proceeding over
    #    CrashLooping pods (TOOL-021 / process-audit P6).
    logger.info("Waiting for rollout completion...")
    rollout = command.run(
        f"{kctl} rollout status deployment -n kubelab --timeout=120s",
        check=False,
    )
    if rollout.returncode != 0:
        logger.error(f"Rollout did not complete:\n{rollout.stderr or rollout.stdout}")
        logger.error(f"Inspect a failing deployment: make logs SVC=<name> ENV={env}")
        raise typer.Exit(1)
    logger.success("All deployments rolled out successfully")


@k8s_app.command("dry-run")
def k8s_dry_run(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")],
) -> None:
    """Generate manifests and validate with dry-run (no apply)."""
    if env == "dev":
        logger.info("Dev environment uses Docker Compose, not K8s")
        raise typer.Exit(0)

    logger.section(f"K8s Dry-Run - {env.upper()}")
    validate_environment_config(env)

    kubeconfig = _get_kubeconfig(env)
    kctl = _kubectl_cmd(kubeconfig)
    overlay_dir = settings.project_root / PATH_STRUCTURES.K8S_OVERLAYS_DIR / env

    # Generate manifests
    logger.info("Generating K8s manifests...")
    if not _generate_k8s_manifests(env):
        raise typer.Exit(1)

    if not overlay_dir.exists():
        logger.error(f"Overlay directory not found: {overlay_dir}")
        raise typer.Exit(1)

    # Dry-run the cluster-wide bootstrap layer (ADR-047 / TOOL-009). Server-side
    # dry-run validates each rendered manifest against the live API.
    if not _apply_cluster_bootstrap(kubeconfig, dry_run=True):
        raise typer.Exit(1)

    # Dry-run namespace-scoped resources
    logger.info("Running dry-run validation...")
    result = command.run(
        f"{kctl} apply --dry-run=client -k {overlay_dir}",
        check=False,
    )
    if result.returncode != 0:
        logger.error(f"Dry-run failed:\n{result.stderr}")
        raise typer.Exit(1)

    logger.console.print(result.stdout)
    logger.success("Dry-run validation passed — manifests are valid")


@k8s_app.command("status")
def k8s_status(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")],
) -> None:
    """Show K8s resource status for the kubelab namespace."""
    if env == "dev":
        logger.info("Dev environment uses Docker Compose, not K8s")
        raise typer.Exit(0)

    logger.section(f"K8s Status - {env.upper()}")
    validate_environment_config(env)

    kubeconfig = _get_kubeconfig(env)
    kctl = _kubectl_cmd(kubeconfig)

    result = command.run(
        f"{kctl} get pods,svc,ingressroute -n kubelab",
        check=False,
    )
    if result.returncode != 0:
        logger.error(f"Failed to get status:\n{result.stderr}")
        raise typer.Exit(1)

    logger.console.print(result.stdout)


@k8s_app.command("restart")
def k8s_restart(
    deployment: Annotated[str, typer.Argument(help="Deployment name to restart")],
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")],
    namespace: Annotated[str, typer.Option("--namespace", "-n", help="Namespace")] = "kubelab",
    timeout: Annotated[int, typer.Option("--timeout", help="Seconds to wait for rollout")] = 120,
) -> None:
    """Restart any K8s deployment (rollout restart + wait) on the env's cluster.

    Codified replacement for ad-hoc `kubectl rollout restart`. Generic over
    deployment + namespace (default: kubelab). Typical use: make a pod re-read a
    changed env-var Secret, e.g. Traefik's CF_DNS_API_TOKEN after a token resync:
      toolkit infra k8s restart traefik --env staging --namespace kube-system
    """
    if env == "dev":
        logger.info("Dev environment uses Docker Compose, not K8s (use `services restart`)")
        raise typer.Exit(0)

    logger.section(f"Restart {namespace}/{deployment} - {env.upper()}")
    validate_environment_config(env)

    kctl = _kubectl_cmd(_get_kubeconfig(env))

    restart = command.run(f"{kctl} -n {namespace} rollout restart deployment/{deployment}", check=False)
    if restart.returncode != 0:
        logger.error(f"rollout restart failed:\n{restart.stderr}")
        raise typer.Exit(1)
    logger.console.print(restart.stdout.strip())

    rollout = command.run(
        f"{kctl} -n {namespace} rollout status deployment/{deployment} --timeout={timeout}s",
        check=False,
    )
    if rollout.returncode != 0:
        logger.error(f"rollout did not complete within {timeout}s:\n{rollout.stderr or rollout.stdout}")
        raise typer.Exit(1)
    logger.console.print(rollout.stdout.strip())
    logger.success(f"{namespace}/{deployment} restarted")


@k8s_app.command("fetch-kubeconfig")
def k8s_fetch_kubeconfig(
    env: Annotated[str, typer.Option("--env", "-e", help="Cluster to fetch (staging|prod|hub)")],
) -> None:
    """Fetch a cluster's kubeconfig with a transport-agnostic server (ADR-052).

    Unifies and replaces the bespoke `fetch-kubeconfig-hub` Makefile target.
    SSHes to the cluster's k3s server via its `clusters.<env>.ssh_alias`
    (common.yaml SSOT), rewrites the apiserver to https://127.0.0.1:<local_port>,
    and saves ~/.kube/kubelab-<env>-config (0600). The local port is mapped to the
    real apiserver by the transport layer (`k8s connect`, ADR-052 Phase 2) -- direct
    for prod's public IP, an SSH local-forward on the LAN, or ts-bridge over the
    mesh -- so one kubeconfig works from any machine, including a non-admin box with
    no native Tailscale.
    """
    from toolkit.core.logging import ExecutionError
    from toolkit.features.k8s_kubeconfig import fetch_kubeconfig

    try:
        fetch_kubeconfig(env)
    except KeyError as e:
        logger.error(str(e))
        raise typer.Exit(2) from e
    except (ValueError, ExecutionError) as e:
        logger.error(f"fetch-kubeconfig failed: {e}")
        raise typer.Exit(1) from e


# -----------------------------------------------------------------------------
# CLUSTER-ACCESS TRANSPORT (ADR-052 Phase 2 / TOOL-014)
# `infra k8s access {connect,disconnect,status}` — separate from the legacy
# `infra k8s status` (workloads), which is left untouched.
# -----------------------------------------------------------------------------


@k8s_access_app.command("connect")
def k8s_access_connect(
    env: Annotated[str, typer.Option("--env", "-e", help="Cluster to connect (staging|prod|hub)")],
) -> None:
    """Bring up the cluster-access transport (idempotent).

    Maps the kubeconfig's 127.0.0.1:<local_port> to the env's apiserver: ts-bridge
    over the Headscale mesh for staging/hub, the direct public endpoint for prod.
    Re-running while already up is a clean no-op.
    """
    from toolkit.features.k8s_connect import connect

    try:
        ok = connect(env)
    except KeyError as e:
        logger.error(str(e))
        raise typer.Exit(2) from e
    if not ok:
        raise typer.Exit(1)


@k8s_access_app.command("disconnect")
def k8s_access_disconnect(
    env: Annotated[str, typer.Option("--env", "-e", help="Cluster to disconnect (staging|prod|hub)")],
) -> None:
    """Tear down the cluster-access transport (idempotent; no-op for prod)."""
    from toolkit.features.k8s_connect import disconnect

    try:
        ok = disconnect(env)
    except KeyError as e:
        logger.error(str(e))
        raise typer.Exit(2) from e
    if not ok:
        raise typer.Exit(1)


@k8s_access_app.command("status")
def k8s_access_status(
    env: Annotated[str, typer.Option("--env", "-e", help="Cluster to inspect (staging|prod|hub)")],
) -> None:
    """Report whether the transport is up and which transport was resolved."""
    from toolkit.features.k8s_connect import status

    try:
        status(env)
    except KeyError as e:
        logger.error(str(e))
        raise typer.Exit(2) from e


# =============================================================================
# ANSIBLE COMMANDS
# =============================================================================


@ansible_app.command("generate")
def ansible_generate(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")] = "staging",
    bootstrap: Annotated[
        bool, typer.Option("--bootstrap", help="Use LAN IPs instead of Tailscale (first-time provisioning)")
    ] = False,
    transport: Annotated[
        str,
        typer.Option(
            "--transport",
            help="SSH transport (TOOL-016): 'mesh' (default, controller on the Tailscale mesh) "
            "or 'bastion' (jump mesh-only nodes through the VPS public bastion — for a non-mesh controller)",
        ),
    ] = "mesh",
) -> None:
    """Generate Ansible inventory from common.yaml (SSOT).

    Reads networking.* from common.yaml and produces inventory
    in infra/ansible/generated/{env}/. Playbooks load config
    directly via include_vars (ADR-020 Rev2).

    Use --bootstrap for first-time provisioning when Tailscale
    is not yet configured on target nodes. This uses lan_ip
    as ansible_host instead of tailscale_ip.

    Use --transport bastion when provisioning from a controller that is NOT on the
    mesh (non-admin box / bare WSL): mesh-only nodes are reached via a ProxyCommand
    through the VPS public bastion (ADR-052 sibling for SSH).
    """
    from toolkit.features.generator_ansible import VALID_TRANSPORTS

    if transport not in VALID_TRANSPORTS:
        logger.error(f"Invalid --transport '{transport}' (expected: {' | '.join(VALID_TRANSPORTS)})")
        raise typer.Exit(1) from None

    _suffix = (" (bootstrap)" if bootstrap else "") + (f" [{transport}]" if transport != "mesh" else "")
    logger.section("Ansible Generate" + _suffix)

    try:
        from toolkit.features.generator_ansible import ansible_generator

        result = ansible_generator.generate(env, bootstrap=bootstrap, transport=transport)
        if result.get("success"):
            for f in result.get("files", []):
                logger.info(f"  {f}")
        else:
            logger.error(f"Generation failed: {result.get('error')}")
            raise typer.Exit(1) from None
    except Exception as e:
        logger.error(f"Ansible generation failed: {e}")
        raise typer.Exit(1) from None


@ansible_app.command("run")
def ansible_run(
    playbook: Annotated[str, typer.Option("--playbook", "-p", help="Playbook name (without .yml)")],
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")] = "staging",
    limit: Annotated[str | None, typer.Option("--limit", "-l", help="Limit to specific hosts")] = None,
    tags: Annotated[str | None, typer.Option("--tags", "-t", help="Run only tagged tasks")] = None,
    check: Annotated[bool, typer.Option("--check", help="Dry-run mode (no changes)")] = False,
    become_ask_pass: Annotated[bool, typer.Option("--ask-become-pass", "-K", help="Ask for sudo password")] = False,
    extra_vars: Annotated[
        str | None, typer.Option("--extra-vars", help="Extra variables (key=value key2=value2)")
    ] = None,
) -> None:
    """Run an Ansible playbook against the generated inventory.

    Loads SSOT config via include_vars at playbook level (ADR-020 Rev2).
    Inventory is generated from common.yaml networking.* section.
    """
    logger.section(f"Ansible Run — {playbook} ({env})")

    ansible_dir = settings.ansible_dir
    inventory = ansible_dir / "generated" / env / "hosts.yml"
    playbook_path = ansible_dir / "playbooks" / f"{playbook}.yml"

    if not inventory.exists():
        logger.error(f"Inventory not found: {inventory}")
        logger.info("Run 'toolkit infra ansible generate --env {env}' first")
        raise typer.Exit(1) from None

    if not playbook_path.exists():
        logger.error(f"Playbook not found: {playbook_path}")
        raise typer.Exit(1) from None

    cmd = f"ansible-playbook {playbook_path} -i {inventory} -e deploy_env={env}"
    if limit:
        cmd += f" --limit {limit}"
    if tags:
        cmd += f" --tags {tags}"
    if check:
        cmd += " --check"
    if become_ask_pass:
        cmd += " --ask-become-pass"
    if extra_vars:
        cmd += f" --extra-vars '{extra_vars}'"

    logger.info(f"Running: {cmd}")
    result = command.run(cmd, cwd=ansible_dir, check=False, capture_output=False)

    if result.returncode == 0:
        logger.success(f"Playbook '{playbook}' completed successfully")
    else:
        logger.error(f"Playbook '{playbook}' failed")
        raise typer.Exit(1) from None


@ansible_app.command("syntax-check")
def ansible_syntax_check(
    playbook: Annotated[
        str | None,
        typer.Option("--playbook", "-p", help="Check one playbook (without .yml) instead of all"),
    ] = None,
) -> None:
    """Parse every playbook without running it — the Ansible half of `make lint`.

    Nothing validated Ansible in this repo until now: `make lint` is ruff over
    `toolkit/`, and pre-commit's yamllint only proves a file is YAML. A playbook
    can be perfectly valid YAML and still be rejected by Ansible — an unknown
    module, a role that does not exist, a malformed `hosts:` — and the first
    place that surfaced was a deploy against real infrastructure.

    Uses the committed static inventory rather than the generated one, so this
    runs in CI with no `ansible generate` step and no SSOT decrypt.

    What it does NOT catch, stated because an earlier version of this docstring
    claimed the opposite: an unresolvable `hosts:` pattern. `--syntax-check`
    parses structure and loads roles, but pattern matching happens at execution
    time — `hosts: typo_host` emits a WARNING and exits 0 (measured, #1180
    review). Making that fatal is not available here either: 11 of the 20
    playbooks already emit it against the static inventory, because the real
    host set lives in the per-environment GENERATED inventory. Catching a
    typo'd host needs a different mechanism than this gate.

    Requires the Galaxy collections from requirements.yml: syntax-check loads
    the roles a playbook includes, and a role using `community.docker` fails to
    parse without it (measured, not assumed).
    """
    logger.section("Ansible Syntax Check")

    ansible_dir = settings.ansible_dir
    inventory = ansible_dir / "inventories" / "homelab.yml"
    playbook_dir = ansible_dir / "playbooks"

    if playbook:
        playbooks = [playbook_dir / f"{playbook}.yml"]
        if not playbooks[0].exists():
            logger.error(f"Playbook not found: {playbooks[0]}")
            raise typer.Exit(1) from None
    else:
        # Top level only: playbooks/_includes/ holds task files that are
        # included INTO a play and are not playbooks themselves — passing one
        # to ansible-playbook fails on a structure that is entirely correct.
        playbooks = sorted(playbook_dir.glob("*.yml"))

    if not playbooks:
        logger.error(f"No playbooks found in {playbook_dir}")
        raise typer.Exit(1) from None

    failed: list[str] = []
    for path in playbooks:
        result = command.run(
            f"ansible-playbook --syntax-check {path} -i {inventory}",
            cwd=ansible_dir,
            check=False,
            capture_output=True,
        )
        if result.returncode == 0:
            logger.success(f"{path.name}")
        else:
            failed.append(path.name)
            logger.error(f"{path.name}")
            # stderr carries the parse error and the line it points at; without
            # it the failure name alone sends you back to reproduce locally.
            for line in (result.stderr or result.stdout or "").strip().splitlines():
                logger.info(f"    {line}")

    if failed:
        logger.error(f"{len(failed)} of {len(playbooks)} playbooks failed: {', '.join(failed)}")
        raise typer.Exit(1) from None

    logger.success(f"All {len(playbooks)} playbooks parse")


# `toolkit infra ansible deploy` lived here until 2026-08-22 (#1178, TOOL-038).
# It ran `playbooks/deploy.yml`, which was deleted in February 2026 by the
# refactor that replaced `infra/compose/` with `infra/stacks/` — so the command
# had been broken for six months, and `docs/runbooks/developer-guide.md` was
# still teaching it to newcomers.
#
# Removed rather than repaired: the deploy model it belonged to was replaced,
# not lost. `make deploy TARGET=vps|dns|k3s|harden-nodes` routes through
# `infra ansible run -p deploy-<target>`, and those playbooks exist.


def _check_terraform_setup() -> None:
    """Check if Terraform is properly set up."""
    if command.run("which terraform", check=False).returncode != 0:
        logger.error(MESSAGES.ERROR_TERRAFORM_NOT_FOUND)
        raise typer.Exit(1) from None

    if not settings.terraform_dir.exists():
        logger.error(MESSAGES.ERROR_TERRAFORM_DIR_NOT_FOUND.format(settings.terraform_dir))
        raise typer.Exit(1) from None


def _get_terraform_env(env: str) -> dict[str, str]:
    """Build environment dict with Cloudflare API token from SOPS.

    Extracts the Cloudflare API token from the SOPS secrets and returns
    an env dict suitable for passing to subprocess/command.run calls.
    """
    from toolkit.features.configuration import ConfigurationManager

    config_manager = ConfigurationManager(env, settings.project_root)
    merged = config_manager.get_merged_config()

    # Navigate: cloudflare.api_token (from common.enc.yaml)
    token = merged.get("cloudflare", {}).get("api_token", "")
    if not token:
        logger.error("Cloudflare API token not found in SOPS secrets (cloudflare.api_token)")
        raise typer.Exit(1) from None

    # Inherit current environment + inject TF_VAR
    env_dict = dict(os.environ)
    env_dict["TF_VAR_cloudflare_api_token"] = token
    return env_dict


@terraform_app.command("init")
def tf_init(env: str = typer.Argument("dev", help="Target environment")) -> None:
    """
    Initialize Terraform configuration.

    Generates necessary backend config and runs 'terraform init'.
    """
    logger.section(f"Terraform Init - {env.upper()}")
    validate_environment_config(env)

    try:
        # Generate configuration first
        from toolkit.features.generator_terraform import terraform_generator

        result = terraform_generator.generate(env)
        if not result.get("success", False):
            logger.error(MESSAGES.ERROR_TERRAFORM_CONFIG_GENERATION_FAILED)
            raise typer.Exit(1) from None

        # Check terraform setup
        _check_terraform_setup()

        # Run terraform init
        terraform_dir = settings.terraform_dir
        tf_env = _get_terraform_env(env)

        cmd = "terraform init"
        logger.info(f"Running: {cmd}")

        tf_result = command.run(cmd, cwd=terraform_dir, env=tf_env)
        if tf_result.returncode == 0:
            logger.success(MESSAGES.SUCCESS_TERRAFORM_INIT.format(env))
        else:
            logger.error(MESSAGES.ERROR_TERRAFORM_INIT_FAILED)
            raise typer.Exit(1) from None

    except Exception as e:
        logger.error(MESSAGES.ERROR_TERRAFORM_INIT_FAILED_WITH_ERROR.format(e))
        raise typer.Exit(1) from None


@terraform_app.command("plan")
def tf_plan(
    env: Annotated[str, typer.Option("--env", "-e", help="Environment for SOPS credentials")] = "prod",
    out: Annotated[str | None, typer.Option("--out", "-o", help="Save plan to file")] = None,
) -> None:
    """
    Create a Terraform execution plan.

    DNS is global (not per-env). --env only selects which SOPS to decrypt.
    Uses terraform.tfvars (auto-loaded by Terraform).
    """
    logger.section("Terraform Plan")

    try:
        _check_terraform_setup()
        terraform_dir = settings.terraform_dir
        tf_env = _get_terraform_env(env)

        output_file = out or "dns.tfplan"
        tfvars_file = terraform_dir / "dns.tfvars"
        cmd_parts = ["terraform", "plan"]
        if tfvars_file.exists():
            cmd_parts.extend(["-var-file", str(tfvars_file)])
        cmd_parts.extend(["-out", output_file])
        cmd = " ".join(cmd_parts)

        logger.info(f"Creating plan: {cmd}")
        result = command.run(cmd, cwd=terraform_dir, env=tf_env)

        if result.returncode == 0:
            logger.success(MESSAGES.SUCCESS_TERRAFORM_PLAN_CREATED.format(output_file))
        else:
            raise typer.Exit(1) from None

    except Exception as e:
        logger.error(MESSAGES.ERROR_TERRAFORM_PLAN_FAILED.format(e))
        raise typer.Exit(1) from None


@terraform_app.command("apply")
def tf_apply(
    env: Annotated[str, typer.Option("--env", "-e", help="Environment for SOPS credentials")] = "prod",
    plan_file: Annotated[str | None, typer.Option("--plan-file", "-f", help="Plan file to apply")] = None,
    auto_approve: Annotated[bool, typer.Option("--auto-approve", help="Skip interactive approval")] = False,
) -> None:
    """
    Apply Terraform configuration changes.

    DNS is global (not per-env). --env only selects which SOPS to decrypt.
    """
    logger.section("Terraform Apply")

    try:
        _check_terraform_setup()

        terraform_dir = settings.terraform_dir
        tf_env = _get_terraform_env(env)
        plan_to_apply = plan_file or "dns.tfplan"

        # Check if plan file exists
        plan_path = terraform_dir / plan_to_apply
        if plan_path.exists():
            cmd = f"terraform apply {plan_to_apply}"
        else:
            logger.warning(MESSAGES.WARNING_TERRAFORM_PLAN_NOT_FOUND.format(plan_path))
            logger.info(MESSAGES.INFO_TERRAFORM_APPLY_WITHOUT_PLAN)
            cmd = "terraform apply"
            if auto_approve:
                cmd += " -auto-approve"

        logger.info(f"Applying configuration: {cmd}")
        result = command.run(cmd, cwd=terraform_dir, env=tf_env)

        if result.returncode == 0:
            logger.success(MESSAGES.SUCCESS_TERRAFORM_APPLY.format(env))
        else:
            raise typer.Exit(1) from None

    except Exception as e:
        logger.error(MESSAGES.ERROR_TERRAFORM_APPLY_FAILED.format(e))
        raise typer.Exit(1) from None


@terraform_app.command("destroy")
def tf_destroy(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")],
    auto_approve: Annotated[bool, typer.Option("--auto-approve", help="Skip interactive approval")] = False,
) -> None:
    """
    Destroy Terraform-managed infrastructure.

    DANGER: This will delete resources!
    """
    logger.section(f"Terraform Destroy - {env.upper()}")

    # Validate environment and get config
    env_config = validate_environment_config(env)

    try:
        _check_terraform_setup()

        # Always require confirmation for destroy
        if not auto_approve:
            logger.warning(MESSAGES.WARNING_TERRAFORM_DESTROY_DANGER)
            confirm_dangerous_operation(env_config, "Destroy infrastructure")

            # Additional confirmation for production (special case for destroy)
            if env == "prod":
                if not logger.confirm("This is PRODUCTION. Type 'destroy' to confirm:", default=False):
                    logger.info(MESSAGES.INFO_TERRAFORM_DESTROY_CANCELLED)
                    raise typer.Exit(0) from None

        terraform_dir = settings.terraform_dir
        tf_env = _get_terraform_env(env)
        tfvars_file = terraform_dir / f"{env}.tfvars"

        cmd_parts = ["terraform", "destroy"]

        if tfvars_file.exists():
            cmd_parts.extend(["-var-file", str(tfvars_file)])

        if auto_approve:
            cmd_parts.append("-auto-approve")

        cmd = " ".join(cmd_parts)

        logger.info(f"Destroying infrastructure: {cmd}")
        result = command.run(cmd, cwd=terraform_dir, env=tf_env)

        if result.returncode == 0:
            logger.success(MESSAGES.SUCCESS_TERRAFORM_DESTROY.format(env))
        else:
            raise typer.Exit(1) from None

    except Exception as e:
        logger.error(MESSAGES.ERROR_TERRAFORM_DESTROY_FAILED.format(e))
        raise typer.Exit(1) from None


@terraform_app.command("aws-tfvars")
def tf_aws_tfvars() -> None:
    """Generate aws.tfvars from SOPS secrets for AWS Argo CD hub."""
    from toolkit.features.configuration import ConfigurationManager

    aws_dir = settings.project_root / "infra" / "terraform" / "aws"
    tfvars_path = aws_dir / "aws.tfvars"

    cm = ConfigurationManager("common", settings.project_root)
    merged = cm.get_merged_config()
    aws = merged.get("aws", {})

    authkey = aws.get("headscale_preauth_key", "")
    api_key = aws.get("headscale_api_key", "")

    if not authkey:
        logger.error("aws.headscale_preauth_key not found in SOPS")
        raise typer.Exit(1) from None
    if not api_key:
        logger.error("aws.headscale_api_key not found in SOPS")
        raise typer.Exit(1) from None

    tfvars_path.write_text(f'tailscale_authkey = "{authkey}"\nheadscale_api_key = "{api_key}"\n')
    logger.success(f"Generated {tfvars_path}")


@terraform_app.command("killswitch-test-tfvars")
def tf_killswitch_test_tfvars() -> None:
    """Render the scratch project's tfvars: the billing id, and the SA to grant.

    The service-account email is READ FROM THE BOOTSTRAP ROOT'S OUTPUT rather
    than retyped. Since the detach permission is per-project, a stale copy grants
    the wrong identity and the proof then fails as a 403 — which reads as "the
    kill switch does not work" when what failed was the test's own setup.
    """
    import subprocess

    from toolkit.features.configuration import ConfigurationManager

    boot_dir = settings.project_root / "infra" / "terraform" / "gcp-bootstrap"
    test_dir = settings.project_root / "infra" / "terraform" / "gcp-killswitch-test"

    cm = ConfigurationManager("common", settings.project_root)
    billing_id = cm.get_merged_config().get("gcp", {}).get("billing_account_id", "")
    if not billing_id:
        logger.error("gcp.billing_account_id not found in SOPS")
        raise typer.Exit(1) from None

    result = subprocess.run(
        ["terraform", f"-chdir={boot_dir}", "output", "-raw", "kill_switch_service_account"],
        capture_output=True,
        text=True,
    )
    sa = result.stdout.strip()
    if result.returncode != 0 or not sa:
        logger.error(
            "could not read kill_switch_service_account from the bootstrap root. "
            "Apply infra/terraform/gcp-bootstrap first."
        )
        raise typer.Exit(1) from None

    path = test_dir / "killswitch-test.tfvars"
    path.write_text(f'billing_account_id = "{billing_id}"\nkill_switch_service_account = "{sa}"\n')
    logger.success(f"Generated {path}")


@terraform_app.command("verify-killswitch")
def tf_verify_killswitch(
    scratch_project: Annotated[str, typer.Option("--scratch", help="Expendable project to detach")],
    function: Annotated[str, typer.Option("--function")] = "billing-kill-switch",
    region: Annotated[str, typer.Option("--region")] = "europe-west4",
    topic: Annotated[str, typer.Option("--topic")] = "billing-kill-switch",
    hub_project: Annotated[str, typer.Option("--hub")] = "kubelab-hub",
) -> None:
    """Prove the billing kill switch fires, against a scratch project (AC2b).

    A budget rule that has never fired is not evidence. This repoints the REAL
    function at an expendable project, publishes a message matching the genuine
    budget schema to the REAL topic, waits for billing to go away, and restores
    the target unconditionally -- verifying the restore rather than assuming it.

    Never run with --scratch pointing at the hub. It would work.
    """
    from toolkit.features import gcp_killswitch_proof as proof

    logger.section("Kill switch proof (AC2b)")
    try:
        result = proof.run_proof(
            function=function,
            region=region,
            topic=topic,
            scratch_project=scratch_project,
            expected_home=hub_project,
        )
    except proof.KillSwitchProofError as exc:
        logger.error(str(exc))
        raise typer.Exit(1) from exc

    logger.info(f"target restored to {result.restored_to}")
    if not result.detached:
        logger.error(
            f"billing on {result.scratch_project} was STILL ENABLED after "
            f"{result.seconds_waited}s. The switch did not fire — the hard cap "
            "does not cap. Check the function's logs before trusting it."
        )
        raise typer.Exit(1)

    logger.success(f"billing detached from {result.scratch_project} after {result.seconds_waited}s — the cap caps")


@terraform_app.command("gcp-bootstrap-tfvars")
def tf_gcp_bootstrap_tfvars() -> None:
    """Render gcp-bootstrap.tfvars from SOPS. Carries exactly one secret.

    This is the shape `aws-tfvars` has and the hub module turned out not to
    need: a real SOPS value injected into Terraform and the file deleted after
    use. The hub carries none because cloud-init reads its credentials from
    Secret Manager; the BOOTSTRAP root predates Secret Manager existing, so its
    one input has nowhere else to come from.

    `gcp.billing_account_id` is not a credential -- nothing can be spent with it
    absent IAM -- but this repository is public and git history is permanent, so
    it is in SOPS rather than in a committed default.
    """
    from toolkit.features.configuration import ConfigurationManager

    boot_dir = settings.project_root / "infra" / "terraform" / "gcp-bootstrap"
    if not (boot_dir / "variables.tf").exists():
        logger.error(f"no Terraform module at {boot_dir}")
        raise typer.Exit(1) from None

    cm = ConfigurationManager("common", settings.project_root)
    billing_id = cm.get_merged_config().get("gcp", {}).get("billing_account_id", "")

    if not billing_id:
        logger.error(
            "gcp.billing_account_id not found in SOPS. Set it with:\n"
            "  toolkit secrets set gcp.billing_account_id --stdin --env common"
        )
        raise typer.Exit(1) from None

    path = boot_dir / "gcp-bootstrap.tfvars"
    path.write_text(f'billing_account_id = "{billing_id}"\n')
    # The path, never the value: this line goes to a terminal, a CI log and a
    # session transcript, none of which can be un-printed.
    logger.success(f"Generated {path}")


@terraform_app.command("gcp-tfvars")
def tf_gcp_tfvars() -> None:
    """Render gcp.tfvars from common.yaml. Carries no secret, by design.

    `aws-tfvars` injects two SOPS values and deletes the file. This does NOT:
    the GCP hub reads its credentials from Secret Manager at boot, so Terraform
    carries none. What it renders instead is the config the Terraform defaults
    currently restate -- see toolkit/features/gcp_tfvars.py for why the shape
    survived while the content changed.
    """
    from toolkit.features import gcp_tfvars
    from toolkit.features.configuration import ConfigurationManager

    gcp_dir = settings.project_root / "infra" / "terraform" / "gcp"
    if not (gcp_dir / "variables.tf").exists():
        logger.error(f"no Terraform module at {gcp_dir}")
        raise typer.Exit(1) from None

    cm = ConfigurationManager("common", settings.project_root)
    try:
        path = gcp_tfvars.write(cm.get_merged_config(), gcp_dir)
    except (KeyError, ValueError) as exc:
        logger.error(f"cannot render gcp.tfvars: {exc}")
        raise typer.Exit(1) from None
    logger.success(f"Generated {path}")


@terraform_app.command("gcp-status")
def tf_gcp_status() -> None:
    """Describe the hub's managed instance group. Read-only."""
    _gcp_mig_call("status")


@terraform_app.command("gcp-resize")
def tf_gcp_resize(
    size: int = typer.Option(..., "--size", help="Target size: 0 stops the hub, 1 rebuilds it."),
) -> None:
    """Set the MIG's target size. 0 stops paying for the VM; 1 boots a fresh one."""
    _gcp_mig_call("resize", size)


@terraform_app.command("gcp-recreate")
def tf_gcp_recreate() -> None:
    """Delete the running hub and let the MIG rebuild it — a preemption on demand."""
    _gcp_mig_call("recreate")


def _gcp_mig_call(action: str, *args: object) -> None:
    """One entry point for the three MIG verbs, so error handling is written once."""
    from toolkit.features import gcp_mig
    from toolkit.features.configuration import ConfigurationManager

    cm = ConfigurationManager("common", settings.project_root)
    try:
        code = getattr(gcp_mig, action)(cm.get_merged_config(), *args)
    except (KeyError, ValueError, RuntimeError) as exc:
        logger.error(str(exc))
        raise typer.Exit(1) from None
    if code != 0:
        raise typer.Exit(code) from None


@terraform_app.command("validate")
def tf_validate() -> None:
    """
    Validate and format Terraform configuration files.
    """
    logger.section("Terraform Configuration Validation")

    try:
        _check_terraform_setup()
        terraform_dir = settings.terraform_dir

        with logger.progress("Validating Terraform configuration...") as progress:
            task = progress.add_task("Validation", total=3)

            # Format check
            progress.update(task, description="Checking formatting...")
            format_result = command.run("terraform fmt -check", cwd=terraform_dir, check=False)
            progress.advance(task)

            # Syntax validation (needs provider vars for full validation)
            progress.update(task, description="Validating syntax...")
            validate_result = command.run("terraform validate", cwd=terraform_dir, check=False)
            progress.advance(task)

            progress.update(task, description="Finalizing...")
            progress.advance(task)

        if format_result.returncode != 0:
            logger.warning(MESSAGES.WARNING_TERRAFORM_FORMAT_NEEDED)
            logger.info(MESSAGES.INFO_TERRAFORM_FMT_COMMAND)

        if validate_result.returncode == 0:
            logger.success(MESSAGES.SUCCESS_TERRAFORM_VALID)
        else:
            raise typer.Exit(1) from None

    except Exception as e:
        logger.error(MESSAGES.ERROR_TERRAFORM_VALIDATION_FAILED.format(e))
        raise typer.Exit(1) from None


# =============================================================================
# GENERAL INFRA COMMANDS
# =============================================================================


@app.command()
def status(
    service: Annotated[
        str,
        typer.Argument(help="Service to check (traefik, all)"),
    ] = "traefik",
    env: Annotated[
        str,
        typer.Option(
            "--env",
            "-e",
            help="Target environment",
        ),
    ] = "dev",
) -> None:
    """
    Check the status of infrastructure services (e.g., Traefik).
    """
    validate_environment_config(env)

    if service == "traefik":
        _check_traefik_status(env)
    elif service == "all":
        _check_all_services_status(env)
    else:
        logger.error(MESSAGES.ERROR_UNKNOWN_SERVICE.format(service))
        logger.info(MESSAGES.INFO_INFRASTRUCTURE_AVAILABLE_SERVICES)
        raise typer.Exit(1) from None


def _check_traefik_status(env: str) -> None:
    """Check Traefik service status."""
    logger.section(f"Traefik Status - {env.upper()}")

    try:
        # Check if Traefik container is running
        result = command.run(
            "docker ps --filter name=traefik --format 'table {{.Names}}\t{{.Status}}'",
            check=False,
        )

        if result.returncode == 0 and result.stdout.strip():
            logger.success(MESSAGES.SUCCESS_INFRASTRUCTURE_TRAEFIK_RUNNING)
            logger.console.print(result.stdout)
        else:
            logger.warning(MESSAGES.WARNING_INFRASTRUCTURE_TRAEFIK_NOT_RUNNING)

        # Health check endpoints
        _check_traefik_health(env)

    except Exception as e:
        logger.error(MESSAGES.ERROR_INFRASTRUCTURE_STATUS_CHECK_FAILED.format(e))
        raise typer.Exit(1) from None


def _check_traefik_health(env: str) -> None:
    """Check Traefik health endpoints."""
    try:
        # Check Traefik API/dashboard
        env_settings = get_settings(env)
        api_url = env_settings.api_endpoint
        result = command.run(
            f"curl -s -o /dev/null -w '%{{http_code}}' --max-time {env_settings.curl_timeout} {api_url}",
            check=False,
        )

        if result.returncode == 0 and result.stdout.strip() in NETWORK_DEFAULTS.CONNECTION_SUCCESS_CODES:
            logger.success(MESSAGES.SUCCESS_INFRASTRUCTURE_TRAEFIK_API_RESPONDING)
        else:
            logger.warning(MESSAGES.WARNING_INFRASTRUCTURE_TRAEFIK_API_NOT_RESPONDING.format(result.stdout.strip()))

        # Check service discovery
        logger.info(MESSAGES.INFO_SERVICE_DISCOVERY_STATUS)
        result = command.run("docker ps --format 'table {{.Names}}\t{{.Labels}}'", check=False)
        if result.returncode == 0:
            # Count services with traefik labels
            traefik_services = 0
            for line in result.stdout.split("\n"):
                if "traefik.enable=true" in line:
                    traefik_services += 1

            logger.info(f"Found {traefik_services} services with Traefik labels")

    except Exception as e:
        logger.warning(MESSAGES.WARNING_INFRASTRUCTURE_HEALTH_CHECK_FAILED.format(e))


def _check_all_services_status(env: str) -> None:
    """Check status of all infrastructure services."""
    logger.section(f"All Services Status - {env.upper()}")

    services = ["traefik"]

    for service in services:
        logger.info(f"Checking {service}...")
        try:
            if service == "traefik":
                _check_traefik_status(env)
            logger.success(MESSAGES.SUCCESS_INFRASTRUCTURE_SERVICE_STATUS_CHECKED.format(service))
        except Exception:
            logger.warning(MESSAGES.WARNING_INFRASTRUCTURE_SERVICE_CHECK_FAILED.format(service))

    logger.info(MESSAGES.INFO_INFRASTRUCTURE_STATUS_CHECK_COMPLETED)


@app.command("nuke")
def nuke_infra(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")] = "dev",
    force: Annotated[bool, typer.Option("--force", "-f", help="Force execution without confirmation")] = False,
) -> None:
    """
    DESTROY EVERYTHING: Stops containers, removes volumes, networks, and cleans caches.

    Use with caution. This will:
    1. Stop all containers and remove volumes/networks for the environment.
    2. Remove all __pycache__ and .pytest_cache directories.
    3. Optionally run docker system prune.
    """
    logger.section("☢️  NUCLEAR OPTION: CLEAN INFRASTRUCTURE ☢️")

    if not force:
        logger.warning("This will destroy all data in volumes and stop services.")
        if not typer.confirm("Are you sure you want to proceed?"):
            logger.info("Operation cancelled.")
            raise typer.Exit()

    # 1. Stop all running containers and remove volumes
    logger.info(f"Stopping all containers and removing volumes for {env}...")
    command.run(
        "docker compose down --volumes --remove-orphans 2>/dev/null || true",
        check=False,
    )
    command.run("docker stop $(docker ps -q) 2>/dev/null || true", check=False)
    command.run("docker container prune -f", check=False)

    # 2. Clean Python Cache
    logger.info("Cleaning Python cache files...")
    cleaned_count = 0
    for path in settings.project_root.rglob("__pycache__"):
        import shutil

        try:
            shutil.rmtree(path)
            cleaned_count += 1
        except Exception as e:
            logger.warning(f"Failed to remove {path}: {e}")

    for path in settings.project_root.rglob(".pytest_cache"):
        import shutil

        try:
            shutil.rmtree(path)
            cleaned_count += 1
        except Exception as e:
            logger.warning(f"Failed to remove {path}: {e}")

    logger.success(f"Removed {cleaned_count} cache directories.")

    # 3. Docker System Prune (Optional)
    if force or typer.confirm("Do you want to run 'docker system prune -a' (removes unused images/networks)?"):
        logger.info("Pruning Docker system...")
        command.run("docker system prune -a -f --volumes", check=False)

    logger.success("Nuke complete. The slate is clean.")
