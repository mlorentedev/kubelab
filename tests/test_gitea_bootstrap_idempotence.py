"""ANSIBLE-054 (#1400) — the bootstrap must report a change only when it made one.

`gitea-bootstrap.sh` calls `gitea admin auth update-oauth` unconditionally
whenever the Authelia auth source already exists, then logs `Updated OIDC
provider`. The Ansible task's guard is

    changed_when: "'Created' in ... or 'Updated' in ..."
    notify: Restart gitea

so an action that is idempotent in **effect** reports non-idempotently, and the
handler restarts the forge on every provision of the node. Measured before this
change, two consecutive runs:

    beelink : ok=131  changed=11  failed=0
    beelink : ok=129  changed=2   failed=0     <- nothing had changed

Gitea is a singleton on an on-demand node, so a provision during work bounces
the forge under whoever is using it; and while it stands, no change to
`beelink_services` can demonstrate `changed=0` — the repo's standing bar for an
IaC change — so the signal is unavailable to every future PR touching the role.

**The fix is the report, never the restart.** Dropping the `notify` is the defect
#1352 repaired and lesson-381 records: `update-oauth` writes SQLite while the
running web process keeps the auth source it parsed at startup, so a provision
without the restart leaves Gitea serving the OLD client secret — which is how
prod SSO stayed broken through a green run on 2026-08-23.

So the write stays unconditional (it still repairs out-of-band drift in the
fields Gitea will accept) and only the *log line* becomes conditional, keyed on a
marker file recording the hash of the configuration last written.

These tests run the real script with `su` and `wget` stubbed on PATH, so they
assert its behaviour rather than its text. A grep-based version would pass on the
docstring above — the false green this repository keeps meeting (lesson-021's
addendum, and `test_the_setting_is_a_value_and_not_only_a_comment`).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/beelink_services"
SCRIPT = ROLE / "files/gitea-bootstrap.sh"

ADMIN = "operator"
SECRET = "s3cr3t-client-secret"
DISCOVERY = "https://auth.kubelab.live/.well-known/openid-configuration"

#: What the script writes into the marker. Kept in the test as an independent
#: restatement rather than imported from the script, so a change to the recipe
#: has to be made deliberately in two places instead of silently agreeing with
#: itself.
FIELDS = ("authelia", "openidConnect", "gitea", SECRET, DISCOVERY, "openid,profile,email,groups")


def _expected_hash(secret: str = SECRET, discovery: str = DISCOVERY) -> str:
    """Length-prefixed, not merely separated — see the script's own comment.

    A bare delimiter is ambiguous for any field that can contain it, and two
    different configurations hashing alike would mean a rotated secret reporting
    no change: the lying report this whole ticket removes, reintroduced through
    the encoding. Raised in review of #1421.
    """
    fields = ("authelia", "openidConnect", "gitea", secret, discovery, "openid,profile,email,groups")
    encoded = "".join(f"{len(f)}:{f}|" for f in fields)
    return hashlib.sha256(encoded.encode()).hexdigest()


@pytest.fixture
def harness(tmp_path: Path):
    """A PATH where `su` and `wget` are stubs, and the marker lives under tmp_path."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"

    (bin_dir / "wget").write_text("#!/bin/sh\nexit 0\n")

    # `su git -c "<command>"`. Dispatch on the command text, record every call,
    # and answer as a Gitea with the admin user and the Authelia source already
    # present -- the converged state, which is the one that must report nothing.
    (bin_dir / "su").write_text(
        f"""#!/bin/sh
cmd="$3"
echo "$cmd" >> {calls}
case "$cmd" in
  *"admin user list"*)  printf 'ID\\tUsername\\tEmail\\n1\\t{ADMIN}\\tops@example.test\\n' ;;
  *"admin auth list"*)  printf 'ID\\tName\\tType\\tEnabled\\n7\\tauthelia\\tOAuth2\\ttrue\\n' ;;
  *"update-oauth"*)     [ -n "${{STUB_UPDATE_FAILS:-}}" ] && exit 1 ; exit 0 ;;
  *"add-oauth"*)        exit 0 ;;
  *)                    exit 0 ;;
esac
"""
    )
    for stub in ("wget", "su"):
        (bin_dir / stub).chmod(0o755)

    marker = tmp_path / "state" / ".kubelab-oidc-bootstrap.sha256"
    marker.parent.mkdir()

    def run(secret: str = SECRET, discovery: str = DISCOVERY, **extra: str):
        env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GITEA_ADMIN_USER": ADMIN,
            "GITEA_ADMIN_PASSWORD": "pw",
            "GITEA_ADMIN_EMAIL": "ops@example.test",
            "GITEA_OIDC_CLIENT_SECRET": secret,
            "GITEA_OIDC_DISCOVERY_URL": discovery,
            "GITEA_BOOTSTRAP_STATE": str(marker),
            **extra,
        }
        return subprocess.run(
            ["sh", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60
        )

    return type(
        "Harness",
        (),
        {"run": staticmethod(run), "marker": marker, "calls": calls, "tmp": tmp_path},
    )


def test_the_stubs_actually_drive_the_script(harness):
    """Without this, a script that died on line 1 would make every check below pass."""
    result = harness.run()
    assert result.returncode == 0, f"script failed: {result.stderr}"
    assert "admin auth list" in harness.calls.read_text(), (
        "the `su` stub was never reached, so the assertions below are asserting on nothing"
    )


def test_a_converged_run_reports_no_change(harness):
    """The defect. Same config as last time must produce neither Created nor Updated.

    `changed_when` reads exactly those two words out of stdout, so this is the
    difference between a provision that restarts the forge and one that does not.
    """
    harness.marker.write_text(_expected_hash() + "\n")

    result = harness.run()

    assert result.returncode == 0, result.stderr
    assert "Updated" not in result.stdout and "Created" not in result.stdout, (
        "the bootstrap announced a change on a converged run:\n"
        f"{result.stdout}\n"
        "`changed_when` matches on 'Created'/'Updated', so this restarts Gitea on "
        "every provision of the node."
    )


def test_the_write_still_happens_on_a_converged_run(harness):
    """Silence in the log must not become silence in the database.

    The tempting fix is to skip `update-oauth` when the marker matches. That
    trades one honest report for a lost repair: the marker cannot see drift
    applied to Gitea directly, and the write is what reconciles the fields Gitea
    will accept. Only the report is conditional.
    """
    harness.marker.write_text(_expected_hash() + "\n")

    harness.run()

    assert "update-oauth" in harness.calls.read_text(), (
        "update-oauth was skipped on a converged run — out-of-band drift in the "
        "auth source would now persist until someone deleted the marker by hand"
    )


def test_a_first_run_reports_a_change_and_records_the_state(harness):
    """No marker means nothing is known, so the honest answer is `changed`."""
    assert not harness.marker.exists()

    result = harness.run()

    assert "Updated" in result.stdout, (
        f"a run with no recorded state must report a change; got:\n{result.stdout}"
    )
    assert harness.marker.read_text().strip() == _expected_hash()


def test_a_rotated_secret_still_reports_a_change(harness):
    """AC2's property, and the one a tightened guard would silently break.

    A guard that never fires is not idempotence, it is a broken deploy that
    reports success — the same class as the missing `notify` in #1352. The
    marker holds the OLD secret; the new one must be seen and announced, so the
    handler fires and the running process picks it up.
    """
    harness.marker.write_text(_expected_hash(secret="the-previous-secret") + "\n")

    result = harness.run()

    assert "Updated" in result.stdout, (
        f"a rotated client secret reported no change; got:\n{result.stdout}\n"
        "Gitea would keep serving the old secret with the provision reporting success."
    )
    assert harness.marker.read_text().strip() == _expected_hash()


def test_a_changed_discovery_url_also_reports_a_change(harness):
    """The marker covers the whole configuration, not the secret alone."""
    harness.marker.write_text(_expected_hash(discovery="https://old.example.test/.well-known/x") + "\n")

    assert "Updated" in harness.run().stdout


def test_a_failed_write_does_not_record_success(harness):
    """The marker is written after the write, never before.

    Recording first would make the next run report `changed=0` over a
    configuration that was never applied — a false green that survives every
    subsequent provision, which is strictly worse than the noise this ticket
    removes.
    """
    harness.marker.write_text(_expected_hash(secret="the-previous-secret") + "\n")
    stale = harness.marker.read_text()

    result = harness.run(STUB_UPDATE_FAILS="1")

    assert result.returncode != 0, "a failing update-oauth must fail the task"
    assert harness.marker.read_text() == stale, (
        "the marker was updated despite the write failing; the next run would "
        "report converged over configuration Gitea never received"
    )


def _task(name: str) -> dict:
    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    for task in tasks:
        if task.get("name") == name:
            return task
    raise AssertionError(f"no task named {name!r} in beelink_services/tasks/main.yml")


def test_replacing_the_script_restarts_the_container_that_mounts_it():
    """A new script on the host is not a new script in the container.

    `compose.yml.j2` mounts the file itself, not its directory:

        {{ beelink_deploy_dir }}/gitea-bootstrap.sh:/scripts/bootstrap.sh:ro

    A single-file bind mount pins the **inode**. Ansible's `copy` replaces the
    file through a tempfile and a rename, so the host gets a new inode while the
    running container keeps the old one, and mounts are re-resolved only when the
    container starts. The container therefore keeps executing the previous script
    until something restarts it.

    Measured while landing this ticket, three consecutive provisions:

        run 1  finished 01:51:36Z   bootstrap reported changed
        marker written 01:53:16Z    <- during run 2, not run 1
        run 2  finished 01:53:41Z   bootstrap reported changed
        run 3  changed=0

    Run 1 installed the new script and then ran the **old** one; run 1's
    `Restart gitea` handler re-resolved the mount; run 2 was the first to execute
    the new script. Neither run was dishonest — each really did write state for
    the first time — but the transition cost one provision per restart, and
    nothing bounded how many that would be.

    Until this ticket, the old script's unconditional `Updated` refreshed the
    mount on every provision by accident. Removing that accident is what makes
    this notify load-bearing: without it, the next edit to the script would run
    stale indefinitely, and the report would say the deploy succeeded.
    """
    task = _task("Install Gitea bootstrap script")
    notify = task.get("notify")
    notify = [notify] if isinstance(notify, str) else (notify or [])

    assert "Restart gitea" in notify, (
        "the task that replaces gitea-bootstrap.sh does not notify `Restart gitea`. "
        "The script is bind-mounted as a single file, so the running container keeps "
        "executing the previous version until it restarts — a script change would "
        "report success and take no effect."
    )


def test_the_state_encoding_cannot_confuse_two_configurations(harness):
    """Two configurations that a bare separator would flatten must differ.

    With `"|".join(...)`, a secret ending in `|` and a discovery URL are
    indistinguishable from a secret and a discovery URL beginning with `|` —
    the marker matches, the script stays silent, and the rotation is lost. The
    length prefix makes that unrepresentable, so this asserts on the property
    rather than on the current alphabet of the secret generator.
    """
    a = harness.run(secret="rotated|", discovery="https://idp.example.test/x")
    assert "Updated" in a.stdout
    first = harness.marker.read_text().strip()

    b = harness.run(secret="rotated", discovery="|https://idp.example.test/x")
    assert "Updated" in b.stdout, (
        "the second configuration was read as identical to the first, so a real "
        "change would have been announced as none"
    )
    assert harness.marker.read_text().strip() != first
