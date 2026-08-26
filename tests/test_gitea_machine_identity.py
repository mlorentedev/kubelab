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

import os
import pathlib
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
COMMON = REPO / "infra/config/values/common.yaml"
ROLE = REPO / "infra/ansible/roles/beelink_services"

BOT_TOKEN_KEY = "apps.services.core.gitea.bot_token"

MINT_TASK = "Mint the machine account's scoped token"
RECORD_TASK = "Record the machine token in SOPS"


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


# --- Script-level behaviour ---------------------------------------------------
# The account and its login block live in gitea-bootstrap.sh rather than in an
# Ansible task: the check is a pipeline of nested quotes, and YAML folding plus
# argv splitting mangled it before it reached the container. Measured, not
# predicted — the equivalent `command:` failed on the live node while the same
# pipeline typed by hand returned `manu`, exit 0.
#
# These run the real script with `su`, `curl` and `wget` stubbed on PATH, so they
# assert behaviour rather than text.

SCRIPT = ROLE / "files/gitea-bootstrap.sh"
BOT = "hefesto"


@pytest.fixture
def bot_harness(tmp_path: pathlib.Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"

    (bin_dir / "wget").write_text("#!/bin/sh\nexit 0\n")

    def build(*, bot_exists: bool, prohibited: bool) -> None:
        rows = f"1\t{BOT}\tbot@example.test\n" if bot_exists else ""
        (bin_dir / "su").write_text(
            f"""#!/bin/sh
cmd="$3"
echo "su: $cmd" >> {calls}
case "$cmd" in
  *"admin user list"*) printf 'ID\\tUsername\\tEmail\\n1\\toperator\\tops@example.test\\n{rows}' ;;
  *"admin auth list"*) printf 'ID\\tName\\n7\\tauthelia\\n' ;;
  *) exit 0 ;;
esac
"""
        )
        (bin_dir / "curl").write_text(
            f"""#!/bin/sh
echo "curl: $*" >> {calls}
case "$*" in
  *PATCH*) exit 0 ;;
  *) printf '{{"login":"{BOT}","prohibit_login":{str(prohibited).lower()}}}' ;;
esac
"""
        )
        for stub in ("wget", "su", "curl"):
            (bin_dir / stub).chmod(0o755)

    marker = tmp_path / "state"
    marker.write_text("")

    def run():
        env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GITEA_ADMIN_USER": "operator",
            "GITEA_ADMIN_PASSWORD": "pw",
            "GITEA_ADMIN_EMAIL": "ops@example.test",
            "GITEA_OIDC_CLIENT_SECRET": "s",
            "GITEA_OIDC_DISCOVERY_URL": "https://idp.example.test/.well-known/x",
            "GITEA_BOOTSTRAP_STATE": str(marker),
            "GITEA_BOT_USER": BOT,
            "GITEA_BOT_EMAIL": f"{BOT}@example.test",
        }
        return subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)

    return type("H", (), {"build": staticmethod(build), "run": staticmethod(run), "calls": calls})


def test_the_machine_account_is_created_when_absent(bot_harness):
    bot_harness.build(bot_exists=False, prohibited=False)
    result = bot_harness.run()
    assert result.returncode == 0, result.stderr
    assert f"Created machine account '{BOT}'" in result.stdout
    assert "admin user create --username hefesto" in bot_harness.calls.read_text()


def test_an_existing_machine_account_is_not_recreated(bot_harness):
    bot_harness.build(bot_exists=True, prohibited=True)
    result = bot_harness.run()
    assert f"Machine account '{BOT}' exists" in result.stdout
    assert "admin user create" not in bot_harness.calls.read_text()


def test_login_is_prohibited_after_creation(bot_harness):
    """R4's ordering: the account cannot be created blocked, so the block follows."""
    bot_harness.build(bot_exists=False, prohibited=False)
    result = bot_harness.run()
    calls = bot_harness.calls.read_text()
    assert "interactive login prohibited" in result.stdout
    assert "PATCH" in calls
    assert calls.index("admin user create") < calls.index("PATCH"), (
        "the login block must follow creation — prohibit_login is in EditUserOption, "
        "not CreateUserOption (R4)"
    )


def test_an_already_prohibited_account_is_not_patched_again(bot_harness):
    """`prohibit_login` reads back, so this converges by comparison, not by a marker.

    An unconditional PATCH is a no-op write announced as a change on every
    provision — ANSIBLE-054 (#1400) in a new place, in the role that just
    finished removing it.
    """
    bot_harness.build(bot_exists=True, prohibited=True)
    result = bot_harness.run()
    assert "already prohibited" in result.stdout
    assert "Updated machine account" not in result.stdout, (
        "the script announced a change over an account that was already blocked; "
        "`changed_when` matches on 'Updated', so this restarts Gitea every provision"
    )
    assert "PATCH" not in bot_harness.calls.read_text()


def test_the_bot_section_is_skipped_when_no_machine_identity_is_declared(bot_harness):
    """A node provisioned before the identity row exists must not break."""
    bot_harness.build(bot_exists=False, prohibited=False)
    env = dict(os.environ)
    env.pop("GITEA_BOT_USER", None)
    result = subprocess.run(
        ["sh", str(SCRIPT)],
        env={
            **env,
            "PATH": f"{bot_harness.calls.parent / 'bin'}:{os.environ['PATH']}",
            "GITEA_ADMIN_USER": "operator",
            "GITEA_ADMIN_PASSWORD": "pw",
            "GITEA_ADMIN_EMAIL": "ops@example.test",
            "GITEA_OIDC_CLIENT_SECRET": "s",
            "GITEA_OIDC_DISCOVERY_URL": "https://idp.example.test/.well-known/x",
            "GITEA_BOOTSTRAP_STATE": str(bot_harness.calls.parent / "state"),
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "machine account" not in result.stdout.lower()


def test_the_mint_command_is_passed_as_argv() -> None:
    """A string command would be re-parsed, and this one does not survive it.

    Measured on the live node: the string form's inner `su git -c "..."` lost its
    quoting through YAML folding plus argv splitting, so `su` took `gitea` as the
    command and the rest as positional arguments. The task failed — and a partial
    invocation had already minted a token under `generate-access-token`'s DEFAULT
    name and DEFAULT scopes, which are `all`.

    That is the worst available outcome and the reason this is guarded rather
    than merely fixed: an over-scoped credential was created on an account whose
    whole purpose is least privilege, while the play reported failure and the
    operator had no token. A quoting bug that only broke the command would have
    been visible; one that silently widens a scope is not.
    """
    command = _task(MINT_TASK).get("command")
    assert isinstance(command, dict) and "argv" in command, (
        "the mint task passes its command as a string. Use the `argv:` list form so the "
        "nested `su git -c` quoting is passed verbatim instead of being re-parsed."
    )
    joined = " ".join(command["argv"])
    for flag in ("--token-name", "--scopes", "--raw"):
        assert flag in joined, f"the mint command lost {flag}; defaults are name=gitea-admin, scopes=all"
