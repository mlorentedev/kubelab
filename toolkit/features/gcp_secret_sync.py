"""One-way delivery of the hub's boot secrets into Google Secret Manager.

GCP-001 finding F1, ADR-063 D7. A managed instance group *recreates* rather than
restarts, so every preemption rebuilds the Argo CD hub from a fresh disk with no
operator present. That machine has no SOPS age key, no kubeconfig and nobody to
type a password: Secret Manager is the only channel it can reach at boot.

**SOPS remains the SSOT.** Nothing is ever authored here and nothing is read back
into SOPS; drift is resolved by re-syncing. There is deliberately no reverse
mode, no pruning and no ownership labelling — a second writer to the same values
would recreate the disagreement this sync exists to remove.

TWO INPUT CLASSES, and the difference is about origin rather than plumbing:

1. **SOPS-authored** — tagged `sync_to_secret_manager=True` in `SECRET_CATALOG`,
   which is the single declaration of what the hub may read.
2. **Spoke-derived** — each spoke's Argo CD ServiceAccount token and cluster CA.
   Kubernetes generates these; no human writes them, and they exist in no vault.
   `make register-spoke` reads them live out of the spoke's
   `argocd-manager-token` Secret, and so does this. Tagging them in the catalog
   would assert an origin they do not have.

   Consequence, stated because it surprises: this sync needs the spokes
   *reachable at sync time* — for staging that means the homelab is powered on.
   The hub never needs them at boot; it reads the copy.

No cloud SDK. The repository has none for any provider — AWS reaches Terraform
through tfvars rendered from SOPS — and `gcloud` is already a Phase 0
prerequisite (runbook §2). Adding `google-cloud-secret-manager` to install one
would be a new dependency class for a tool that shells out four times.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Any

from toolkit.core.logging import logger
from toolkit.features import k8s_kubeconfig
from toolkit.features.secrets_manager import (
    secret_manager_name,
    secrets_synced_to_secret_manager,
)

# The spoke-side Secret that `spoke-rbac.yaml` creates and `register-spoke`
# reads. Named once here; the two fields below are its only consumers.
SPOKE_TOKEN_SECRET = "argocd-manager-token"
SPOKE_NAMESPACE = "kubelab"

# Secret Manager bills per active version and a *disabled* version still bills,
# so superseded versions are DESTROYED rather than disabled. Six is the ceiling
# the cost envelope sets; in practice this tool leaves exactly one.
MAX_ACTIVE_VERSIONS = 6


@dataclass(frozen=True)
class SyncItem:
    """One secret bound for Secret Manager.

    `value` is `repr=False` on purpose. A dataclass prints every field by
    default, so a bare `print(item)` in a debugger, a logged exception carrying
    locals, or a `logger.debug(f"{items}")` added later would each put a
    credential in output that gets pasted into a terminal and a transcript. The
    doctrine says never print a secret; this makes the accidental path harder.
    """

    secret_id: str  # Secret Manager id, always via secret_manager_name()
    origin: str  # Human-readable source. NEVER a value.
    value: str = field(repr=False)


@dataclass(frozen=True)
class SyncResult:
    secret_id: str
    action: str  # created | updated | unchanged | failed
    detail: str = ""


class GcloudMissingError(RuntimeError):
    """`gcloud` is not on PATH. Phase 0 has not been done on this machine."""


def _gcloud(args: list[str], project_id: str, stdin_data: str | None = None) -> subprocess.CompletedProcess[str]:
    """Invoke `gcloud`, with any secret value passed ONLY through stdin.

    `toolkit.features.command.run` is deliberately not used here, and the reason
    is specific rather than stylistic: it takes a shell string, has no stdin
    parameter, and logs the command it runs. Every one of those is wrong for a
    credential — a value on argv is visible to `ps` for the life of the call and
    lands in whatever the helper logs.

    So: argv list (no shell, no quoting to get wrong), values on stdin, and the
    only thing ever logged is the subcommand and the secret's NAME.
    """
    argv = ["gcloud", "secrets", *args, f"--project={project_id}"]
    logger.debug(f"gcloud secrets {' '.join(args[:2])} (project={project_id})")
    try:
        return subprocess.run(  # noqa: S603 - argv list, no shell; see docstring
            argv,
            input=stdin_data,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GcloudMissingError(
            "gcloud is not installed. It is a Phase 0 prerequisite — see docs/runbooks/gcp-hub-bootstrap.md §2."
        ) from exc


def _dig(config: dict[str, Any], dotted: str) -> str:
    """Resolve a dotted SOPS path, returning '' when any segment is absent."""
    node: object = config
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return ""
        node = node[part]
    return str(node) if node is not None else ""


def collect_sops_items(config: dict[str, Any]) -> tuple[list[SyncItem], list[SyncResult]]:
    """The catalog-tagged half. Missing values FAIL rather than sync empty.

    An empty payload is the worst outcome available here: it would be written,
    read successfully at boot, and produce a hub whose admin password is the
    empty string — a success-shaped failure. `_deploy-argocd-helm` already
    refuses to install on an empty decrypt for the same reason.
    """
    items: list[SyncItem] = []
    failures: list[SyncResult] = []
    for spec in secrets_synced_to_secret_manager():
        value = _dig(config, spec.key_path)
        secret_id = secret_manager_name(spec.key_path)
        if not value:
            failures.append(
                SyncResult(
                    secret_id,
                    "failed",
                    f"{spec.key_path} is absent or empty in SOPS; refusing to deliver an empty secret",
                )
            )
            continue
        items.append(SyncItem(secret_id=secret_id, origin=f"SOPS {spec.key_path}", value=value))
    return items, failures


def collect_spoke_items(config: dict[str, Any]) -> tuple[list[SyncItem], list[SyncResult]]:
    """The Kubernetes-generated half, read live from each spoke.

    The pseudo-paths below (`argocd.spokes.<env>.{token,ca}`) are not SOPS keys
    and never will be. They exist so both classes travel through the same name
    mapper: one naming rule, no second convention to drift from the first.
    """
    items: list[SyncItem] = []
    failures: list[SyncResult] = []
    for env in sorted(config.get("argocd", {}).get("spokes", {})):
        kubeconfig = k8s_kubeconfig.output_path(env)
        for field_name, json_path in (("token", ".data.token"), ("ca", r".data.ca\.crt")):
            secret_id = secret_manager_name(f"argocd.spokes.{env}.{field_name}")
            proc = subprocess.run(  # noqa: S603 - argv list, no shell
                [
                    "kubectl",
                    "--kubeconfig",
                    str(kubeconfig),
                    "get",
                    "secret",
                    SPOKE_TOKEN_SECRET,
                    "-n",
                    SPOKE_NAMESPACE,
                    "-o",
                    f"jsonpath={{{json_path}}}",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0 or not proc.stdout.strip():
                failures.append(
                    SyncResult(
                        secret_id,
                        "failed",
                        f"could not read {SPOKE_TOKEN_SECRET} from the {env} spoke "
                        f"(unreachable? for staging, is the homelab powered on?)",
                    )
                )
                continue
            items.append(
                SyncItem(
                    secret_id=secret_id,
                    origin=f"{env} spoke {SPOKE_TOKEN_SECRET}/{field_name}",
                    value=proc.stdout.strip(),
                )
            )
    return items, failures


def _destroy_superseded(secret_id: str, project_id: str) -> None:
    """Destroy every enabled version but the newest.

    DESTROY, not disable: a disabled version still bills, which is the trap the
    cost envelope names. Applied to every superseded version rather than only
    the one this run replaced, so a version added by hand is cleaned up too.
    """
    listed = _gcloud(
        ["versions", "list", secret_id, "--filter=state:enabled", "--format=json"],
        project_id,
    )
    if listed.returncode != 0:
        return
    try:
        versions = json.loads(listed.stdout or "[]")
    except json.JSONDecodeError:
        return
    # gcloud lists newest first; keep [0], destroy the rest.
    for version in versions[1:]:
        name = str(version.get("name", "")).rsplit("/", 1)[-1]
        if name:
            _gcloud(["versions", "destroy", name, f"--secret={secret_id}", "--quiet"], project_id)


def sync_item(item: SyncItem, project_id: str, dry_run: bool) -> SyncResult:
    """Create, update or skip one secret. Idempotent by payload comparison.

    The comparison is the point. `versions add` unconditionally would create a
    version per run — billed, and walking the six-version ceiling for no change.
    """
    exists = _gcloud(["describe", item.secret_id, "--format=value(name)"], project_id).returncode == 0

    if exists:
        current = _gcloud(["versions", "access", "latest", f"--secret={item.secret_id}"], project_id)
        if current.returncode == 0 and current.stdout == item.value:
            return SyncResult(item.secret_id, "unchanged", item.origin)
        if dry_run:
            return SyncResult(item.secret_id, "updated", f"{item.origin} (dry-run, not written)")
        added = _gcloud(["versions", "add", item.secret_id, "--data-file=-"], project_id, stdin_data=item.value)
        if added.returncode != 0:
            return SyncResult(item.secret_id, "failed", "versions add failed")
        _destroy_superseded(item.secret_id, project_id)
        return SyncResult(item.secret_id, "updated", item.origin)

    if dry_run:
        return SyncResult(item.secret_id, "created", f"{item.origin} (dry-run, not written)")
    created = _gcloud(
        ["create", item.secret_id, "--replication-policy=automatic", "--data-file=-"],
        project_id,
        stdin_data=item.value,
    )
    if created.returncode != 0:
        return SyncResult(item.secret_id, "failed", "create failed")
    return SyncResult(item.secret_id, "created", item.origin)


def sync_all(config: dict[str, Any], project_id: str, dry_run: bool = False) -> list[SyncResult]:
    """Deliver both classes, attempting every item even when some fail.

    Partial failure is the normal case rather than an edge one: staging's spoke
    lives in an on-demand homelab. Everything reachable is delivered, the rest is
    reported by name, and a later re-run completes it — which is what "drift is
    resolved by re-syncing" means operationally.
    """
    sops_items, results = collect_sops_items(config)
    spoke_items, spoke_failures = collect_spoke_items(config)
    results = [*results, *spoke_failures]
    for item in [*sops_items, *spoke_items]:
        results.append(sync_item(item, project_id, dry_run))
    return results
