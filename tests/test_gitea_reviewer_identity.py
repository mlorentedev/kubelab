"""TOOL-080 AC5/AC6 -- the PR reviewer is a machine identity of its own, provisioned like the bot.

`mentor` posts PR-Agent's reviews. It is a second machine account rather than a
second token on `hefesto` (Manu, 2026-09-24):
- `hefesto` writes to every `personal/` repository, and read access is what contains
  the reviewer (measured, `specs/TOOL-080-forge-pr-reviewer/verification.md`);
- the reviewer's token lives in an internet-facing pod that reads untrusted diffs, so
  it must not share the reconciler's blast radius or its rotation;
- separate authorship lets a triage tell a review from reconciler output.

So everything the bot has, the reviewer mirrors: a row in the identity map, an
account created by `gitea-bootstrap.sh` with the login flag off (ADR-062 D1 as
amended 2026-09-24), a token minted once by Ansible and recorded over stdin, a
catalog entry, and a rotation entry. What differs is the grant: `write:issue` +
`read:repository`, and a read team instead of `reconcilers`.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
from typing import Any

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
COMMON = REPO / "infra/config/values/common.yaml"
ROLE = REPO / "infra/ansible/roles/beelink_services"
PLAYBOOK = REPO / "infra/ansible/playbooks/provision-bee.yml"
SCRIPT = ROLE / "files/gitea-bootstrap.sh"

REVIEWER_TOKEN_KEY = "apps.services.core.gitea.reviewer_token"
MINT_TASK = "Mint the reviewer account's scoped token"
RECORD_TASK = "Record the reviewer token in SOPS"


def _identities() -> dict[str, str]:
    return yaml.safe_load(COMMON.read_text())["apps"]["auth"]["identities"]


def _task(name: str) -> dict[str, Any]:
    for task in yaml.safe_load((ROLE / "tasks/main.yml").read_text()):
        if isinstance(task, dict) and task.get("name") == name:
            return task
    raise AssertionError(f"no task named {name!r} in beelink_services/tasks/main.yml")


# --------------------------------------------------------------------------- declaration


def test_the_reviewer_is_its_own_row_in_the_identity_map() -> None:
    identities = _identities()
    assert identities.get("reviewer"), "apps.auth.identities.reviewer is missing or empty"
    others = {identities[k] for k in ("superadmin", "operator", "machine")}
    assert identities["reviewer"] not in others, (
        "the reviewer shares an account with another identity. It must not be `machine`: that account "
        "holds write on every personal/ repository, and read access is what contains the reviewer."
    )


def test_the_playbook_resolves_the_reviewer_through_the_map() -> None:
    playbook = PLAYBOOK.read_text()
    reviewer = _identities()["reviewer"]
    live = [line for line in playbook.splitlines() if reviewer in line and not line.strip().startswith("#")]
    assert not live, f"the reviewer account name appears literally in provision-bee.yml: {live}"
    assert "apps.auth.identities.reviewer" in playbook
    assert "token_scopes.reviewer" in playbook, "the reviewer's grant must come from common.yaml, not a literal"


def test_the_reviewer_token_is_catalogued_like_the_bot_token() -> None:
    from toolkit.features.secrets_manager import SECRET_CATALOG, Expiry, SecretKind

    spec = next((s for s in SECRET_CATALOG if s.key_path == REVIEWER_TOKEN_KEY), None)
    assert spec is not None, f"{REVIEWER_TOKEN_KEY} is not in SECRET_CATALOG, so no audit can report it absent"
    assert spec.kind is SecretKind.EXTERNAL, "Gitea mints it; a locally generated string would authenticate nothing"
    assert spec.expiry is Expiry.NEVER, "Gitea tokens carry no expiry field; see the bot_token entry"
    assert "prod" in spec.envs


# --------------------------------------------------------------------------- the mint


def test_the_reviewer_token_is_minted_once_with_its_declared_grant() -> None:
    task = _task(MINT_TASK)
    assert task.get("no_log") is True
    assert "reviewer_token" in str(task.get("when") or ""), "an ungated mint issues a new live token every run"
    command = " ".join(task["command"]["argv"])
    assert "--username {{ gitea_reviewer_user }}" in command
    assert "--token-name kubelab-reviewer" in command
    assert "--scopes {{ gitea_reviewer_scopes }}" in command


def test_the_reviewer_token_is_recorded_over_stdin() -> None:
    task = _task(RECORD_TASK)
    assert task.get("no_log") is True
    assert f"toolkit secrets set {REVIEWER_TOKEN_KEY}" in task["command"]
    assert "--stdin" in task["command"]
    assert "reviewer_token" in str(task.get("when") or "")


def test_the_container_receives_the_reviewer_name_for_the_bootstrap_script() -> None:
    compose = (ROLE / "templates/compose.yml.j2").read_text()
    assert 'GITEA_REVIEWER_USER: "{{ gitea_reviewer_user }}"' in compose
    assert 'GITEA_REVIEWER_EMAIL: "{{ gitea_reviewer_email }}"' in compose


# --------------------------------------------------------------------------- the account


@pytest.fixture
def harness(tmp_path: pathlib.Path) -> Any:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"

    def build(*, existing: tuple[str, ...], prohibited: bool) -> None:
        rows = "".join(f"{i}\\t{name}\\t{name}@example.test\\n" for i, name in enumerate(existing, start=2))
        (bin_dir / "wget").write_text("#!/bin/sh\nexit 0\n")
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
  *) printf '{{"prohibit_login":{str(prohibited).lower()}}}' ;;
esac
"""
        )
        for stub in ("wget", "su", "curl"):
            (bin_dir / stub).chmod(0o755)

    marker = tmp_path / "state"
    marker.write_text("")

    def run(**extra: str) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GITEA_ADMIN_USER": "operator",
            "GITEA_ADMIN_PASSWORD": "pw",
            "GITEA_ADMIN_EMAIL": "ops@example.test",
            "GITEA_OIDC_CLIENT_SECRET": "s",
            "GITEA_OIDC_DISCOVERY_URL": "https://idp.example.test/.well-known/x",
            "GITEA_BOOTSTRAP_STATE": str(marker),
            **extra,
        }
        return subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)

    return type("H", (), {"build": staticmethod(build), "run": staticmethod(run), "calls": calls})


