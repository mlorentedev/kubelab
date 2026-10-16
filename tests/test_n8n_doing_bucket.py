"""An opened or reopened pull request moves its task to the in-progress bucket (#2318).

ADR-066 D4, option B of the operator's 2026-10-16 decision: no new bucket, the task
goes to the existing `Doing` one. The rule stays forward-only (APP-CONFIG-016): it
moves a task that is not done, never one a merge already finished, and a success
signal never names a bucket Vikunja did not store. Each node's own JavaScript runs on
the items n8n produces (`tests/n8n_code_node.py`); the route and verb come from
Vikunja 1.0's own swagger (`POST /projects/{p}/views/{v}/buckets/{b}/tasks`, measured
on staging 2026-10-16: the ticket's `PUT` is the bucket-CREATE verb one level up).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.n8n_code_node import WORKFLOW_DIR, node_js, run_items_node, split_items, wrapped_array
from toolkit.features.n8n_import import PLACEHOLDER_SSOT

WORKFLOW = "multi-forge-sync.json"
TOKEN = "RESOLVE_VIKUNJA_IN_PROGRESS_BUCKET"
ROOT = Path(__file__).resolve().parents[1]


def workflow() -> dict[str, Any]:
    return json.loads((WORKFLOW_DIR / WORKFLOW).read_text(encoding="utf-8"))


def node(name: str) -> dict[str, Any]:
    return next(n for n in workflow()["nodes"] if n["name"] == name)


def targets(source: str, output: int) -> list[str]:
    outputs = workflow()["connections"].get(source, {}).get("main", [])
    return [t["node"] for t in outputs[output]] if len(outputs) > output else []


def bucket_js(title: str = "Doing") -> str:
    return node_js(WORKFLOW, "Pick In-Progress Bucket").replace(TOKEN, title)


# ── the target is declared once ──────────────────────────────────────────────


def test_the_bucket_title_is_declared_in_ssot_and_filled_at_import() -> None:
    declared = yaml.safe_load((ROOT / "infra/config/values/common.yaml").read_text(encoding="utf-8"))
    vikunja = declared["apps"]["services"]["core"]["vikunja"]
    assert vikunja["in_progress_bucket"] == "Doing"
    assert PLACEHOLDER_SSOT[TOKEN] == "apps.services.core.vikunja.in_progress_bucket"
    assert TOKEN in node_js(WORKFLOW, "Pick In-Progress Bucket"), "the workflow must carry the token, not a literal"


# ── which tasks move ─────────────────────────────────────────────────────────

TASK = {"id": 42, "project_id": 4, "title": "TOOL-035: forge", "done": False}


def extract(task: dict[str, Any] | None, kind: str) -> dict[str, Any]:
    prior = {"Parse Forge Event": {"taskKey": "TOOL-035", "prWriteKind": kind, "prUrl": "u", "action": "opened"}}
    return run_items_node(node_js(WORKFLOW, "Extract Matched Task ID"), split_items([task] if task else []), prior)


def test_an_opened_pr_moves_a_task_that_is_not_done() -> None:
    out = extract(TASK, "comment")
    assert out["moveToDoing"] is True
    assert out["projectId"] == 4


def test_a_done_task_is_never_moved_back() -> None:
    assert extract({**TASK, "done": True}, "comment")["moveToDoing"] is False


def test_a_merge_does_not_move_the_task_to_doing() -> None:
    assert extract(TASK, "done")["moveToDoing"] is False


def test_no_task_means_no_move() -> None:
    out = extract(None, "comment")
    assert out["moveToDoing"] is False
    assert out["projectId"] is None


# ── finding the view and the bucket without guessing ids ─────────────────────

VIEWS = [
    {"id": 13, "view_kind": "list"},
    {"id": 16, "view_kind": "kanban"},
    {"id": 14, "view_kind": "gantt"},
]
BUCKETS = [{"id": 10, "title": "To-Do"}, {"id": 11, "title": "Doing"}, {"id": 12, "title": "Done"}]


@pytest.mark.parametrize("shape", [split_items, wrapped_array])
def test_the_kanban_view_is_found_by_kind_on_every_item_shape(shape: Any) -> None:
    out = run_items_node(node_js(WORKFLOW, "Pick Kanban View"), shape(VIEWS))
    assert out == {"viewId": 16}


def test_a_project_without_a_kanban_view_fails_the_run() -> None:
    with pytest.raises(subprocess.CalledProcessError) as err:
        run_items_node(node_js(WORKFLOW, "Pick Kanban View"), split_items([VIEWS[0], VIEWS[2]]))
    assert "no Kanban view" in err.value.stderr


@pytest.mark.parametrize("shape", [split_items, wrapped_array])
def test_the_bucket_is_found_by_title_on_every_item_shape(shape: Any) -> None:
    out = run_items_node(bucket_js(), shape(BUCKETS))
    assert out == {"bucketId": 11, "bucketTitle": "Doing"}


def test_the_title_match_ignores_case_and_padding() -> None:
    assert run_items_node(bucket_js(" doing "), split_items(BUCKETS))["bucketId"] == 11


def test_a_missing_bucket_fails_and_lists_what_exists() -> None:
    with pytest.raises(subprocess.CalledProcessError) as err:
        run_items_node(bucket_js("In Review"), split_items(BUCKETS))
    assert "in review" in err.value.stderr
    assert "To-Do" in err.value.stderr, "the failure must name the buckets that do exist"


# ── the write, and the claim about it ────────────────────────────────────────


def test_the_move_is_the_documented_post_with_the_task_id() -> None:
    move = node("Move Task to In-Progress Bucket")["parameters"]
    assert move["method"] == "POST"
    assert "/views/{{ $('Pick Kanban View').first().json.viewId }}/buckets/" in move["url"]
    assert move["url"].endswith("/tasks")
    assert "task_id" in move["jsonBody"]
    assert node("Move Task to In-Progress Bucket").get("onError") in (None, "stopWorkflow")


def confirm(stored: Any) -> dict[str, Any]:
    js = node_js(WORKFLOW, "Confirm Move")
    script_prior = {"Pick In-Progress Bucket": {"bucketId": 11, "bucketTitle": "Doing"}}
    return run_items_node(js, [stored], script_prior)


def test_a_confirmed_move_names_the_bucket_vikunja_stored() -> None:
    assert confirm({"task_id": 42, "bucket_id": 11})["movedTo"] == "Doing"


@pytest.mark.parametrize("stored", [{"task_id": 42, "bucket_id": 10}, {"message": "x"}, {}])
def test_an_unconfirmed_move_fails_instead_of_being_announced(stored: dict[str, Any]) -> None:
    with pytest.raises(subprocess.CalledProcessError) as err:
        confirm(stored)
    assert "move not confirmed" in err.value.stderr


def test_the_notification_and_the_answer_name_a_bucket_only_after_the_confirmation() -> None:
    assert targets("Move Task to In-Progress Bucket", 0) == ["Confirm Move"]
    assert targets("Confirm Move", 0) == ["Notify #dev-activity"]
    for name, key in (("Notify #dev-activity", "jsonBody"), ("Respond PR Synced", "responseBody")):
        body = node(name)["parameters"][key]
        assert "Confirm Move" in body and "moveToDoing" in body, name


def test_a_pr_that_does_not_move_a_task_skips_the_chain() -> None:
    assert targets("Should Move to Doing?", 0) == ["Read Project Views"]
    assert targets("Should Move to Doing?", 1) == ["Notify #dev-activity"]
    chain = [
        "Read Project Views",
        "Pick Kanban View",
        "Read Kanban Buckets",
        "Pick In-Progress Bucket",
        "Move Task to In-Progress Bucket",
        "Confirm Move",
    ]
    for a, b in zip(chain, chain[1:] + ["Notify #dev-activity"], strict=True):
        assert targets(a, 0) == [b], a


def test_every_new_http_node_authenticates_and_reads_ids_from_upstream() -> None:
    for name in ("Read Project Views", "Read Kanban Buckets", "Move Task to In-Progress Bucket"):
        params = node(name)["parameters"]
        assert "VIKUNJA_API_TOKEN" in json.dumps(params), name
        assert "$('Extract Matched Task ID')" in params["url"], name
