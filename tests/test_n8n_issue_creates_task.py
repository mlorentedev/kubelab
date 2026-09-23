"""The `issue opened` -> create-Vikunja-task path in multi-forge-sync (APP-CONFIG-008).

Every test here executes the workflow's OWN JavaScript in Node, the way
`test_n8n_multi_forge_sync.py` does. A Python re-implementation of the node logic
would pass while the shipped workflow was wrong -- the failure mode lesson 413
records, where a fake encoding a wrong belief certifies the belief instead of
refuting it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml

from toolkit.features.configuration import ConfigurationManager
from toolkit.features.gitea_repos import load_webhook
from toolkit.features.n8n_import import PLACEHOLDER_SSOT, resolve_placeholders

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO_ROOT / "infra/n8n/workflows/multi-forge-sync.json"
COMMON_YAML = REPO_ROOT / "infra/config/values/common.yaml"

SECRET = "my-secret-key"


def workflow() -> dict[str, Any]:
    with open(WORKFLOW_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def node_js(name: str) -> str:
    """The node's code AS IT RUNS — placeholders resolved from SSOT.

    The committed JSON carries `RESOLVE_*` tokens that `n8n_import` fills at
    import time. Executing the raw text would test an artifact that never runs
    and would pass with a project title of literally
    `RESOLVE_VIKUNJA_DEFAULT_PROJECT`, so the real resolver is used here — which
    also pins that every token in the workflow is mapped.
    """
    raw = next(n for n in workflow()["nodes"] if n["name"] == name)["parameters"]["jsCode"]
    return resolve_placeholders(raw, ConfigurationManager(env="prod"))


def node(name: str) -> dict[str, Any]:
    return next(n for n in workflow()["nodes"] if n["name"] == name)


def sign(payload: bytes) -> str:
    return f"sha256={hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()}"


def run_node(js: str, items: list[Any], prior: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute one code node against a list of n8n INPUT ITEMS.

    `items` is what the upstream node emitted, one entry per item -- not a single
    `$json`. That distinction is the point: n8n passes data between nodes as an
    array of items, and an HTTP node handed a JSON array emits one item PER
    ELEMENT. A helper that mocked `$json` as the whole array would encode a
    belief about n8n's item model and then certify it (lesson 413) -- the node
    would pass every test and, in production, read the first task as if it were
    the list.
    """
    script = f"""
    const ITEMS = {json.dumps(items)};
    const $input = {{ all: () => ITEMS.map(j => ({{ json: j }})) }};
    const $json = ITEMS[0];
    const PRIOR = {json.dumps(prior or {})};
    const $ = (name) => ({{ first: () => ({{ json: PRIOR[name] }}) }});
    const $env = {{}};
    const result = (() => {{
        {js}
    }})();
    console.log(JSON.stringify(result[0].json));
    """
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(proc.stdout.strip())


#: The shapes an HTTP node's output can take, as separate item lists. Every code
#: node is exercised against ALL of them, because which one arrives is a property
#: of n8n and the response body, not something the workflow chooses.
def split_items(records: list[dict[str, Any]]) -> list[Any]:
    """One item per array element -- what an HTTP node emits for a JSON array."""
    return list(records)


def wrapped_array(records: list[dict[str, Any]]) -> list[Any]:
    """A single item whose json IS the array."""
    return [records]


def wrapped_data(records: list[dict[str, Any]]) -> list[Any]:
    """A single item shaped `{data: [...]}`, the paginated form."""
    return [{"data": records}]


EMPTY_ITEM: list[Any] = [{}]  # what `alwaysOutputData` emits when there is no data
ERROR_ITEM: list[Any] = [{"error": "401 unauthorized"}]  # what `continueOnFail` emits


