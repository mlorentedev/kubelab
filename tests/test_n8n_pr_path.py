"""The forge pull-request path in multi-forge-sync (APP-CONFIG-016, #1871).

No pull request had ever reached its Vikunja task. `Extract Matched Task ID`
read `$json` as the search result, and n8n hands it one item per task. Past it,
three nodes read the event from the previous response, and the write would have
erased the task it updated. Each test here runs the workflow's own JavaScript
on the items n8n really produces (`tests/n8n_code_node.py`).

What the path writes is decided by the operator's forward-only rule
(2026-09-27, ADR-066 D4):

- an opened or reopened PR adds one comment;
- a merged PR marks the task done and adds a comment;
- every other event writes nothing, so no event ever un-does a task.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
from typing import Any

import pytest

from tests.n8n_code_node import (
    EMPTY_ITEM,
    ERROR_ITEM,
    WORKFLOW_DIR,
    node_js,
    run_code_node,
    run_items_node,
    split_items,
    webhook_item,
    wrapped_array,
    wrapped_data,
)

WORKFLOW = "multi-forge-sync.json"
SECRET = "my-secret-key"


def workflow() -> dict[str, Any]:
    return json.loads((WORKFLOW_DIR / WORKFLOW).read_text(encoding="utf-8"))


def node(name: str) -> dict[str, Any]:
    return next(n for n in workflow()["nodes"] if n["name"] == name)


def targets(source: str, output: int) -> list[str]:
    outputs = workflow()["connections"].get(source, {}).get("main", [])
    return [t["node"] for t in outputs[output]] if len(outputs) > output else []


def parse(body: dict[str, Any], *, signed: bool = True) -> dict[str, Any]:
    raw = json.dumps(body, indent=2).encode()
    headers = {"x-gitea-signature": hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()} if signed else {}
    (out,) = run_code_node(
        node_js(WORKFLOW, "Parse Forge Event"), [webhook_item(raw, headers, body)], {"FORGE_WEBHOOK_SECRET": SECRET}
    )
    return out


REPO = {"name": "kubelab", "full_name": "kubelab/kubelab", "owner": {"login": "kubelab"}}


def pull_request(action: str, *, merged: bool = False, title: str = "fix: TOOL-035 forge") -> dict[str, Any]:
    """A Gitea `pull_request` delivery."""
    return {
        "action": action,
        "number": 12,
        "pull_request": {
            "title": title,
            "html_url": "https://gitea.kubelab.live/kubelab/kubelab/pulls/12",
            "merged": merged,
            "head": {"ref": "fix/tool-035-forge"},
        },
        "repository": REPO,
    }


def push() -> dict[str, Any]:
    return {
        "ref": "refs/heads/fix/tool-035-forge",
        "commits": [{"message": "TOOL-035: wip"}],
        "head_commit": {"message": "TOOL-035: wip"},
        "repository": REPO,
    }


def pr_comment() -> dict[str, Any]:
    """Gitea `issue_comment` on a pull request: the PR arrives as `issue.pull_request`."""
    return {
        "action": "created",
        "issue": {"number": 12, "title": "fix: TOOL-035 forge", "pull_request": {"merged": False}},
        "comment": {"body": "lgtm"},
        "is_pull": True,
        "repository": REPO,
    }


def review_comment() -> dict[str, Any]:
    """GitHub `pull_request_review_comment`: carries `pull_request` AND `comment`."""
    body = pull_request("created")
    body["comment"] = {"body": "nit"}
    return body


# ── AC2: which events write ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("body", "kind"),
    [
        pytest.param(pull_request("opened"), "comment", id="opened"),
        pytest.param(pull_request("reopened"), "comment", id="reopened"),
        pytest.param(pull_request("closed", merged=True), "done", id="merged"),
        pytest.param(pull_request("closed"), "none", id="closed-unmerged"),
        pytest.param(pull_request("synchronized"), "none", id="gitea-synchronized"),
        pytest.param(pull_request("synchronize"), "none", id="github-synchronize"),
        pytest.param(pull_request("edited"), "none", id="edited"),
        pytest.param(push(), "none", id="push"),
        pytest.param(pr_comment(), "none", id="pr-comment"),
        pytest.param(review_comment(), "none", id="review-comment"),
    ],
)
def test_only_forward_moving_pull_request_events_write(body: dict[str, Any], kind: str) -> None:
    event = parse(body)
    assert event["taskKey"] == "TOOL-035"
    assert event["prWriteKind"] == kind
    assert event["isTrackedPrEvent"] is (kind != "none")


def test_an_unsigned_merge_writes_nothing() -> None:
    event = parse(pull_request("closed", merged=True), signed=False)
    assert event["isTrackedPrEvent"] is False


def test_a_keyless_merge_writes_nothing() -> None:
    event = parse(
        pull_request("closed", merged=True, title="chore: bump deps")
        | {
            "pull_request": {
                "title": "chore: bump deps",
                "html_url": "u",
                "merged": True,
                "head": {"ref": "chore/deps"},
            }
        }
    )
    assert event["taskKey"] is None
    assert event["isTrackedPrEvent"] is False


def test_the_graph_routes_only_tracked_events_to_the_search() -> None:
    assert targets("Is Issue Event?", 1) == ["Is Tracked PR Event?"]
    assert targets("Is Tracked PR Event?", 0) == ["Find Vikunja Task by Key"]
    assert targets("Is Tracked PR Event?", 1) == ["Respond 200"]
    gate = node("Is Tracked PR Event?")
    assert gate["typeVersion"] >= 2
    assert "$json.isTrackedPrEvent" in json.dumps(gate["parameters"])


def test_only_a_merge_reaches_the_state_write() -> None:
    assert targets("Found Matched Task in Vikunja?", 0) == ["Is PR Merged?"]
    assert targets("Found Matched Task in Vikunja?", 1) == ["Respond 200"]
    assert targets("Is PR Merged?", 0) == ["Update Vikunja Task State"]
    assert targets("Is PR Merged?", 1) == ["Append PR URL Comment"]
    assert targets("Update Vikunja Task State", 0) == ["Append PR URL Comment"]
    assert targets("Append PR URL Comment", 0) == ["Notify #dev-activity"]
    assert targets("Notify #dev-activity", 0) == ["Respond PR Synced"]
    assert "prWriteKind" in json.dumps(node("Is PR Merged?")["parameters"])


# ── AC1: the search is read on every item shape, and matched exactly ─────────

EVENT = {
    "taskKey": "TOOL-035",
    "prWriteKind": "done",
    "prUrl": "https://gitea.kubelab.live/kubelab/kubelab/pulls/12",
    "action": "closed",
}
PRIOR = {"Parse Forge Event": EVENT}

TASK = {"id": 42, "title": "TOOL-035: forge", "description": "<p>keep me</p>", "done": False, "priority": 3}
LONGER = {"id": 99, "title": "TOOL-0350: other", "description": "", "done": False}


def extract(items: list[Any]) -> dict[str, Any]:
    return run_items_node(node_js(WORKFLOW, "Extract Matched Task ID"), items, PRIOR)


@pytest.mark.parametrize("shape", [split_items, wrapped_array, wrapped_data])
def test_the_exact_task_is_found_on_every_shape(shape: Any) -> None:
    for results in ([TASK], [LONGER, TASK], [TASK, LONGER]):
        out = extract(shape(results))
        assert out["hasMatchedTask"] is True, (shape.__name__, results)
        assert out["taskId"] == 42


@pytest.mark.parametrize("shape", [split_items, wrapped_array, wrapped_data])
def test_a_longer_key_is_not_a_match(shape: Any) -> None:
    """#1692: `?s=` is a substring search, and `results[0]` would have marked
    TOOL-0350 done when TOOL-035 merged."""
    out = extract(shape([LONGER]))
    assert out["hasMatchedTask"] is False
    assert out["taskId"] is None


def test_no_results_is_no_task() -> None:
    """`alwaysOutputData` makes the empty search emit `{}` instead of nothing, so
    the node runs and the forge gets an answer (#1659)."""
    for items in (EMPTY_ITEM, wrapped_array([]), wrapped_data([])):
        out = extract(items)
        assert out["hasMatchedTask"] is False
        assert out["updateBody"] is None


def test_a_failed_search_fails_the_run_rather_than_reading_as_no_task() -> None:
    """A 401 is not "no task". Answering 200 `no-task` for it would be the silent
    failure #1659 describes. The search itself has no `onError`, so a failure
    halts the run and the forge records a failed delivery. The extractor refuses
    an error item as well, in case someone later adds one."""
    with pytest.raises(subprocess.CalledProcessError):
        extract(ERROR_ITEM)
    assert node("Find Vikunja Task by Key").get("onError") is None


def test_the_search_emits_an_item_on_zero_results() -> None:
    assert node("Find Vikunja Task by Key").get("alwaysOutputData") is True


def test_the_create_path_searches_reach_the_code_that_branches_on_their_failure() -> None:
    """`Extract Issue Task Match` and `Pick Project for Repo` turn a failed search
    into a 422 `Respond Create Blocked`. That needs the error item, which exists
    only when the node-level setting asks for it (test_n8n_http_error_handling.py)."""
    for name in ("Find Task for Issue", "Resolve Vikunja Project"):
        assert node(name).get("onError") == "continueRegularOutput", name


# ── AC5: the write keeps the task it writes ───────────────────────────────────


def test_the_update_body_is_the_task_with_only_done_changed() -> None:
    """Vikunja 1.0's `POST /tasks/{id}` is a full update: a body of `{done: true}`
    clears description, priority and dates, and an empty title fails validation
    (`Task.updateSingleTask`). So the write sends the task as searched."""
    body = extract(split_items([TASK]))["updateBody"]
    assert body == {**TASK, "done": True}


def test_the_writes_read_the_event_from_the_extractor() -> None:
    for name in ("Update Vikunja Task State", "Append PR URL Comment", "Notify #dev-activity", "Respond PR Synced"):
        params = json.dumps(node(name)["parameters"])
        assert "$('Extract Matched Task ID')" in params, name


def test_a_write_failure_is_not_swallowed() -> None:
    for name in ("Update Vikunja Task State", "Append PR URL Comment"):
        assert node(name).get("onError") in (None, "stopWorkflow"), name


def test_the_comment_names_the_pull_request_and_what_happened() -> None:
    out = extract(split_items([TASK]))
    assert EVENT["prUrl"] in out["comment"]
    assert "merged" in out["comment"]


# ── The answer ────────────────────────────────────────────────────────────────


def test_every_answer_names_its_status() -> None:
    """#1659 AC1: the forge's delivery log is the only cheap observer."""
    for name in ("Respond 200", "Respond PR Synced"):
        assert "status:" in node(name)["parameters"]["responseBody"], name
    assert "no-task" in node("Respond 200")["parameters"]["responseBody"]
