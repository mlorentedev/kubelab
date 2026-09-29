"""Argo CD management — targetRevision swap for preview-per-PR and patch-back.

Encapsulates the kubectl patch payload so callers do not shell out by hand
(see feedback_no_manual_kubectl, feedback_never_adhoc_commands).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any


class ApplicationNotFoundError(Exception):
    """Raised when the Argo CD Application does not exist in the target namespace."""


class RevisionHeldError(Exception):
    """Raised when another branch holds the Application and the caller did not force (#1083)."""


class HubUnreachableError(Exception):
    """Raised when a drift check cannot reach the hub — never treat this as "clean" (#1016)."""


@dataclass(frozen=True)
class SetRevisionResult:
    old_revision: str
    new_revision: str
    sync_status: str


@dataclass(frozen=True)
class DriftCheckResult:
    clean: bool
    diff: str  # raw `kubectl diff` output; empty when clean


def _kubectl(kubeconfig: str, namespace: str, *args: str) -> list[str]:
    return ["kubectl", "--kubeconfig", kubeconfig, "-n", namespace, *args]


def _run_json(argv: list[str]) -> dict[str, Any]:
    proc = subprocess.run(argv, capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


# One retry absorbs a status write between the read and the patch; a second
# conflict in a row is contention worth surfacing.
_PATCH_ATTEMPTS = 2


def _read_application(app: str, kubeconfig: str, namespace: str) -> dict[str, Any]:
    get_argv = _kubectl(kubeconfig, namespace, "get", "application", app, "-o", "json")
    try:
        return _run_json(get_argv)
    except subprocess.CalledProcessError as exc:
        if "not found" in (exc.stderr or "").lower():
            raise ApplicationNotFoundError(f"Application '{app}' not found in namespace {namespace}") from exc
        raise


def _patch_argv(app: str, rev: str, before: dict[str, Any], kubeconfig: str, namespace: str) -> list[str]:
    # The read's resourceVersion is a precondition: a lane that repointed the
    # Application after our read turns this patch into a 409 instead of being
    # silently replaced by it.
    patch_body: dict[str, Any] = {"spec": {"source": {"targetRevision": rev}}}
    resource_version = before.get("metadata", {}).get("resourceVersion")
    if resource_version:
        patch_body["metadata"] = {"resourceVersion": resource_version}
    return _kubectl(
        kubeconfig,
        namespace,
        "patch",
        "application",
        app,
        "--type",
        "merge",
        "-p",
        json.dumps(patch_body),
        "-o",
        "json",
    )


def set_revision(
    app: str,
    rev: str,
    kubeconfig: str,
    namespace: str = "argocd",
    force: bool = False,
    release: str = "master",
) -> SetRevisionResult:
    """Patch the Application's spec.source.targetRevision to ``rev``.

    Returns a snapshot of the revision before/after and the post-patch sync status.
    Raises ApplicationNotFoundError if the Application does not exist.

    Refuses (RevisionHeldError) to replace a branch other than ``release`` with a
    different branch unless ``force``: that branch is another lane's live preview,
    and on 2026-09-25 the old value was only printed after the patch (#1083).
    Pointing back at ``release`` is never refused, because that is the patch-back.
    """
    for attempt in range(_PATCH_ATTEMPTS):
        before = _read_application(app, kubeconfig, namespace)
        old_revision = before["spec"]["source"]["targetRevision"]
        if not force and rev != release and old_revision not in (release, rev):
            raise RevisionHeldError(
                f"'{app}' is on '{old_revision}', not '{release}': another lane may be previewing it. "
                f"Ask that lane first; --force (FORCE=1 via make) replaces it anyway."
            )
        try:
            after = _run_json(_patch_argv(app, rev, before, kubeconfig, namespace))
            break
        except subprocess.CalledProcessError as exc:
            # A 409 means the object moved since the read, not that a lane took
            # it: Argo CD's controller bumps the resourceVersion with every status
            # write. So read again and let the guard decide who, if anyone, holds it.
            if "conflict" not in (exc.stderr or "").lower() or attempt == _PATCH_ATTEMPTS - 1:
                raise

    return SetRevisionResult(
        old_revision=old_revision,
        new_revision=after["spec"]["source"]["targetRevision"],
        sync_status=after.get("status", {}).get("sync", {}).get("status", "Unknown"),
    )


def check_drift(applications_dir: str, kubeconfig: str) -> DriftCheckResult:
    """Compare live Argo CD Application objects against their git manifests.

    A manifest changed in git (e.g. ADR-037's staging `selfHeal: false`) is a
    claim, not a deployed fact, until something reads back the live object —
    #1016 found that claim had been false for ~3 months because nothing did.

    `kubectl diff` exit codes: 0 = no diff, 1 = diff found, >1 = an actual
    error (commonly: hub unreachable). The >1 case must never be reported as
    clean — that would be the exact "CANNOT CHECK reported as OK" failure
    this function exists to prevent — so it raises instead of returning a
    false DriftCheckResult.
    """
    proc = subprocess.run(
        # --request-timeout: kubectl's default connection timeout against an
        # unreachable hub is ~60s (measured against aws1 down during #1016's
        # own investigation) — bound it so "hub unreachable" fails fast rather
        # than making every `make check-apps`/`deploy-apps` hang.
        ["kubectl", "diff", "-f", applications_dir, "--kubeconfig", kubeconfig, "--request-timeout=15s"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        return DriftCheckResult(clean=True, diff="")
    if proc.returncode == 1:
        return DriftCheckResult(clean=False, diff=proc.stdout)
    raise HubUnreachableError(
        f"kubectl diff exited {proc.returncode} (not 0 or 1) — cannot determine drift. "
        f"stderr: {(proc.stderr or '').strip()}"
    )
