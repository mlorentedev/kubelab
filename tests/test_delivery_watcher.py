"""The delivery watcher: did Argo CD apply master HEAD (GITOPS-003 AC2, #2645).

`deploy-verify.yml` turns red at once on a `failure` status, but the case of no
status at all needs a clock. GitHub starts this repository's scheduled runs
3 to 6 hours apart, so the in-cluster watcher is that clock. These tests run the
real `watch.py` under the interpreter, against a fake GitHub on localhost, and
read what it prints, which is exactly what Vector ships to Loki.

Two properties matter more than any single verdict:

- **Unknown is never a verdict.** When GitHub cannot be asked, the line carries
  no `healthy`, so `unwrap` drops it and the rule reads no data. It must not say
  the deploy is broken because GitHub was the one not answering.
- **One run, one line.** The rule keeps `last_over_time`, so a second line from
  the same run would decide instead of the first.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
WATCH = REPO / "infra/k8s/base/services/delivery-watcher/watch.py"
SHA = "9706719f02e3bf1baec7996819566fe7795c96a3"
GRACE = 600


class FakeGitHub:
    """Answers the two reads the watcher makes. `head_status` overrides the HEAD read."""

    def __init__(self) -> None:
        self.age = timedelta(minutes=30)
        self.statuses: list[dict[str, str]] = []
        self.head_status = 200
        self.statuses_status = 200
        self.delay = 0.0
        self.requests: list[str] = []

    def head(self) -> dict[str, object]:
        landed = datetime.now(timezone.utc) - self.age
        # The author date is deliberately older: a squash merge keeps the PR's
        # first commit as author date, and only the committer date is the merge.
        authored = landed - timedelta(days=3)
        return {
            "sha": SHA,
            "commit": {
                "author": {"date": authored.strftime("%Y-%m-%dT%H:%M:%SZ")},
                "committer": {"date": landed.strftime("%Y-%m-%dT%H:%M:%SZ")},
            },
        }


@pytest.fixture
def github() -> Iterator[tuple[FakeGitHub, str]]:
    fake = FakeGitHub()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server's naming
            fake.requests.append(self.path)
            time.sleep(fake.delay)
            if self.path == "/repos/mlorentedev/kubelab/commits/master":
                code, body = fake.head_status, fake.head()
            elif self.path == f"/repos/mlorentedev/kubelab/commits/{SHA}/status":
                # The combined status: GitHub keeps the newest status of each
                # context, in one response however many statuses were posted.
                latest: dict[str, dict[str, str]] = {}
                for s in fake.statuses:
                    latest.setdefault(s["context"], s)
                code, body = fake.statuses_status, {"sha": SHA, "statuses": list(latest.values())}
            else:
                code, body = 404, {"message": "Not Found"}
            payload = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield fake, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


def _run(api: str, env: str = "prod", deadline: int = 60) -> tuple[int, list[dict[str, object]]]:
    proc = subprocess.run(
        [sys.executable, "-I", str(WATCH)],
        env={
            "PATH": os.environ.get("PATH", ""),
            "GITHUB_API": api,
            "REPOSITORY": "mlorentedev/kubelab",
            "BRANCH": "master",
            "ARGO_ENV": env,
            "GRACE_SECONDS": str(GRACE),
            "DEADLINE_SECONDS": str(deadline),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    lines = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    return proc.returncode, lines


def _status(env: str, state: str) -> dict[str, str]:
    return {"context": f"argocd/kubelab-{env}", "state": state, "description": f"{state} at {SHA[:7]}"}


def _only_line(api: str, env: str = "prod", deadline: int = 60) -> dict[str, object]:
    code, lines = _run(api, env, deadline)
    assert code == 0, "the watcher owns its exits: every verdict, unknown included, exits 0"
    assert len(lines) == 1, f"one run must print exactly one line, got {lines}"
    line = lines[0]
    assert line["metric"] == "argo_delivery"
    assert line["argo_env"] == env
    return line


def test_success_on_head_is_healthy(github: tuple[FakeGitHub, str]) -> None:
    fake, api = github
    fake.statuses = [_status("prod", "success")]
    line = _only_line(api)
    assert line["healthy"] == 1
    assert line["sha"] == SHA
    assert line["state"] == "success"


@pytest.mark.parametrize("state", ["failure", "error"])
def test_a_failed_sync_is_unhealthy_however_young(github: tuple[FakeGitHub, str], state: str) -> None:
    """Argo does not retry a failed operation, so waiting out the grace adds nothing."""
    fake, api = github
    fake.age = timedelta(seconds=30)
    fake.statuses = [_status("prod", state)]
    line = _only_line(api)
    assert line["healthy"] == 0
    assert line["state"] == state


def test_no_status_inside_the_grace_is_healthy(github: tuple[FakeGitHub, str]) -> None:
    """A fresh merge has not synced yet. Calling it unhealthy would page on every merge."""
    fake, api = github
    fake.age = timedelta(seconds=GRACE - 120)
    line = _only_line(api)
    assert line["healthy"] == 1
    assert line["state"] is None


def test_no_status_past_the_grace_is_unhealthy(github: tuple[FakeGitHub, str]) -> None:
    fake, api = github
    fake.age = timedelta(seconds=GRACE + 120)
    line = _only_line(api)
    assert line["healthy"] == 0
    assert line["state"] is None
    assert line["age_seconds"] >= GRACE


def test_age_is_measured_from_the_merge_not_the_authoring(github: tuple[FakeGitHub, str]) -> None:
    """Squash merges keep the PR's author date, days old. Read from it, every merge is late."""
    fake, api = github
    fake.age = timedelta(minutes=2)
    line = _only_line(api)
    assert line["age_seconds"] < GRACE
    assert line["healthy"] == 1