REVIEWER_ENV = {"GITEA_REVIEWER_USER": "mentor", "GITEA_REVIEWER_EMAIL": "mentor@example.test"}


def test_the_reviewer_account_is_created_when_absent(harness: Any) -> None:
    harness.build(existing=(), prohibited=False)
    result = harness.run(**REVIEWER_ENV)
    assert result.returncode == 0, result.stderr
    assert "Created machine account 'mentor'" in result.stdout
    assert "admin user create --username mentor" in harness.calls.read_text()


def test_the_reviewer_account_keeps_a_working_token(harness: Any) -> None:
    """The login flag stays off: `prohibit_login` kills API tokens (lesson-400, re-measured 2026-09-24)."""
    harness.build(existing=("mentor",), prohibited=True)
    result = harness.run(**REVIEWER_ENV)
    calls = harness.calls.read_text()
    assert "Updated machine account login state" in result.stdout
    assert "admin/users/mentor" in calls and "PATCH" in calls


def test_the_bot_and_the_reviewer_are_both_provisioned_in_one_run(harness: Any) -> None:
    harness.build(existing=(), prohibited=False)
    result = harness.run(GITEA_BOT_USER="hefesto", GITEA_BOT_EMAIL="hefesto@example.test", **REVIEWER_ENV)
    assert "Created machine account 'hefesto'" in result.stdout
    assert "Created machine account 'mentor'" in result.stdout


def test_no_reviewer_is_provisioned_when_none_is_declared(harness: Any) -> None:
    harness.build(existing=(), prohibited=False)
    result = harness.run(GITEA_BOT_USER="hefesto", GITEA_BOT_EMAIL="hefesto@example.test")
    assert result.returncode == 0, result.stderr
    assert "mentor" not in harness.calls.read_text()


def test_the_admin_password_never_reaches_curl_argv(harness: Any) -> None:
    """Review of #1832: `-u user:password` puts the admin password in /proc/<pid>/cmdline.

    The credential is handed to curl as a config on stdin (`-K -`) instead, so the
    only argv it appears in is none. The stub records argv, which is what `ps` shows.
    """
    harness.build(existing=("mentor",), prohibited=True)
    harness.run(GITEA_BOT_USER="hefesto", GITEA_BOT_EMAIL="hefesto@example.test", **REVIEWER_ENV)
    calls = harness.calls.read_text()
    assert "PATCH" in calls, "the fixture must drive the PATCH path too"
    assert "operator:pw" not in calls
