"""Verify a product promotion by its consequence, not by a green job (GITOPS-003 AC4, #1478).

A merged overlay is a claim. Twice it was not a deploy: eleven web releases
never reached prod while every job was green, and a staging auto-sync panicked,
was never retried, and nothing in the delivery path noticed (lesson-407). This
check reads the two consequences an operator can observe from the mesh, for
any contract-managed product in the registry (ADR-067):

1. **The Application on the hub.** Ready means `sync.status == Synced` at
   `origin/master` HEAD and the last operation `Succeeded`. The operation's own
   revision is NOT compared with HEAD: a commit that does not touch the overlay
   moves `sync.revision` without starting an operation, so on 2026-10-20 the
   live `kubelab-staging` was Synced at HEAD with its last operation at an
   older commit. A failed operation AT HEAD is red at once, because Argo makes
   one automated attempt per revision and will not retry it.
2. **What the product serves.** A platform convention, not a per-product
   setting: every contract-managed product answers `GET https://<host>/version.json`
   with `{"version": "X.Y.Z", "commit": "<7 hex>"}`, where `commit` is its image
   tag minus `sha-`. web is the first to implement it (web#435; interface fixed
   on #1478 2026-10-20). The host is the contract's `hostnames[env]`. A
   `sha-<hex>` tag is compared with `commit`, a semver tag (prod, ADR-046)
   with `version`. A payload without `commit` is "not
   verifiable yet", its own verdict, never a pass.

The host is read only once the Application is ready, so a match can never be
the previous deploy answering. Health of the whole Application is not a
condition: staging was Degraded on 2026-10-20 by the `vikunja` Deployment
(ProgressDeadlineExceeded, #1783), unrelated to web.

Every input is read from `origin/master`, never the worktree (lesson-479).
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Any, Callable

import yaml

from toolkit.features.argo_manager import HubUnreachableError

#: Default deadline: above the 0–6 minute merge→sync lag measured over seven
#: staging syncs, plus the poll interval (spec Risk 3).
DEFAULT_TIMEOUT = 600.0
DEFAULT_POLL = 15.0

_SHA_TAG = re.compile(r"^sha-([0-9a-f]{7,40})$")


class Verdict(IntEnum):
    """The exit code of `verify-product`. Callers branch on these numbers."""

    VERIFIED = 0
    FAILED = 1
    CANNOT_CHECK = 2
    NOT_VERIFIABLE = 3
    SUPERSEDED = 4


class Served(Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    ABSENT = "absent"


class HostUnreachableError(Exception):
    """The web host could not be reached at all (DNS, connection, TLS) — never a pass."""


class ServedError(Exception):
    """The host answered, but not with a version.json (wrong status, not JSON)."""


@dataclass(frozen=True)
class AppState:
    ready: bool
    failed: bool
    summary: str


def classify_application(app: dict[str, Any], head: str) -> AppState:
    """Judge an Argo CD Application against the commit it should be at."""
    status = app.get("status") or {}
    sync = status.get("sync") or {}
    op = status.get("operationState") or {}
    phase = op.get("phase")
    op_revision = (op.get("syncResult") or {}).get("revision") or ((op.get("operation") or {}).get("sync") or {}).get(
        "revision"
    )
    summary = (
        f"sync={sync.get('status')} at {str(sync.get('revision'))[:7]} (HEAD {head[:7]}); "
        f"last operation {phase} at {str(op_revision)[:7]}: {op.get('message', '<no message>')}"
    )
    failed = phase in ("Failed", "Error") and op_revision == head
    ready = sync.get("status") == "Synced" and sync.get("revision") == head and phase == "Succeeded"
    return AppState(ready=ready, failed=failed, summary=summary)


def classify_served(payload: dict[str, Any], tag: str) -> tuple[Served, str]:
    """Compare a product's version.json with the image tag pinned at HEAD.

    Returns the outcome and a one-line detail naming what was served and what
    was expected, so a red run says which side is wrong.
    """
    sha = _SHA_TAG.match(tag)
    if sha is None:
        # A semver tag (prod): the image is a digest re-tag of a staging sha,
        # so the tag names a release, not a commit.
        served = payload.get("version")
        detail = f"serves version {served!r}, expected {tag!r}"
        return (Served.MATCH if served == tag else Served.MISMATCH), detail
    if "commit" not in payload:
        return Served.ABSENT, f"serves no `commit` (version {payload.get('version')!r}), expected {sha.group(1)!r}"
    # Strict equality: the convention fixes `commit` as the tag minus `sha-`, so
    # a prefix match would accept a truncated or differently built answer.
    # "local" (built without the arg) is simply another value, and a mismatch.
    served = str(payload["commit"])
    expected = sha.group(1)
    detail = f"serves commit {served!r}, expected {expected!r}"
    if served != expected and (served.startswith(expected) or expected.startswith(served)):
        # Same commit, other length: the producer breaks the convention, which is
        # a different fix from "another image is running".
        detail += "; same commit at another length, so the producer breaks the convention (tag minus `sha-`)"
    return (Served.MATCH if served == expected else Served.MISMATCH), detail


def pinned_tag(deployments_yaml: str, image_name: str) -> str:
    """The tag of ``image_name`` in a rendered overlay's deployments.yaml."""
    suffix = f"/{image_name}:"
    for doc in yaml.safe_load_all(deployments_yaml):
        spec = ((doc or {}).get("spec") or {}).get("template", {}).get("spec") or {}
        for container in spec.get("containers") or []:
            image = container.get("image", "")
            if suffix in image:
                return image.rsplit(":", 1)[1]
    raise ValueError(f"no container runs {image_name} in the rendered overlay")


