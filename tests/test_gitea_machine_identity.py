"""AUTH-004 C5 (#1013) — the machine identity is declared, scoped, and cannot log in.

ADR-062 D1 gives the platform a third identity class alongside the two humans:
an agent that acts on the forge without being a person. `common.yaml`'s own
comment above `apps.auth.identities` anticipated it — *"the set is expected to
grow (a second human, a machine class) and each growth should add a row, not a
new key name for every consumer to learn"* — so this adds a row rather than a
parallel declaration.

Three properties are asserted here and the rest live in the demonstration on the
ticket, because they can only be observed against a running Gitea:

1. **The name is declared once.** A machine account named in an Ansible variable
   instead of in the identity map is the alias that renamed Gitea's only admin
   on 2026-08-23 (#1352, lesson-379), one class down.

2. **The token is registered for the environment that has it.** Gitea's identity
   environment is prod (`gitea_identity_env`), so a catalog entry claiming any
   other env makes the secret vanish from every audit silently — the ANSIBLE-033
   failure mode, which `SecretSpec.envs` invites because it reads like a storage
   location and is an audit dimension.

3. **The provisioning cannot print the token.** `generate-access-token` shows the
   value exactly once, so the run that mints it is the only run that could leak
   it, and a transcript is a durable artefact no scanner reaches.

R4 settled the ordering these tasks must follow: `prohibit_login` is in Gitea's
`EditUserOption` and **not** in `CreateUserOption`, so the account cannot be
created already blocked — create, then PATCH, then mint. Unlike the OIDC secret,
`prohibit_login` reads back (`GET /api/v1/admin/users` returns it), so this
converges by observation and needs no marker file.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
COMMON = REPO / "infra/config/values/common.yaml"
ROLE = REPO / "infra/ansible/roles/beelink_services"

BOT_TOKEN_KEY = "apps.services.core.gitea.bot_token"

MINT_TASK = "Mint the machine account's scoped token"
RECORD_TASK = "Record the machine token in SOPS"
PROHIBIT_TASK = "Prohibit interactive login for the machine account"
CREATE_TASK = "Ensure the Gitea machine account exists"


def _tasks() -> list[dict]:
    return [t for t in yaml.safe_load((ROLE / "tasks/main.yml").read_text()) if isinstance(t, dict)]


def _task(name: str) -> dict:
    for task in _tasks():
        if task.get("name") == name:
            return task
    raise AssertionError(
        f"no task named {name!r} in beelink_services/tasks/main.yml; "
        "the machine-identity provisioning is missing or was renamed"
    )


def test_the_machine_identity_is_declared_in_the_identity_map() -> None:
    """A row in `apps.auth.identities`, not a literal in a playbook."""
    common = yaml.safe_load(COMMON.read_text())
    identities = common["apps"]["auth"]["identities"]

    assert "machine" in identities, (
        "apps.auth.identities has no `machine` row. The machine account's name must be "
        "declared here like the humans', or it becomes a literal in an Ansible variable — "
        "which is the alias shape that renamed Gitea's only admin on 2026-08-23."
    )
    assert identities["machine"], "apps.auth.identities.machine is declared but empty"
    assert identities["machine"] not in (identities["superadmin"], identities["operator"]), (
        "the machine identity collides with a human one; the whole point of the third "
        "class is that an agent's actions are not attributed to a person"
    )


def test_the_playbook_resolves_the_bot_name_through_the_map() -> None:
    """The anti-alias assertion: the name must not appear as a literal."""
    playbook = (REPO / "infra/ansible/playbooks/provision-bee.yml").read_text()
    common = yaml.safe_load(COMMON.read_text())
    machine = common["apps"]["auth"]["identities"]["machine"]

    live = [
        line
        for line in playbook.splitlines()
        if machine in line and not line.strip().startswith("#")
    ]
    assert not live, (
        f"the machine account name {machine!r} appears literally in provision-bee.yml:\n  "
        + "\n  ".join(live)
        + "\n\nResolve it through apps.auth.identities.machine, so renaming the row is one edit."
    )
    assert "apps.auth.identities.machine" in playbook, (
        "provision-bee.yml never reads apps.auth.identities.machine — a declaration with "
        "no readers is a comment (lesson-380)"
    )


def test_the_bot_token_is_registered_for_the_environment_that_holds_it() -> None:
    """`envs` is the audit dimension, and Gitea's identity environment is prod."""
    from toolkit.features.secrets_manager import SECRET_CATALOG

    spec = next((s for s in SECRET_CATALOG if s.key_path == BOT_TOKEN_KEY), None)
    assert spec is not None, (
        f"{BOT_TOKEN_KEY} is not in SECRET_CATALOG. An unregistered secret is invisible to "
        "`make secrets-audit`, so its absence can never be reported."
    )
    assert "prod" in spec.envs, (
        f"{BOT_TOKEN_KEY} declares envs={spec.envs!r}. Gitea's identity environment is prod "
        "(gitea_identity_env), and `envs` says which environments must HAVE the secret, not "
        "which file stores it — a tuple matching no real env drops it from every audit silently "
        "(ANSIBLE-033)."
    )


def test_nothing_that_touches_the_token_can_print_it() -> None:
    """`generate-access-token` shows the value once; that run is the only chance to leak it."""
    leaky = [
        name
        for name in (MINT_TASK, RECORD_TASK)
        if _task(name).get("no_log") is not True
    ]
    assert not leaky, (
        f"these tasks handle the machine token without `no_log: true`: {leaky}. "
        "Ansible echoes a registered command's stdout on failure and under -v, and a "
        "transcript is a durable artefact that no secret scanner reaches."
    )


def test_the_token_is_minted_only_when_there_is_none() -> None:
    """Minting is not idempotent — a second run would issue a second live token."""
    condition = str(_task(MINT_TASK).get("when") or "")
    assert "bot_token" in condition, (
        f"the mint task's `when` is {condition!r}. `generate-access-token` always succeeds and "
        "always returns a NEW token, so an ungated task issues a fresh credential on every "
        "provision and orphans the previous one inside Gitea. Gate it on the recorded secret "
        "being absent."
    )


def test_login_is_prohibited_by_comparison_rather_than_unconditionally() -> None:
    """`prohibit_login` reads back, so this must converge by observation.

    An unconditional PATCH is the #1400 defect one service over: the write is a
    no-op in effect and a change in the report, so the guard fires forever.
    """
    task = _task(PROHIBIT_TASK)
    condition = str(task.get("when") or "")
    assert condition, (
        "the prohibit-login task has no `when`. Unlike the OIDC client secret, "
        "`prohibit_login` is readable via `GET /api/v1/admin/users`, so this converges by "
        "comparison — patch only when the live value disagrees. An unconditional PATCH "
        "reports a change on every provision, which is ANSIBLE-054 in a new place."
    )


def test_the_account_is_created_only_when_absent() -> None:
    """R4's ordering: create, then PATCH, then mint — the account exists briefly loginable."""
    tasks = [t.get("name") for t in _tasks()]
    for earlier, later in ((CREATE_TASK, PROHIBIT_TASK), (PROHIBIT_TASK, MINT_TASK)):
        assert tasks.index(earlier) < tasks.index(later), (
            f"{earlier!r} must run before {later!r}. `prohibit_login` is in EditUserOption and "
            "not in CreateUserOption, so the account cannot be created already blocked (R4); "
            "the token must not be minted before the block is applied."
        )
