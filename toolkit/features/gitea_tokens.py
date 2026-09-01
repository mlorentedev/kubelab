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
}


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
