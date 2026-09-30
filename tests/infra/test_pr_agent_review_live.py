"""Infrastructure: the forge PR reviewer answered a real pull request, on the LIVE forge.

TOOL-080 (#1823) AC1 and AC2 are statements about delivery, and delivery is the one
thing no manifest test reaches. The rendered ConfigMap proves `/review` is the only
command, the signature probes prove a stranger is refused, and a green pod proves the
process started. None of them proves a review arrived. The first smoke test showed it:
on personal/resume PR 279 every one of those was true and no comment ever came. The
pod could not resolve the forge's hostname, and nothing reported that (lesson-472).

So this file asks the forge, not the cluster, about one recorded pull request:

- AC1: exactly one reviewer-authored `PR Reviewer Guide` comment exists. "Exactly
  one", because a second comment is how a broken `persistent_comment` shows up.
- AC2: that comment was updated after the latest push. The push time comes from the
  PR's `pull_push` timeline events, never from the head commit's date, which is
  author-controlled (the same rule tasks.md sets for the AC8 watcher).

It reads with the reviewer's own token. The admin token has no `read:issue`, and the
reviewer's grant (`write:issue,read:repository`) covers both reads, so widening the
admin grant for a test would be the wrong trade.
"""

from __future__ import annotations

import os
from datetime import datetime

import pytest
import yaml

pytestmark = pytest.mark.infra

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_COMMON_YAML = os.path.abspath(os.path.join(_REPO_ROOT, "infra/config/values/common.yaml"))

#: The smoke-test pull request recorded in
#: specs/TOOL-080-forge-pr-reviewer/verification.md ("Live smoke test"). Opened
#: 2026-09-30, reviewed 18 s later, pushed to once, and the same comment was edited
#: 12 s after that push.
REPO = ("personal", "resume")
PR_NUMBER = 280

#: The heading PR-Agent's `/review` writes. A notice about the review (a quota or
#: an error) does not carry it, and a notice is not a review.
REVIEW_MARKER = "PR Reviewer Guide"


def _common() -> dict:
    with open(_COMMON_YAML, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _reviewer_login() -> str:
    """The reviewer account, from the SSOT, so a rename moves the assertion with it."""
    return _common()["apps"]["auth"]["identities"]["reviewer"]


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def review_comments(comments: list[dict], login: str) -> list[dict]:
    """The comments that are a review by `login`, not a notice and not someone else's."""
    return [c for c in comments if (c.get("user") or {}).get("login") == login and REVIEW_MARKER in c.get("body", "")]


def latest_push(timeline: list[dict]) -> datetime | None:
    """When the branch last moved, as the forge recorded it."""
    pushes = [_ts(e["created_at"]) for e in timeline if e.get("type") == "pull_push"]
    return max(pushes) if pushes else None


@pytest.fixture(scope="module")
def pr_activity() -> tuple[list[dict], list[dict]]:
    """The PR's comments and timeline, or a skip if the forge cannot be asked."""
    from toolkit.features.configuration import ConfigurationManager
    from toolkit.features.gitea_client import GiteaClient, GiteaError

    cfg = ConfigurationManager(env="prod")
    token = cfg.get_secret_by_path("apps.services.core.gitea.reviewer_token")
    if not token:
        pytest.skip("no reviewer token in SOPS — cannot ask the forge")

    domain = _common()["apps"]["services"]["core"]["gitea"]["domain"]
    client = GiteaClient(f"https://{domain}", str(token))
    owner, name = REPO
    try:
        comments = list(client._paginate(f"/repos/{owner}/{name}/issues/{PR_NUMBER}/comments"))
        timeline = list(client._paginate(f"/repos/{owner}/{name}/issues/{PR_NUMBER}/timeline"))
    except GiteaError as exc:
        if exc.status_code and exc.status_code >= 500:
            pytest.skip(f"Gitea unreachable ({exc}) — the Beelink is on-demand")
        raise
    except OSError as exc:
        pytest.skip(f"Gitea unreachable ({exc}) — the Beelink is on-demand")
    return comments, timeline


def test_the_reviewer_left_exactly_one_review(pr_activity: tuple[list[dict], list[dict]]) -> None:
    """AC1, and the half of AC2 that says the push edited rather than added."""
    comments, _ = pr_activity
    reviews = review_comments(comments, _reviewer_login())

    assert len(reviews) == 1, (
        f"expected one `{REVIEW_MARKER}` comment by `{_reviewer_login()}` on "
        f"{'/'.join(REPO)}#{PR_NUMBER}, found {len(reviews)}. None means no review was "
        "delivered (check the pod's logs, then its DNS: lesson-472). Two or more means "
        "`persistent_comment` stopped editing in place."
    )


def test_the_review_was_updated_after_the_latest_push(pr_activity: tuple[list[dict], list[dict]]) -> None:
    """AC2: the push reached the reviewer and it answered on the same comment."""
    comments, timeline = pr_activity
    reviews = review_comments(comments, _reviewer_login())
    pushed = latest_push(timeline)

    assert reviews, "no review to compare against the push; see the test above"
    assert pushed is not None, f"{'/'.join(REPO)}#{PR_NUMBER} has no `pull_push` event in its timeline"
    assert _ts(reviews[0]["updated_at"]) > pushed, (
        f"the review was last updated at {reviews[0]['updated_at']}, not after the latest push "
        f"at {pushed.isoformat()}. `pull_request_sync` did not reach the reviewer, or "
        "`GITEA__HANDLE_PUSH_TRIGGER` is off."
    )
