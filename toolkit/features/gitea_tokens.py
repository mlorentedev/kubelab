"""Rotating a Gitea machine token, as one operation instead of three (TOOL-035, #1076).

WHY THIS MODULE EXISTS AT ALL. `GiteaBasicAuthClient.revoke_token` was reachable
only from Python, so the runbook's rotation step read "call this method" -- which
is not a step an operator can take, and makes the claim "credential loss is
recoverable" true only for someone willing to open a REPL. The code was right and
the last mile was missing.

ROTATION IS TWO STEPS BECAUSE THE SOPS KEY IS THE MINT GATE. The Ansible mint task
carries `when: not gitea_bot_token`: it acts only when the recorded secret is
ABSENT, which is what keeps a re-provision from minting a duplicate on every run.
The consequence is that revoking alone strands the account -- the live token is
dead and the gate is still shut, so nothing re-mints and every consumer fails
until a human remembers the second half. So revoke and unset travel together.

ORDER: REVOKE, THEN UNSET. The two failure modes are not symmetric, and the
asymmetry decides it.

- Revoke succeeds, unset fails -> the bot is down, loudly, and the remedy is a
  single command this module prints. Detectable, recoverable.
- Unset succeeds, revoke fails -> the gate is open while the old token is still
  live, so the next provision mints a SECOND credential. That is exactly the
  state `bot_token`'s rotate_note forbids ("the account would hold two live
  credentials and nothing records which consumer holds which"), it is silent,
  and no audit reports it.

Prefer the loud recoverable failure to the quiet unrecoverable one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from toolkit.features.gitea_client import expand_grant


@dataclass(frozen=True)
class RotatableToken:
    """One credential's rotation coordinates.

    `identity` is a key into `apps.auth.identities` rather than a username: the
    map is the SSOT (AUTH-004 #1390 removed the last literal), so `machine` keeps
    resolving after the account behind it is renamed.
    """

    secret_key: str
    token_name: str
    identity: str


#: The tokens this command can rotate.
#:
#: MIRRORED IN ANSIBLE, GUARDED BY A TEST. `beelink_services/tasks/main.yml`
#: hardcodes the same `--token-name` values and the same `toolkit secrets set`
#: key paths in its mint tasks. Declaring them a second time here is duplication,
#: and the honest fix would be a single declaration in `common.yaml` read by
#: both -- rejected for now only because it edits a provisioning path that
#: currently works and cannot be exercised without a live re-provision.
#: `tests/test_gitea_token_rotation_registry.py` parses that YAML and fails if
#: the two ever disagree, which makes the duplication detectable rather than
#: latent. If the SSOT move happens later, delete this note with the constant.
ROTATABLE_TOKENS: dict[str, RotatableToken] = {
    "bot": RotatableToken(
        secret_key="apps.services.core.gitea.bot_token",
        token_name="kubelab-provisioning",
        identity="machine",
    ),
    "admin": RotatableToken(
        secret_key="apps.services.core.gitea.admin_token",
        token_name="kubelab-reconciler",
        identity="superadmin",
    ),
    # The PR reviewer (TOOL-080). Minted by the same role, gated the same way.
    "reviewer": RotatableToken(
        secret_key="apps.services.core.gitea.reviewer_token",
        token_name="kubelab-reviewer",
        identity="reviewer",
    ),
    # The token n8n comments with when a review fails (TOOL-093, #1957): a second
    # token on the reviewer's account, so the comment has the author a review would.
    "review_notice": RotatableToken(
        secret_key="apps.services.core.gitea.review_notice_token",
        token_name="kubelab-review-notice",
        identity="reviewer",
    ),
}

#: What the reviewer's token must hold -- exactly, not at least. The requirement is a
#: measurement, not code in this repository: PR-Agent makes the calls. Measured
#: 2026-09-24 in a local Gitea 1.25.5 against PR-Agent 0.45.0
#: (`specs/TOOL-080-forge-pr-reviewer/verification.md`). `write:issue` posts and edits
#: the review comment; `read:repository` reads the PR, its files, diff and commits.
REVIEWER_SCOPES: frozenset[str] = frozenset({"write:issue", "read:repository"})

#: What the review-notice token must hold -- exactly. A decision, not a measurement:
#: the owner chose on 2026-10-18 that n8n gets a token of its own that can write
#: comments and nothing else, because the workflow sits behind a public route. The
#: measurement that makes it sufficient is the reviewer's own (`POST issues/{n}/comments`
#: answers 201 to `write:issue` alone); reading the PR is not part of the job.
REVIEW_NOTICE_SCOPES: frozenset[str] = frozenset({"write:issue"})


@dataclass(frozen=True)
class RotationPlan:
    """What a rotation would do, resolved against the forge's recorded state."""

    label: str
    username: str
    token_name: str
    secret_key: str
    secret_present: bool

    @property
    def is_noop(self) -> bool:
        """True when SOPS already holds no value for this token.

        NOT a claim that the forge holds no token -- this module cannot know that
        without the admin password, and `revoke_token` answers it by consequence.
        It means only that the mint gate is already open, so `--apply` has at most
        the revoke half left to do. Naming it `is_noop` would overstate it, which
        is why the caller still offers to run.
        """
        return not self.secret_present


def plan_rotation(label: str, identities: dict[str, str], secret_present: bool) -> RotationPlan:
    """Resolve a registry entry against the identity map and the recorded secret.

    Pure: takes the two facts it needs rather than reading SOPS or the forge, so
    the interesting cases are testable without either.
    """
    if label not in ROTATABLE_TOKENS:
        known = ", ".join(sorted(ROTATABLE_TOKENS))
        raise KeyError(f"unknown token {label!r}; known: {known}")

    spec = ROTATABLE_TOKENS[label]
    if spec.identity not in identities:
        raise KeyError(f"apps.auth.identities has no {spec.identity!r} entry — cannot resolve the account to rotate")

    return RotationPlan(
        label=label,
        username=identities[spec.identity],
        token_name=spec.token_name,
        secret_key=spec.secret_key,
        secret_present=secret_present,
    )


def format_rotation_plan(plan: RotationPlan) -> str:
    """Render the plan for a human about to authorise an outage."""
    lines = [
        f"  account       {plan.username}",
        f"  token name    {plan.token_name}",
        f"  SOPS key      {plan.secret_key}",
        f"  recorded now  {'yes' if plan.secret_present else 'no — the mint gate is already open'}",
        "",
        "  would: revoke the token in Gitea, then clear the SOPS key so the",
        "         mint task can issue a replacement on the next provision.",
    ]
    return "\n".join(lines)


# --- scope drift: the minted token against the declared grant (TOOL-056, #1551) ---------------
#
# `tests/test_gitea_token_scopes.py` ties the DECLARATION to the code's requirement.
# This ties the LIVE token to the declaration, the step that test cannot see: Gitea
# cannot edit a token's scopes after minting and the mint task is gated on the SOPS
# key being absent, so a widened declaration stays inert until a rotation. Both prod
# tokens were in that state on 2026-09-01 and each surfaced only as a 403.
#
# REPORT, NEVER ROTATE. A rotation opens an outage window and is a decision; the
# check names the command and stops.

#: Gitea's scope that grants every category. Normalisation collapses a full grant to
#: this literal, so it covers any declared scope and is never itself declared.
ALL_SCOPE = "all"


class ScopeVerdict(Enum):
    """One token's standing against its declaration. Only OK is converged."""

    OK = "ok"
    MISSING = "missing"  # the minted token lacks a declared scope: calls fail today
    UNDECLARED = "undeclared"  # it holds more than declared: privilege nobody decided
    ABSENT = "absent"  # no token carries the registered name on that account
    DUPLICATE = "duplicate"  # two tokens share the name: nothing records which is used


@dataclass(frozen=True)
class ScopeCheck:
    """What one registered token was minted with, compared with what is declared."""

    label: str
    token_name: str
    declared: frozenset[str]
    minted: frozenset[str]
    missing: frozenset[str]
    undeclared: frozenset[str]
    verdict: ScopeVerdict


def parse_scopes(scopes: str | Iterable[str]) -> frozenset[str]:
    """Normalise a comma-separated grant or a listing's array into a set.

    Order, case and whitespace carry no meaning in Gitea's scope strings, and its
    normalisation is free to reorder them, so none of them may decide a verdict.
    """
    items = scopes.split(",") if isinstance(scopes, str) else scopes
    return frozenset(s.strip().lower() for s in items if s and s.strip())


def check_token_scopes(label: str, declared_grant: str, tokens: list[dict[str, Any]]) -> ScopeCheck:
    """Compare the registered token in an account's listing with its declared grant.

    Pure: takes the declaration and the `GET /users/{u}/tokens` payload rather than
    reading either, so every verdict is testable without a forge.

    Both directions are drift. Missing breaks calls; undeclared is privilege the
    SSOT never granted, and for the admin token that is exactly the delete
    capability #1076 refuses. Each side is widened with `expand_grant` before the
    other is subtracted from it, because a write scope already carries its read.
    """
    if label not in ROTATABLE_TOKENS:
        known = ", ".join(sorted(ROTATABLE_TOKENS))
        raise KeyError(f"unknown token {label!r}; known: {known}")

    token_name = ROTATABLE_TOKENS[label].token_name
    declared = parse_scopes(declared_grant)
    matches = [t for t in tokens if t.get("name") == token_name]

    if len(matches) != 1:
        verdict = ScopeVerdict.ABSENT if not matches else ScopeVerdict.DUPLICATE
        return ScopeCheck(label, token_name, declared, frozenset(), frozenset(), frozenset(), verdict)

    minted = parse_scopes(matches[0].get("scopes") or [])
    missing = frozenset() if ALL_SCOPE in minted else frozenset(declared - expand_grant(set(minted)))
    undeclared = frozenset(minted - expand_grant(set(declared)))

    if missing:
        verdict = ScopeVerdict.MISSING
    elif undeclared:
        verdict = ScopeVerdict.UNDECLARED
    else:
        verdict = ScopeVerdict.OK
    return ScopeCheck(label, token_name, declared, minted, missing, undeclared, verdict)