def test_only_this_environment_counts(github: tuple[FakeGitHub, str]) -> None:
    """Staging's success says nothing about prod, and the other way round."""
    fake, api = github
    fake.statuses = [_status("staging", "success")]
    assert _only_line(api, "prod")["healthy"] == 0
    assert _only_line(api, "staging")["healthy"] == 1


def test_the_newest_status_of_the_context_wins(github: tuple[FakeGitHub, str]) -> None:
    """A later success clears an earlier failure, and the other way round."""
    fake, api = github
    fake.statuses = [_status("prod", "success"), _status("prod", "failure")]
    assert _only_line(api)["healthy"] == 1
    fake.statuses = [_status("prod", "failure"), _status("prod", "success")]
    assert _only_line(api)["healthy"] == 0


@pytest.mark.parametrize("which", ["head_status", "statuses_status"])
@pytest.mark.parametrize("code", [403, 500])
def test_github_not_answering_is_unknown_not_unhealthy(github: tuple[FakeGitHub, str], which: str, code: int) -> None:
    """403 is the anonymous rate limit (60/h per egress IP, shared with the whole NAT)."""
    fake, api = github
    fake.age = timedelta(hours=2)
    setattr(fake, which, code)
    line = _only_line(api)
    assert "healthy" not in line
    assert str(code) in str(line["reason"])


def test_github_unreachable_is_unknown_not_unhealthy() -> None:
    line = _only_line("http://127.0.0.1:9")
    assert "healthy" not in line
    assert line["reason"]


def test_it_reads_github_and_nothing_else(github: tuple[FakeGitHub, str]) -> None:
    """Two anonymous reads per run: 12 an hour against the 60 allowed."""
    fake, api = github
    fake.statuses = [_status("prod", "success")]
    _only_line(api)
    assert len(fake.requests) == 2


def test_a_run_past_its_deadline_still_prints_its_line(github: tuple[FakeGitHub, str]) -> None:
    """urlopen's timeout does not bound a DNS lookup. Killed by the Job's deadline, the
    run would print nothing; the watcher stops itself first and says why."""
    fake, api = github
    fake.delay = 10
    line = _only_line(api, deadline=2)
    assert "healthy" not in line
    assert "deadline" in str(line["reason"])


def test_other_contexts_cannot_crowd_out_argo(github: tuple[FakeGitHub, str]) -> None:
    """The list endpoint pages at 100: enough newer statuses would push Argo's off page one."""
    fake, api = github
    fake.statuses = [_status(f"other-{i}", "success") for i in range(150)] + [_status("prod", "success")]
    for s in fake.statuses[:150]:
        s["context"] = s["context"].replace("argocd/kubelab-", "ci/")
    assert _only_line(api)["healthy"] == 1
