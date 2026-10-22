"""Infrastructure: the token Argo CD posts commit statuses with still works (GITOPS-003 AC6, #1478).

Argo CD's `service.webhook.github` posts `argocd/kubelab-<env>` with a
fine-grained PAT (`argocd.github_status_token`, common SOPS). When that PAT
expires, Argo's webhook calls fail inside the notifications controller and no
status is posted. Every `deploy-verify` run then reads "no status arrived",
which says nothing about why. This file asks GitHub directly, with the same
token, for the one thing Argo needs it for: the commit statuses of kubelab.

A 401 is a failure here, never a skip: it is the expired or revoked token this
check exists to catch. Only an unreachable GitHub skips, because a check that
could not run must not read as a pass.

The token is read in process and sent as a header. It never reaches argv, a
log line or an assertion message.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.infra

KEY = "argocd.github_status_token"
REPO = "mlorentedev/kubelab"


@pytest.fixture(scope="module")
def token() -> str:
    from toolkit.features.configuration import ConfigurationManager

    value = ConfigurationManager(env="prod").get_secret_by_path(KEY)
    if not value:
        pytest.skip(f"{KEY} is not in SOPS here (no age key?) — cannot ask GitHub")
    return str(value)


def _get(path: str, token: str) -> tuple[int, dict, object]:
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, dict(resp.headers), json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), None
    except OSError as exc:
        pytest.skip(f"GitHub unreachable ({exc}) — cannot check the token")


def test_the_token_reads_kubelab_commit_statuses(token: str) -> None:
    """The permission Argo uses, exercised read-only: a 401 means it can post nothing."""
    status, _, body = _get(f"/repos/{REPO}/commits/master/statuses?per_page=1", token)
    assert status != 401, (
        f"GitHub rejected {KEY} (HTTP 401): expired or revoked. Argo CD posts no commit status "
        "until it is rotated: mint a new one per its SECRET_CATALOG entry, then `make deploy-argocd`."
    )
    assert status == 200, f"GET commit statuses of {REPO} with {KEY} answered HTTP {status}, not 200"
    assert isinstance(body, list)


def test_the_token_has_not_expired(token: str) -> None:
    """The expiry GitHub states for the token, read by the same function `secrets check-expiry` uses."""
    from toolkit.features.secret_expiry import CredentialRejectedError, ExpiryUnavailableError, github_pat_expiry

    try:
        expires = github_pat_expiry(token)
    except CredentialRejectedError as exc:
        pytest.fail(f"{KEY}: {exc}")
    except ExpiryUnavailableError as exc:
        pytest.skip(f"cannot ask GitHub for {KEY}'s expiry: {exc}")
    if expires is None:
        pytest.skip(f"{KEY} carries no expiry: nothing to compare")
    assert expires > datetime.now(timezone.utc), f"{KEY} expired at {expires.isoformat()}"