def git_show(rev: str, path: str) -> str:
    """A file as committed at ``rev``: the deploy is judged against master, never the worktree (lesson-479)."""
    return subprocess.run(["git", "show", f"{rev}:{path}"], capture_output=True, text=True, check=True).stdout


def descends_from(head: str, rev: str, fetch: bool = False) -> bool:
    """True when ``rev`` is a strict descendant of ``head``: a later master, not the same or an older one.

    ``fetch`` first fetches origin/master, so a commit merged while polling is
    known locally. An unknown ``rev`` is not a descendant, so the caller waits
    for it instead of judging it.
    """
    if rev == head:
        return False
    if fetch:
        subprocess.run(["git", "fetch", "--quiet", "origin", "master"], capture_output=True, text=True, check=False)
    proc = subprocess.run(["git", "merge-base", "--is-ancestor", head, rev], capture_output=True, text=True)
    return proc.returncode == 0


def origin_head() -> str:
    """Fetch, then the sha of origin/master: the commit Argo CD should be at."""
    subprocess.run(["git", "fetch", "--quiet", "origin", "master"], capture_output=True, text=True, check=True)
    return subprocess.run(
        ["git", "rev-parse", "origin/master"], capture_output=True, text=True, check=True
    ).stdout.strip()


VERSION_PATH = "/version.json"


class NoContractError(ValueError):
    """The app is unregistered or in-tree: nothing declares its hostname or image."""


def targets_at(rev: str, app: str, env: str, show: Callable[[str, str], str] = git_show) -> tuple[str, str]:
    """The tag ``env``'s rendered overlay pins for ``app`` at ``rev``, and its version.json URL.

    The hostname and image come from the contract snapshot, the product's own
    declaration, which the values are rendered from; the registry only says
    whether the app has a contract at all.
    """
    from toolkit.features.product_registry import REGISTRY_RELPATH, Registry

    registry = Registry.model_validate(yaml.safe_load(show(rev, str(REGISTRY_RELPATH))))
    entry = registry.products.get(app)
    if entry is None or not entry.contract_managed:
        raise NoContractError(f"'{app}' has no product contract at {rev[:7]}: nothing declares its hostname")
    contract = yaml.safe_load(show(rev, f"infra/config/products/contracts/{app}.yaml"))
    host = contract["hostnames"][env]
    image_name = contract["image"].rsplit("/", 1)[1]
    tag = pinned_tag(show(rev, f"infra/k8s/overlays/{env}/generated/deployments.yaml"), image_name)
    return tag, f"https://{host}{VERSION_PATH}"


