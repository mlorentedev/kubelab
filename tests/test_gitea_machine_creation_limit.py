"""AUTH-024 AC1 (#3148): a machine account cannot create or fork a repository of its own.

ADR-065 D1 says the bot, the reviewer and the agent own nothing, and #3163 makes
the reconcile fail when one does. That detects; this prevents. Gitea checks a
repository's OWNER against `max_repo_creation`, so 0 on the account blocks a
repository or a fork under its own name and leaves org repositories alone.

Gitea's API cannot read the value back: `max_repo_creation` is in EditUserOption
and absent from `api.User`. So convergence is asserted from what the bootstrap
last wrote, a marker per account, the pattern the OIDC block already uses. The
accounts already exist in prod, so "at creation" alone would never reach them.

The real script runs with `su`, `wget` and `curl` stubbed on PATH, so these
assert its behaviour, not its text.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "infra/ansible/roles/beelink_services/files/gitea-bootstrap.sh"
MACHINES = {"GITEA_BOT_USER": "hefesto", "GITEA_REVIEWER_USER": "mentor", "GITEA_AGENT_USER": "dedalo"}


@pytest.fixture
def harness(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "curl.log"
    users = "\\n".join(f"{i}\\t{u}\\tx@example.test" for i, u in enumerate(["operator", *MACHINES.values()], 1))
    stubs = {
        "wget": "#!/bin/sh\nexit 0\n",
        "su": f"""#!/bin/sh
case "$3" in
  *"admin user list"*) printf 'ID\\tUsername\\tEmail\\n{users}\\n' ;;
  *"admin auth list"*) printf 'ID\\tName\\tType\\tEnabled\\n7\\tauthelia\\tOAuth2\\ttrue\\n' ;;
esac
exit 0
""",
        # Records method, URL and body; a GET answers with the login already allowed,
        # so the only write left in a run is the one under test.
        "curl": f"""#!/bin/sh
cat > /dev/null
method=GET; body=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -X) method="$2"; shift ;;
    -d) body="$2"; shift ;;
    -H|-K) shift ;;
    http*) url="$1" ;;
  esac
  shift
done
printf '%s %s %s\\n' "$method" "$url" "$body" >> {calls}
[ -n "${{STUB_PATCH_FAILS:-}}" ] && [ "$method" = PATCH ] && exit 22
[ "$method" = GET ] && printf '{{"id":%s,"prohibit_login":false}}' "${{STUB_USER_ID-7}}"
exit 0
""",
    }
    for name, text in stubs.items():
        (bin_dir / name).write_text(text, encoding="utf-8", newline="\n")
        (bin_dir / name).chmod(0o755)
    state = tmp_path / "state"
    state.mkdir()

    def run(**extra: str) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GITEA_ADMIN_USER": "operator",
            "GITEA_ADMIN_PASSWORD": "pw",
            "GITEA_ADMIN_EMAIL": "ops@example.test",
            "GITEA_OIDC_CLIENT_SECRET": "s",
            "GITEA_OIDC_DISCOVERY_URL": "https://auth.example.test/.well-known/openid-configuration",
            "GITEA_BOOTSTRAP_STATE": str(state / ".kubelab-oidc-bootstrap.sha256"),
            "GITEA_CREATION_LIMIT_STATE_DIR": str(state),
            **{key: login for key, login in MACHINES.items()},
            **{key.replace("_USER", "_EMAIL"): f"{login}@example.test" for key, login in MACHINES.items()},
            **extra,
        }
        return subprocess.run(
            ["sh", str(SCRIPT)], env=env, capture_output=True, text=True, encoding="utf-8", timeout=60
        )

    def limit_writes() -> list[tuple[str, dict]]:
        out = []
        for line in calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []:
            method, url, *body = line.split(" ", 2)
            payload = json.loads(body[0]) if body and body[0] else {}
            if method == "PATCH" and "max_repo_creation" in payload:
                out.append((url.rsplit("/", 1)[-1], payload))
        return out

    return type("H", (), {"run": staticmethod(run), "writes": staticmethod(limit_writes), "state": state})


def test_every_machine_account_gets_a_creation_limit_of_zero(harness) -> None:
    result = harness.run()

    assert result.returncode == 0, result.stderr
    written = dict(harness.writes())
    assert set(written) == set(MACHINES.values()), written
    for login, payload in written.items():
        assert payload["max_repo_creation"] == 0, login
        # EditUserOption requires both; without them Gitea answers 422.
        assert payload["login_name"] == login and payload["source_id"] == 0


def test_the_first_application_is_reported_as_a_change(harness) -> None:
    result = harness.run()

    for login in MACHINES.values():
        assert f"Updated repository creation limit ({login})" in result.stdout, result.stdout


def test_a_recorded_limit_is_neither_written_nor_reported_again(harness) -> None:
    """Without this the role restarts Gitea on every provision (ANSIBLE-054)."""
    harness.run()
    first = len(harness.writes())

    result = harness.run()

    assert len(harness.writes()) == first, "the limit was written again on a converged run"
    assert "Updated repository creation limit" not in result.stdout


def test_a_failed_write_records_nothing(harness) -> None:
    """Recording before the write returns would report converged over a value
    Gitea never received, a false green that outlives the run."""
    result = harness.run(STUB_PATCH_FAILS="1")

    assert result.returncode != 0
    assert not list(harness.state.glob(".kubelab-creation-limit-*"))


def test_an_account_created_again_under_the_same_login_gets_the_limit_again(harness) -> None:
    """A recreated account starts unlimited; a marker keyed by login alone would hide that."""
    harness.run()
    first = len(harness.writes())

    result = harness.run(STUB_USER_ID="8")

    assert len(harness.writes()) == first + len(MACHINES), "a new account id did not get the limit"
    assert "Updated repository creation limit" in result.stdout


def test_an_unreadable_account_is_limited_and_not_recorded(harness) -> None:
    """With no id there is nothing to key a marker on, so the write repeats instead of converging falsely."""
    result = harness.run(STUB_USER_ID="")

    assert result.returncode == 0, result.stderr
    assert len(harness.writes()) == len(MACHINES)
    assert not list(harness.state.glob(".kubelab-creation-limit-*"))
