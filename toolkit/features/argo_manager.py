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


@dataclass(frozen=True)
class SetRevisionResult:
    old_revision: str
    new_revision: str
    sync_status: str


def _kubectl(kubeconfig: str, namespace: str, *args: str) -> list[str]:
    return ["kubectl", "--kubeconfig", kubeconfig, "-n", namespace, *args]


def _run_json(argv: list[str]) -> dict[str, Any]:
    proc = subprocess.run(argv, capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


def set_revision(
    app: str,
    rev: str,
    kubeconfig: str,
    namespace: str = "argocd",
) -> SetRevisionResult:
    """Patch the Application's spec.source.targetRevision to ``rev``.

    Returns a snapshot of the revision before/after and the post-patch sync status.
    Raises ApplicationNotFoundError if the Application does not exist.
    """
    get_argv = _kubectl(kubeconfig, namespace, "get", "application", app, "-o", "json")
    try:
        before = _run_json(get_argv)
    except subprocess.CalledProcessError as exc:
        if "not found" in (exc.stderr or "").lower():
            raise ApplicationNotFoundError(f"Application '{app}' not found in namespace {namespace}") from exc
        raise

    old_revision = before["spec"]["source"]["targetRevision"]

    payload = json.dumps({"spec": {"source": {"targetRevision": rev}}})
    patch_argv = _kubectl(
        kubeconfig,
        namespace,
        "patch",
        "application",
        app,
        "--type",
        "merge",
        "-p",
        payload,
        "-o",
        "json",
    )
    after = _run_json(patch_argv)

    return SetRevisionResult(
        old_revision=old_revision,
        new_revision=after["spec"]["source"]["targetRevision"],
        sync_status=after.get("status", {}).get("sync", {}).get("status", "Unknown"),
    )
