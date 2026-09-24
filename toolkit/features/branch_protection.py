"""Reconcile GitHub branch protection with what `common.yaml` declares.

WHY THIS EXISTS. Every other control in this repository is codified — Gitea
repository settings, K8s manifests, DNS, the cloud firewall — while the one
protecting `master`, where all of it lands, was only ever a set of clicks in a
web UI. Nothing recorded what it was supposed to be, so nothing could say
whether it still was. It was found while acting on #1678: a decision had been
taken to change `strict`, and there was no reproducible way to apply it.

THE TRAP THIS MODULE IS SHAPED AROUND. `PUT /repos/{o}/{r}/branches/{b}/protection`
is a **whole-object replace, not a patch**. A body carrying only
`required_status_checks` does not leave the rest alone — it resets
`enforce_admins`, `required_pull_request_reviews`, `restrictions` and the
booleans to null/false, and answers **200**. This repository has
`enforce_admins: true`, so the naive write disables admin enforcement on
`master` silently, reporting success. Hence: GET the live object, overlay only
what is declared, PUT the whole thing back, GET again, and assert.

This is the same lesson as `gitea_repos.ensure_settings` (TOOL-063, #1633) — a
200 says the request was accepted, never that the fields were applied — with a
sharper edge, because here the unapplied fields are not merely unchanged, they
are actively cleared.

THE SHAPES DIFFER BETWEEN READ AND WRITE, which is the second half of the trap.
GET answers `enforce_admins: {"enabled": true}`; PUT wants `enforce_admins: true`.
Feeding a GET body straight back into a PUT is rejected or, worse, coerced.
`put_body` is the one place that translation lives.

DECLARE ONLY WHAT IS RECONCILED. `ci.branch_protection.<owner/name>.<branch>`
carries `strict` and `required_contexts` and nothing else. Everything else on the
object is passthrough, preserved verbatim from the live read. Modelling
reviewers, restrictions or rulesets here would be a redesign, and an
unreconciled field in a declaration is worse than an absent one: it reads as
managed while nothing checks it.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any

from toolkit.core.logging import logger

# Fields the GET returns as `{"enabled": bool}` and the PUT wants as a bare bool.
_ENABLED_WRAPPED = (
    "enforce_admins",
    "required_linear_history",
    "allow_force_pushes",
    "allow_deletions",
    "block_creations",
    "required_conversation_resolution",
    "lock_branch",
    "allow_fork_syncing",
)

# Present in the GET body, not accepted by the PUT — they have their own
# endpoints. Sending them is an error, so they are dropped deliberately rather
# than by omission.
_READ_ONLY_ON_PUT = ("url", "required_signatures", "contexts_url")


class BranchProtectionError(RuntimeError):
    """A protection change was accepted and did not take, or could not be read."""


@dataclass(frozen=True)
class DeclaredProtection:
    """The subset of branch protection this repository declares and reconciles."""

    strict: bool
    required_contexts: tuple[str, ...]

    @classmethod
    def from_config(cls, raw: dict[str, Any]) -> DeclaredProtection:
        contexts = raw.get("required_contexts") or []
        if not isinstance(contexts, list) or not all(isinstance(c, str) for c in contexts):
            raise BranchProtectionError("`required_contexts` must be a list of check names")
        if "strict" not in raw:
            raise BranchProtectionError("`strict` must be declared explicitly, not defaulted")
        return cls(strict=bool(raw["strict"]), required_contexts=tuple(contexts))


def load_declared(config: dict[str, Any]) -> dict[str, dict[str, DeclaredProtection]]:
    """Read `ci.branch_protection` out of the merged configuration: repository, then branch.

    KEYED BY REPOSITORY because `--repo` used to change only the target. The one
    declaration was kubelab's, so pointing the command at another repository
    compared that repository against kubelab's required contexts, and reported
    the difference as drift. A repository now has its own entry or none.

    The earlier shape (`ci.branch_protection.<branch>`) is refused rather than
    read as kubelab's: a key that is not `owner/name` fails loudly, so an old
    declaration cannot be silently attributed to a repository.
    """
    declared = (config.get("ci") or {}).get("branch_protection") or {}
    repos: dict[str, dict[str, DeclaredProtection]] = {}
    for repo, branches in declared.items():
        if repo.count("/") != 1 or not isinstance(branches, dict):
            raise BranchProtectionError(
                f"`ci.branch_protection` is keyed by repository (`owner/name`), then branch; "
                f"`{repo}` is not a repository"
            )
        repos[repo] = {branch: DeclaredProtection.from_config(raw) for branch, raw in branches.items()}
    return repos


def protection_changes(live: dict[str, Any], declared: DeclaredProtection) -> list[tuple[str, Any, Any]]:
    """Return `(field, live, declared)` for everything that disagrees.

    THE SINGLE PREDICATE. It answers what the plan shows, what the PUT needs to
    change, and what must be true afterwards. A second hand-written field list
    for the post-condition would be free to fall behind this one, and a field
    that is never checked is the defect this whole module exists to prevent.
    """
    checks = live.get("required_status_checks") or {}
    changes: list[tuple[str, Any, Any]] = []

    live_strict = bool(checks.get("strict", False))
    if live_strict != declared.strict:
        changes.append(("required_status_checks.strict", live_strict, declared.strict))

    live_contexts = tuple(checks.get("contexts") or [])
    if sorted(live_contexts) != sorted(declared.required_contexts):
        changes.append(("required_status_checks.contexts", list(live_contexts), list(declared.required_contexts)))

    return changes


def put_body(live: dict[str, Any], declared: DeclaredProtection) -> dict[str, Any]:
    """Build the FULL replace body: the live object, with the declaration overlaid.

    Every field the API accepts is carried through even when the declaration says
    nothing about it, because the PUT clears what it does not receive. The test
    that matters here asserts `enforce_admins` survives a declaration that never
    mentions it.
    """
    body: dict[str, Any] = {}

    for field in _ENABLED_WRAPPED:
        value = live.get(field)
        # `{"enabled": bool}` on read, bare bool on write.
        body[field] = bool(value.get("enabled", False)) if isinstance(value, dict) else bool(value)

    reviews = live.get("required_pull_request_reviews")
    if isinstance(reviews, dict):
        body["required_pull_request_reviews"] = {k: v for k, v in reviews.items() if k not in _READ_ONLY_ON_PUT}
    else:
        # Explicit null, not omission: omitting it is what removes it.
        body["required_pull_request_reviews"] = None

    restrictions = live.get("restrictions")
    if isinstance(restrictions, dict):
        body["restrictions"] = {
            key: [entry.get("login") or entry.get("slug") for entry in restrictions.get(key) or []]
            for key in ("users", "teams", "apps")
        }
    else:
        body["restrictions"] = None

    body["required_status_checks"] = {
        "strict": declared.strict,
        "contexts": list(declared.required_contexts),
    }

    return body


class GitHubBranchProtectionClient:
    """Talks to the protection endpoints through `gh api`, like `github_secrets`."""

    def __init__(self, repo: str) -> None:
        self.repo = repo

    def _gh(self, args: list[str], payload: dict[str, Any] | None = None) -> str:
        result = subprocess.run(
            ["gh", "api", *args],
            input=json.dumps(payload) if payload is not None else None,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise BranchProtectionError(f"gh api {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout

    def get_protection(self, branch: str) -> dict[str, Any] | None:
        try:
            raw = self._gh([f"repos/{self.repo}/branches/{branch}/protection"])
        except BranchProtectionError as exc:
            if "Branch not protected" in str(exc):
                return None
            raise
        parsed: dict[str, Any] = json.loads(raw)
        return parsed

    def put_protection(self, branch: str, body: dict[str, Any]) -> None:
        self._gh(
            [
                "--method",
                "PUT",
                f"repos/{self.repo}/branches/{branch}/protection",
                "--input",
                "-",
            ],
            payload=body,
        )


def ensure_protection(
    client: GitHubBranchProtectionClient,
    branch: str,
    declared: DeclaredProtection,
) -> list[tuple[str, Any, Any]]:
    """Apply the declaration, then READ IT BACK and assert it took.

    Returns the changes that were applied; an empty list means the branch already
    agreed and nothing was written, which is what makes a second run `changed=0`.
    """
    live = client.get_protection(branch)
    if live is None:
        raise BranchProtectionError(
            f"`{branch}` is not protected at all. This command reconciles an existing "
            f"protection object; creating one from nothing is a different decision and "
            f"is not made here."
        )

    pending = protection_changes(live, declared)
    if not pending:
        return []

    client.put_protection(branch, put_body(live, declared))

    after = client.get_protection(branch)
    if after is None:
        raise BranchProtectionError(
            f"`{branch}` does not read back as protected after being written. The PUT was "
            f"accepted, so this is not a permission problem — the protection object is gone."
        )

    remaining = protection_changes(after, declared)
    if remaining:
        detail = ", ".join(
            f"{field}: live {live_v!r}, declared {declared_v!r}" for field, live_v, declared_v in remaining
        )
        raise BranchProtectionError(
            f"`{branch}` still disagrees after a PUT that returned success: {detail}. "
            f"A 200 from this endpoint says the request was accepted, never that the fields "
            f"were applied."
        )

    if bool((after.get("enforce_admins") or {}).get("enabled")) != bool(
        (live.get("enforce_admins") or {}).get("enabled")
    ):
        raise BranchProtectionError(
            "`enforce_admins` changed as a side effect of writing the status checks. That is "
            "the whole-object-replace trap this module exists to avoid; the protection object "
            "must be restored by hand before retrying."
        )

    logger.debug(f"{branch}: applied {len(pending)} protection change(s)")
    return pending