def parse_event(body: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps(body, separators=(",", ":"))
    js = node_js("Parse Forge Event")
    headers = json.dumps({"x-gitea-signature": sign(payload.encode())})
    script = f"""
    const $json = {{ rawBody: {json.dumps(payload)}, headers: {headers} }};
    const $env = {json.dumps({"FORGE_WEBHOOK_SECRET": SECRET})};
    const result = (() => {{
        {js}
    }})();
    console.log(JSON.stringify(result[0].json));
    """
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(proc.stdout.strip())


def issue_event(action: str, title: str, *, number: int = 7) -> dict[str, Any]:
    return {
        "action": action,
        "number": number,
        "issue": {
            "number": number,
            "title": title,
            "html_url": f"https://gitea.kubelab.live/kubelab/kubelab/issues/{number}",
        },
        "repository": {"name": "kubelab", "full_name": "kubelab/kubelab", "owner": {"login": "kubelab"}},
    }


# ── The key extractor ─────────────────────────────────────────────────────────
#
# AC1 makes the title the join key of the whole integration, so an extractor that
# truncates it is not a cosmetic bug.


def test_a_hyphenated_area_keeps_its_whole_key() -> None:
    """`APP-CONFIG-008` must not extract as `CONFIG-008`.

    Measured 2026-09-05 over 300 real issue titles: the single-segment pattern
    truncated 25 of the 256 it matched, spanning five whole AREAs (`APP-CONFIG`,
    `CI-GATE`, `SEC-VIKUNJA`, `SEC-SOPS`, `SEC-GITEA`). It could never surface as
    a failed lookup, because `?s=` is a substring search and `?s=CONFIG-008`
    still finds `APP-CONFIG-008: ...` -- only as a collision, once two AREAs
    share a final segment.
    """
    for title, expected in [
        ("APP-CONFIG-008: nothing creates the Vikunja task", "APP-CONFIG-008"),
        ("CI-GATE-018: the crossed-signature test", "CI-GATE-018"),
        ("SEC-VIKUNJA-001: public self-registration", "SEC-VIKUNJA-001"),
        ("IDP-035 add sync", "IDP-035"),
        ("TOOL-035: forge", "TOOL-035"),
    ]:
        assert parse_event(issue_event("opened", title))["taskKey"] == expected, title


def test_widening_the_key_did_not_widen_what_matches() -> None:
    """The fix must change WHICH key is extracted, never WHETHER one is.

    A pattern that started matching new things would silently pull unrelated
    events into the create path.
    """
    for title in [
        "feat: reclaim the docker residue",
        "chore: bump v2-3",
        "A-1 is too short an area",
    ]:
        assert parse_event(issue_event("opened", title))["taskKey"] is None, title


# ── The create floor ──────────────────────────────────────────────────────────


def test_the_create_floor_is_exactly_what_add_to_project_fired_on() -> None:
    """AC5, stated as a FLOOR the workflow must cover -- never a copy of it.

    The literal sets live here, in the test. Reading them out of the workflow
    would assert the workflow equals itself (lesson 416): an empty expectation
    is not a weak expectation, it matches everything.
    """
    must_create = {"opened", "reopened"}
    must_not_create = {"closed", "edited", "assigned", "labeled"}

    for action in must_create:
        result = parse_event(issue_event(action, "APP-CONFIG-008: x"))
        assert result["isCreateCandidate"] is True, action

    for action in must_not_create:
        result = parse_event(issue_event(action, "APP-CONFIG-008: x"))
        assert result["isCreateCandidate"] is False, action


def test_the_declared_webhook_events_cover_the_create_trigger() -> None:
    """The forge must actually SEND the event the create path waits for.

    Superset, not equality: Gitea expands `pull_request` into its sub-events, so
    an equality assertion fails forever on a correct hook (`webhook_changes`
    makes the same choice for the same reason).
    """
    declared = set(load_webhook(yaml.safe_load(COMMON_YAML.read_text(encoding="utf-8"))).events)
    assert {"push", "pull_request", "issues"} <= declared


def test_an_unsigned_issue_event_creates_nothing() -> None:
    body = issue_event("opened", "APP-CONFIG-008: x")
    js = node_js("Parse Forge Event")
    script = f"""
    const $json = {{ rawBody: {json.dumps(json.dumps(body, separators=(",", ":")))},
                     headers: {json.dumps({"x-gitea-signature": "sha256=wrong"})} }};
    const $env = {json.dumps({"FORGE_WEBHOOK_SECRET": SECRET})};
    const result = (() => {{ {js} }})();
    console.log(JSON.stringify(result[0].json));
    """
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    result = json.loads(proc.stdout.strip())
    assert result["isValidSig"] is False
    assert result["isCreateCandidate"] is False


def test_a_keyless_issue_creates_nothing() -> None:
    """AC1 requires a key, so 'every issue' means 'every KEYED issue'.

    Stated as a test rather than left implicit: an issue filed without an
    `AREA-NNN` title still answers 200 and still reaches no board.
    """
    result = parse_event(issue_event("opened", "something broke again"))
    assert result["taskKey"] is None
    assert result["isCreateCandidate"] is False


# ── Keeping the two paths apart ───────────────────────────────────────────────


def test_a_pull_request_event_is_not_an_issue_event() -> None:
    """The whole point of branching early: an issue event must never reach
    `Update Vikunja Task State`, which writes `{done: false}` and would undo a
    task somebody finished."""
    body = {
        "action": "opened",
        "pull_request": {
            "title": "feat: APP-CONFIG-008 wire it up",
            "html_url": "https://github.com/org/repo/pull/1",
            "merged": False,
            "head": {"ref": "feat/app-config-008"},
        },
    }
    result = parse_event(body)
    assert result["isIssueEvent"] is False
    assert result["isCreateCandidate"] is False
    assert result["hasTask"] is True


def test_a_pull_request_comment_is_not_an_issue_event() -> None:
    """Gitea sends an `issue` object for PR comments too, with
    `issue.pull_request` populated. Treated as an issue it would create a task
    for every commented-on pull request."""
    body = issue_event("opened", "APP-CONFIG-008: x")
    body["issue"]["pull_request"] = {"html_url": "https://gitea.kubelab.live/x/y/pulls/1"}
    assert parse_event(body)["isIssueEvent"] is False


def test_the_pull_request_chain_still_ends_where_it_did() -> None:
    conns = workflow()["connections"]
    assert conns["Found Matched Task in Vikunja?"]["main"][0][0]["node"] == "Update Vikunja Task State"
    assert conns["Update Vikunja Task State"]["main"][0][0]["node"] == "Append PR URL Comment"
    # The split is the only re-point: the first gate now goes to the issue/PR
    # fork, whose FALSE branch is the search the chain always started with.
    assert conns["Has Task Key & Valid Sig?"]["main"][0][0]["node"] == "Is Issue Event?"
    assert conns["Is Issue Event?"]["main"][1][0]["node"] == "Find Vikunja Task by Key"


# ── Idempotence (AC2) ─────────────────────────────────────────────────────────


PARSED = {
    "Parse Forge Event": {
        "taskKey": "TOOL-035",
        "title": "TOOL-035: forge",
        "issueUrl": "u",
        "repoOwner": "kubelab",
        "repoName": "kubelab",
        "issueNumber": 7,
    }
}


def test_an_existing_task_is_matched_exactly_not_by_substring() -> None:
    """`?s=` is a substring search. Taking `results[0]` -- what the pull-request
    path does -- would decide `TOOL-035` already exists because `TOOL-0350` does,
    and never create it, with a 200 on the way out.

    Run against all three item shapes: which one arrives is decided by n8n and
    the response body, not by the workflow, so a node that is only correct for
    one of them is only accidentally correct.
    """
    js = node_js("Extract Issue Task Match")

    for shape in (split_items, wrapped_array, wrapped_data):
        longer = run_node(js, shape([{"id": 99, "title": "TOOL-0350: something else"}]), PARSED)
        assert longer["taskAlreadyExists"] is False, shape.__name__
        assert longer["existingTaskId"] is None, shape.__name__

        for title in ["TOOL-035: forge", "TOOL-035-forge-migration"]:
            found = run_node(js, shape([{"id": 42, "title": title}]), PARSED)
            assert found["taskAlreadyExists"] is True, f"{shape.__name__}/{title}"
            assert found["existingTaskId"] == 42, f"{shape.__name__}/{title}"


def test_a_multi_result_search_still_finds_the_exact_task() -> None:
    """The split shape is the one that bites: with several results, `$json` is
    the FIRST task rather than the list. A node reading `$json` would see one
    task, fail `Array.isArray`, fall through to no results, and create a
    duplicate of a task it was looking straight at."""
    results = [{"id": 99, "title": "TOOL-0350: other"}, {"id": 42, "title": "TOOL-035: forge"}]
    found = run_node(node_js("Extract Issue Task Match"), split_items(results), PARSED)
    assert found["taskAlreadyExists"] is True
    assert found["existingTaskId"] == 42


def test_an_empty_search_result_creates() -> None:
    """The primary case this whole path exists for: a new issue, no task yet.

    `alwaysOutputData` on the request node makes it emit `{}` rather than no item
    at all -- a node with no input does not run, so without it the chain would
    stop dead here and the webhook would time out with nothing answered.
    """
    for items in (EMPTY_ITEM, split_items([]), wrapped_array([])):
        result = run_node(node_js("Extract Issue Task Match"), items or EMPTY_ITEM, PARSED)
        assert result["taskAlreadyExists"] is False
        assert result["searchFailed"] is False


def test_a_failed_search_is_not_an_empty_search() -> None:
    """`continueOnFail` turns a 401 into an item carrying `error`, which is
    shaped exactly like 'found nothing'. Creating on it duplicates a task that
    already exists."""
    result = run_node(node_js("Extract Issue Task Match"), ERROR_ITEM, PARSED)
    assert result["searchFailed"] is True

    picked = run_node(
        node_js("Pick Project for Repo"),
        split_items([{"id": 3, "title": "kubelab"}]),
        {"Extract Issue Task Match": result},
    )
    assert picked["readyToCreate"] is False


def test_a_failed_project_lookup_blocks_the_create() -> None:
    prior = {"Extract Issue Task Match": {"repoOwner": "kubelab", "repoName": "kubelab", "searchFailed": False}}
    picked = run_node(node_js("Pick Project for Repo"), ERROR_ITEM, prior)
    assert picked["projectLookupFailed"] is True
    assert picked["readyToCreate"] is False


def test_the_created_title_carries_the_key_as_a_prefix() -> None:
    """AC1 by construction. The key can be extracted from mid-title, so the task
    title is built rather than copied."""
    prior_mid = {
        "Parse Forge Event": {
            "taskKey": "TOOL-035",
            "title": "fix the TOOL-035 thing",
            "issueUrl": "u",
            "repoOwner": "kubelab",
            "repoName": "kubelab",
            "issueNumber": 7,
        }
    }
    assert run_node(node_js("Extract Issue Task Match"), EMPTY_ITEM, prior_mid)["taskTitle"].startswith("TOOL-035")
    assert run_node(node_js("Extract Issue Task Match"), EMPTY_ITEM, PARSED)["taskTitle"] == "TOOL-035: forge"


# ── Project resolution fails closed ───────────────────────────────────────────


def test_an_unmatched_repository_does_not_fall_back_to_a_default_project() -> None:
    """`slack-task-capture` defaults to project 1 because a human sees where the
    task landed. Nothing watches a webhook, so the same default files issues into
    an arbitrary project invisibly and forever."""
    prior = {"Extract Issue Task Match": {"repoOwner": "teledyne", "repoName": "fae-brain", "searchFailed": False}}
    for shape in (split_items, wrapped_array, wrapped_data):
        result = run_node(node_js("Pick Project for Repo"), shape([{"id": 1, "title": "Inbox"}]), prior)
        assert result["projectId"] is None, shape.__name__
        assert result["readyToCreate"] is False, shape.__name__


def test_every_repository_routes_to_the_one_declared_board() -> None:
    """ADR-066 revised: one board, provenance in `area:*` labels and in the
    mandatory `AREA-NNN` title key — not in separate projects.

    So the repository no longer selects anything. A node that still matched on it
    would route `teledyne/fae-brain` somewhere other than `kubelab/kubelab`,
    which is the split this change withdrew.
    """
    declared = ConfigurationManager(env="prod").get_merged_config()["apps"]["services"]["core"]["vikunja"][
        "default_project"
    ]
    projects = [{"id": 1, "title": "Inbox"}, {"id": 2, "title": declared}, {"id": 3, "title": "kubelab"}]

    for repo in (
        {"repoOwner": "teledyne", "repoName": "fae-brain"},
        {"repoOwner": "kubelab", "repoName": "kubelab"},
        {"repoOwner": "personal", "repoName": "resume"},
    ):
        for shape in (split_items, wrapped_array, wrapped_data):
            result = run_node(
                node_js("Pick Project for Repo"),
                shape(projects),
                {"Extract Issue Task Match": {**repo, "searchFailed": False}},
            )
            assert result["projectId"] == 2, f"{repo['repoName']}/{shape.__name__}"
            assert result["readyToCreate"] is True


def test_the_declared_board_is_matched_case_insensitively_by_title() -> None:
    """Resolved by title rather than id, because an id is environment-specific
    and opaque — the same workflow would silently target a different board per
    environment, and nothing would report it."""
    declared = ConfigurationManager(env="prod").get_merged_config()["apps"]["services"]["core"]["vikunja"][
        "default_project"
    ]
    prior = {"Extract Issue Task Match": {"repoOwner": "kubelab", "repoName": "kubelab", "searchFailed": False}}

    result = run_node(
        node_js("Pick Project for Repo"), split_items([{"id": 7, "title": f"  {declared.upper()}  "}]), prior
    )
    assert result["projectId"] == 7


def test_the_workflow_declares_no_placeholder_the_importer_cannot_fill() -> None:
    """An unmapped `RESOLVE_*` token reaches the running workflow as a literal
    string. It would fail closed — nothing is titled `RESOLVE_...` — but in
    production, and naming no cause. The import refuses instead; this asserts the
    committed workflow gives it nothing to refuse."""
    import re

    tokens = set(re.findall(r"RESOLVE_[A-Z0-9_]+", WORKFLOW_PATH.read_text(encoding="utf-8")))
    assert tokens <= set(PLACEHOLDER_SSOT), (
        f"unmapped placeholder(s) {sorted(tokens - set(PLACEHOLDER_SSOT))} — add them to "
        f"`PLACEHOLDER_SSOT` with the common.yaml path they read"
    )


# ── The graph's own honesty ───────────────────────────────────────────────────


def test_the_create_request_may_not_swallow_its_own_failure() -> None:
    """AC3: never trust the 2xx. With `continueOnFail`, a create that 401s would
    flow on to the notify node and the 201 -- three success signals for a task
    that does not exist."""
    assert node("Create Task from Issue")["parameters"]["options"].get("continueOnFail") is not True


def test_a_blocked_create_answers_non_2xx() -> None:
    """The forge's delivery log is the only observer. A 200 there is
    indistinguishable from a task that was created."""
    assert node("Respond Create Blocked")["parameters"]["options"]["responseCode"] == 422
    assert node("Respond Task Created")["parameters"]["options"]["responseCode"] == 201


def test_a_search_that_finds_nothing_still_emits_an_item() -> None:
    """A node that yields no data emits NO ITEM, and a node with no input does
    not run. `GET /tasks?s=<a brand-new key>` returning `[]` is the primary case
    this path exists for -- without `alwaysOutputData` the chain stops dead
    there, no respond node fires, and the webhook times out. Nothing about that
    failure names its cause."""
    for name in ("Find Task for Issue", "Resolve Vikunja Project"):
        assert node(name).get("alwaysOutputData") is True, name


def test_the_post_create_nodes_read_the_event_from_the_node_that_holds_it() -> None:
    """`$json` at a node is that node's INPUT. After `Create Task from Issue`
    the input is Vikunja's created-task object, so a bare `$json.taskKey` is
    `undefined` -- the notice would read "Task created: undefined" and
    `JSON.stringify` would silently drop the undefined fields from the 201 body.

    Both nodes must reach back to `Pick Project for Repo` for the event, and the
    only field they may take from `$json` is the new task's `id`.
    """
    for name, key in [("Notify Task Created", "jsonBody"), ("Respond Task Created", "responseBody")]:
        body = node(name)["parameters"][key]
        assert "$('Pick Project for Repo')" in body, name
        for field in ("taskKey", "repoOwner", "repoName", "issueNumber", "projectTitle", "projectId", "issueUrl"):
            assert f"$json.{field}" not in body, f"{name} reads $json.{field}, which is undefined there"

    assert "$json.id" in node("Respond Task Created")["parameters"]["responseBody"], (
        "the created task's id is the cheapest observable that a task exists (#1659)"
    )


def test_the_creation_notice_does_not_announce_a_bucket() -> None:
    """`targetBucket` is computed and never written to Vikunja (#1687). A notice
    naming it would be that defect reintroduced -- and this path's notice is the
    one a human actually reads."""
    body = node("Notify Task Created")["parameters"]["jsonBody"]
    assert "targetBucket" not in body
    assert "Task created" in body


def test_the_create_path_is_reachable_end_to_end() -> None:
    conns = workflow()["connections"]
    hop = {
        "Should Create Task?": "Find Task for Issue",
        "Find Task for Issue": "Extract Issue Task Match",
        "Extract Issue Task Match": "Task Already Exists?",
        "Resolve Vikunja Project": "Pick Project for Repo",
        "Pick Project for Repo": "Ready to Create?",
        "Create Task from Issue": "Notify Task Created",
        "Notify Task Created": "Respond Task Created",
    }
    for src, dst in hop.items():
        assert conns[src]["main"][0][0]["node"] == dst, src
    assert conns["Task Already Exists?"]["main"][1][0]["node"] == "Resolve Vikunja Project"
    assert conns["Ready to Create?"]["main"][0][0]["node"] == "Create Task from Issue"
    assert conns["Ready to Create?"]["main"][1][0]["node"] == "Respond Create Blocked"


def test_the_workflow_survives_a_pvc_wipe() -> None:
    """AC4. A workflow committed to git but absent from the import catalog is
    restored by hand or not at all (APP-CONFIG-009)."""
    from toolkit.features.n8n_import import N8N_IMPORT_CATALOG

    imported = {str(spec.workflow_path) for spec in N8N_IMPORT_CATALOG}
    assert "infra/n8n/workflows/multi-forge-sync.json" in imported
