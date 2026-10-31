"""Did Argo CD apply master HEAD in this environment? One JSON line per run (GITOPS-003 AC2).

Reads master HEAD and its `argocd/kubelab-<ARGO_ENV>` commit status from the
GitHub API, anonymously (the repository is public), and prints one
`argo_delivery` line. Vector ships it to Loki; grafana-alerting/delivery-rules.yaml
pages on `healthy` < 1.

- `healthy: 0` when the newest status of the context is `failure`/`error`
  (Argo CD does not retry a failed operation, so age does not matter), or when
  HEAD landed more than GRACE_SECONDS ago and has no `success`.
- `healthy: 1` on `success`, or while HEAD is younger than the grace.
- No `healthy` at all when GitHub cannot be asked. `unwrap` drops the line, so
  the rule reads no data and pages late, but never says the deploy is broken
  because GitHub was the one not answering.

Always exits 0 after its one line: the Job runs with `backoffLimit: 0`, and a
retried pod's second line would replace this one under `last_over_time`.
Stdlib only, so the image is a plain interpreter. Tested by
tests/test_delivery_watcher.py against a fake GitHub.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

API = os.environ.get("GITHUB_API", "https://api.github.com")
REPOSITORY = os.environ["REPOSITORY"]
BRANCH = os.environ.get("BRANCH", "master")
ARGO_ENV = os.environ["ARGO_ENV"]
GRACE_SECONDS = int(os.environ.get("GRACE_SECONDS", "600"))
# Below the Job's `activeDeadlineSeconds` (120). urlopen's timeout bounds the
# connection and each read, not the DNS lookup, so the run bounds itself: a Job
# killed by its deadline would print nothing.
DEADLINE_SECONDS = int(os.environ.get("DEADLINE_SECONDS", "90"))
CONTEXT = f"argocd/kubelab-{ARGO_ENV}"
FAILED = {"failure", "error"}


class Unknown(Exception):
    """GitHub could not be asked; the run has no verdict."""


def _get(path: str) -> object:
    req = urllib.request.Request(
        f"{API}{path}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "kubelab-delivery-watcher"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        raise Unknown(f"GET {path}: HTTP {exc.code}") from exc
    except (OSError, ValueError) as exc:
        raise Unknown(f"GET {path}: {exc}") from exc


def _verdict() -> dict[str, object]:
    head = _get(f"/repos/{REPOSITORY}/commits/{BRANCH}")
    if not isinstance(head, dict):
        raise Unknown("HEAD read is not an object")
    sha = str(head["sha"])
    # The committer date, not the author date: a squash merge keeps the PR's
    # author date, and only the committer date is the moment it reached master.
    landed = datetime.fromisoformat(str(head["commit"]["committer"]["date"]).replace("Z", "+00:00"))
    age = int((datetime.now(timezone.utc) - landed).total_seconds())

    statuses = _get(f"/repos/{REPOSITORY}/commits/{sha}/statuses?per_page=100")
    if not isinstance(statuses, list):
        raise Unknown("statuses read is not a list")
    # GitHub lists statuses newest first, so the first one of the context is current.
    state = next((s.get("state") for s in statuses if s.get("context") == CONTEXT), None)

    if state in FAILED:
        healthy = 0
    elif state == "success":
        healthy = 1
    else:
        healthy = 1 if age < GRACE_SECONDS else 0
    return {"sha": sha, "age_seconds": age, "state": state, "healthy": healthy}


def _out_of_time(*_: object) -> None:
    raise Unknown(f"run passed its {DEADLINE_SECONDS}s deadline")


def main() -> int:
    line: dict[str, object] = {"metric": "argo_delivery", "argo_env": ARGO_ENV}
    signal.signal(signal.SIGALRM, _out_of_time)
    signal.alarm(DEADLINE_SECONDS)
    try:
        line.update(_verdict())
    except (Unknown, KeyError, TypeError) as exc:
        line["reason"] = str(exc) or type(exc).__name__
    finally:
        signal.alarm(0)
    print(json.dumps(line), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