def read_application(app: str, kubeconfig: str) -> dict[str, Any]:
    """The Application as the hub holds it; any failure to read it is HubUnreachableError."""
    import json

    proc = subprocess.run(
        [
            "kubectl",
            "--kubeconfig",
            kubeconfig,
            "-n",
            "argocd",
            "get",
            "application",
            app,
            "-o",
            "json",
            "--request-timeout=15s",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise HubUnreachableError(f"kubectl get application {app}: {proc.stderr.strip()[:200]}")
    return json.loads(proc.stdout)


def fetch_version_json(url: str, timeout: float = 10.0) -> dict[str, Any]:
    """GET ``url`` uncached; the two failure kinds stay distinct for the verdict."""
    import httpx

    try:
        resp = httpx.get(url, headers={"Cache-Control": "no-cache"}, timeout=timeout, follow_redirects=False)
    except httpx.HTTPError as exc:
        raise HostUnreachableError(f"{url}: {exc}") from exc
    content_type = resp.headers.get("content-type", "")
    if resp.status_code != 200:
        raise ServedError(f"{url} answered HTTP {resp.status_code} ({content_type})")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise ServedError(f"{url} answered {content_type}, not JSON") from exc
    if not isinstance(payload, dict):
        raise ServedError(f"{url} answered JSON that is not an object")
    return payload


class _Superseded(Exception):
    """The Application is at a later master that pins another tag."""


class _PinUnreadable(Exception):
    """The tag a later master pins could not be read from git."""


def _judged_revision(
    app: dict[str, Any],
    head: str,
    tag: str,
    descends: Callable[[str], bool],
    tag_at: Callable[[str], str],
) -> str:
    """The revision the Application is judged at: HEAD, or a later master that keeps the same tag."""
    synced = ((app.get("status") or {}).get("sync") or {}).get("revision")
    if not synced or synced == head or not descends(synced):
        return head
    try:
        newer = tag_at(synced)
    except (subprocess.CalledProcessError, KeyError, ValueError, yaml.YAMLError) as exc:
        raise _PinUnreadable(str(exc)) from exc
    if newer != tag:
        raise _Superseded(f"the Application is synced at {synced[:7]}, which pins {newer}, not {tag} as {head[:7]} did")
    return synced


def verify(
    *,
    head: str,
    tag: str,
    read_app: Callable[[], dict[str, Any]],
    fetch_served: Callable[[], dict[str, Any]],
    descends: Callable[[str], bool],
    tag_at: Callable[[str], str],
    timeout: float = DEFAULT_TIMEOUT,
    poll: float = DEFAULT_POLL,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[Verdict, list[str]]:
    """Poll both consequences until they agree with HEAD or the deadline passes.

    At the deadline the verdict follows the LAST observation: unreachable is
    CANNOT_CHECK, a payload without `commit` is NOT_VERIFIABLE, anything else
    (not synced, another commit served, an HTTP error) is FAILED. The
    Application's summary, with `operationState.message`, is in every report.

    HEAD is read once, but master can move while this polls (GITOPS-007,
    #2584). When the Application is at a revision that ``descends`` from HEAD,
    the tag that revision pins (``tag_at``) decides: the same tag means the
    promotion is still the one live, so that revision is judged instead of
    HEAD; another tag means a later merge replaced it, which is SUPERSEDED at
    once. That is not a pass under the new tag and not red: the promotion asked
    about can no longer be observed, and the newer one has its own check.
    """
    deadline = now() + timeout
    app_line = "Application not read"
    while True:
        verdict, served_line = Verdict.FAILED, "host not read: the Application is not ready at HEAD"
        try:
            app = read_app()
            target = _judged_revision(app, head, tag, descends, tag_at)
            state = classify_application(app, target)
        except HubUnreachableError as exc:
            verdict, app_line = Verdict.CANNOT_CHECK, f"hub unreachable: {exc}"
        except _Superseded as exc:
            return Verdict.SUPERSEDED, [
                str(exc),
                classify_application(app, head).summary,
                "a later merge replaced this promotion; verify that one instead",
            ]
        except _PinUnreadable as exc:
            verdict, app_line = Verdict.CANNOT_CHECK, f"the pin at the synced revision could not be read: {exc}"
        else:
            app_line = state.summary
            if state.failed:
                return Verdict.FAILED, [app_line, "Argo CD does not retry a failed revision: make sync-app"]
            if state.ready:
                try:
                    outcome, served_line = classify_served(fetch_served(), tag)
                except HostUnreachableError as exc:
                    verdict, served_line = Verdict.CANNOT_CHECK, f"host unreachable: {exc}"
                except ServedError as exc:
                    served_line = str(exc)
                else:
                    if outcome is Served.MATCH:
                        return Verdict.VERIFIED, [app_line, served_line]
                    if outcome is Served.ABSENT:
                        verdict = Verdict.NOT_VERIFIABLE
        if now() >= deadline:
            return verdict, [app_line, served_line, f"deadline of {timeout:.0f}s reached"]
        sleep(poll)
