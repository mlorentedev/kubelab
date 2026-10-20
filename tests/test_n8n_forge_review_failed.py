"""TOOL-093 (#1957) -- the `forge-review-failed` workflow tells the author once that no review is coming.

Grafana calls it when the rule `tool093-reviewer-failed` fires; it comments on the pull request through
the comment-only Gitea credential. What is pinned is what Grafana and Gitea observe, by running the
REAL committed `jsCode` of both Code nodes:

- on the body Grafana 13.0.2 really sends (`tests/fixtures/grafana/forge-review-failed-webhook.json`,
  captured, not written by hand), inside the item shape a Webhook v2 hands a Code node;
- on the HTTP node's `fullResponse` output, which is ONE item per pull request whose `body` is the
  comment list -- not one item per comment, which is what the node emits without that option and
  which turns a PR with no comments into zero items, ending the run before the first notice.

The whole workflow was also run in the pinned n8n 2.12.3 against a Gitea 1.27.3, and these tests hold
the facts that run found: the task runner's sandbox has NO `URL` global (the first version parsed the
label with it and failed on every call), a run that ends on an empty node answers Grafana 500 (it would
retry a dedup or a bad label as a failed notification), and Gitea lists 30 comments a page unless asked.
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.n8n_code_node import WORKFLOW_DIR, node_js, run_code_node, webhook_item
from toolkit.features.n8n_import import (
    N8N_IMPORT_CATALOG,
    N8N_SHARED_CREDENTIALS,
    PLACEHOLDER_SSOT,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = "forge-review-failed.json"
FIXTURE = json.loads((REPO_ROOT / "tests" / "fixtures" / "grafana" / "forge-review-failed-webhook.json").read_text())
RULES = REPO_ROOT / "infra" / "k8s" / "base" / "services" / "grafana-alerting" / "rules.yaml"

DOMAIN = "gitea.kubelab.live"
PR = f"https://{DOMAIN}/personal/imagesensortool/pulls/29"
STARTS_AT = "2026-10-18T10:59:50Z"
MARKER = f"<!-- forge-review-failed:{STARTS_AT} -->"

TERMINALS = {"Comment Posted", "Nothing To Post"}


def _workflow() -> dict[str, Any]:
    return json.loads((WORKFLOW_DIR / WORKFLOW).read_text(encoding="utf-8"))


def _node(name: str) -> dict[str, Any]:
    return next(n for n in _workflow()["nodes"] if n["name"] == name)


def _parse_js() -> str:
    return node_js(WORKFLOW, "Parse Alerts").replace("RESOLVE_GITEA_DOMAIN", DOMAIN)


def _parse(body: Any) -> list[dict[str, Any]]:
    item = webhook_item(json.dumps(body).encode(), dict(FIXTURE["headers"]), body)
    return run_code_node(_parse_js(), [item])


def _body(*alerts: dict[str, Any]) -> dict[str, Any]:
    body = copy.deepcopy(FIXTURE["body"])
    body["alerts"] = list(alerts)
    return body


def _alert(**changes: Any) -> dict[str, Any]:
    alert = copy.deepcopy(FIXTURE["body"]["alerts"][0])
    labels = changes.pop("labels", {})
    alert["labels"].update(labels)
    alert.update(changes)
    return alert


def _already_told(comments_response: dict[str, Any], pr: dict[str, Any]) -> dict[str, Any]:
    """Run 'Already Told?' (once for each item) on the HTTP node's output for one PR."""
    script = f"""
    const RES = {json.dumps(comments_response)};
    const PR = {json.dumps(pr)};
    const $input = {{ item: {{ json: RES }} }};
    const $ = (name) => {{
      if (name !== 'Parse Alerts') throw new Error('unexpected node ' + name);
      return {{ item: {{ json: PR }} }};
    }};
    const out = (() => {{ {node_js(WORKFLOW, "Already Told?")} }})();
    console.log(JSON.stringify(out.json));
    """
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(next((l for l in proc.stderr.splitlines() if l.startswith("Error:")), proc.stderr))
    return json.loads(proc.stdout.strip())


PARSED = {
    "origin": f"https://{DOMAIN}",
    "owner": "personal",
    "repo": "imagesensortool",
    "index": "29",
    "marker": MARKER,
    "since": STARTS_AT,
}


# --- Parse Alerts: the real Grafana body -------------------------------------------------------


def test_the_captured_grafana_body_becomes_one_pull_request():
    assert _parse(FIXTURE["body"]) == [PARSED]


def test_a_group_yields_one_item_per_firing_pull_request_in_order():
    other = f"https://{DOMAIN}/personal/other-repo/pulls/7"
    body = _body(_alert(), _alert(labels={"pr": other}, startsAt="2026-10-18T13:05:00Z"))

    parsed = _parse(body)

    assert [(p["repo"], p["index"], p["marker"]) for p in parsed] == [
        ("imagesensortool", "29", MARKER),
        ("other-repo", "7", "<!-- forge-review-failed:2026-10-18T13:05:00Z -->"),
    ]


def test_a_bad_alert_in_a_group_does_not_cost_the_good_one_its_comment():
    body = _body(_alert(labels={"pr": f"https://{DOMAIN}/personal/proj/issues/2"}), _alert())

    assert _parse(body) == [PARSED]


@pytest.mark.parametrize(
    ("label", "alert"),
    [
        ("resolved", _alert(status="resolved")),
        ("another rule", _alert(ruleUID="some-other-rule")),
        ("another forge", _alert(labels={"pr": "https://evil.example/personal/proj/pulls/1"})),
        ("a host that only starts like the forge", _alert(labels={"pr": f"https://{DOMAIN}.evil.example/a/b/pulls/1"})),
        ("an issue, not a pull request", _alert(labels={"pr": f"https://{DOMAIN}/personal/proj/issues/1"})),
        ("a query string", _alert(labels={"pr": f"{PR}?x=1"})),
        ("a fragment", _alert(labels={"pr": f"{PR}#issuecomment-1"})),
        ("a path traversal", _alert(labels={"pr": f"https://{DOMAIN}/personal/../admin/pulls/1"})),
        ("a dot-dot repo name", _alert(labels={"pr": f"https://{DOMAIN}/personal/../pulls/1"})),
        ("a dot-dot owner name", _alert(labels={"pr": f"https://{DOMAIN}/../proj/pulls/1"})),
        ("a trailing path", _alert(labels={"pr": f"{PR}/files"})),
        ("plain http", _alert(labels={"pr": PR.replace("https", "http")})),
        ("no pr label", {**_alert(), "labels": {"alertname": "x"}}),
        ("a startsAt that is not a timestamp", _alert(startsAt="soon")),
        ("no startsAt", {k: v for k, v in _alert().items() if k != "startsAt"}),
    ],
)
def test_only_a_firing_pull_request_of_this_forge_reaches_a_gitea_url(label, alert):
    """Each drop answers with ONE `skip` item: see the empty-answer test below for why not zero."""
    assert _parse(_body(alert)) == [{"skip": True}], label


@pytest.mark.parametrize("body", [{}, {"alerts": []}, {"alerts": "nope"}, {"alerts": None}])
def test_a_body_with_nothing_to_act_on_is_one_skip_item(body):
    assert _parse(body) == [{"skip": True}]


def test_the_sandbox_has_no_url_global_so_the_node_must_not_use_one():
    """n8n 2.12.3's task runner: `ReferenceError: URL is not defined`. Node's own runtime has it, so
    the run above cannot show this; the lab did, on every call, until the label was matched by pattern."""
    for name in ("Parse Alerts", "Already Told?"):
        code = re.sub(r"//.*", "", node_js(WORKFLOW, name))
        assert not re.search(r"\bnew\s+URL\b|\bURLSearchParams\b", code), name


# --- Already Told?: the comment list of one PR --------------------------------------------------


def _list(*comment_bodies: str, status: int = 200) -> dict[str, Any]:
    return {"statusCode": status, "body": [{"body": b} for b in comment_bodies]}


def test_a_pull_request_with_no_comments_gets_the_notice():
    """The case a per-element HTTP output loses: an empty list is ONE item with `body: []`."""
    out = _already_told(_list(), PARSED)

    assert out["post"] is True
    assert out["comment"].rstrip().endswith(MARKER)


def test_the_notice_says_it_did_not_run_and_how_to_retry():
    comment = _already_told(_list(), PARSED)["comment"]

    assert "did not run" in comment
    assert "Push a commit" in comment
    assert "`/review`" in comment  # said to be ignored, so the author does not try it


def test_a_comment_carrying_this_failures_marker_means_it_was_already_told():
    out = _already_told(_list("unrelated", f"**The automated review did not run**\n\n{MARKER}"), PARSED)

    assert out["post"] is False


def test_a_new_failure_of_the_same_pull_request_is_told_again():
    older = "<!-- forge-review-failed:2026-10-18T08:00:00Z -->"

    assert _already_told(_list(f"earlier notice\n{older}"), PARSED)["post"] is True


def test_an_unreadable_comment_list_fails_the_run_rather_than_posting_blind():
    with pytest.raises(RuntimeError, match="could not read the comments of personal/imagesensortool#29"):
        _already_told({"statusCode": 200, "body": {"message": "nope"}}, PARSED)


# --- the workflow as n8n runs it ---------------------------------------------------------------


def test_every_path_ends_in_a_node_that_emits_an_item():
    """A webhook answers with its last node's items; none is a 500 that Grafana retries as a failed
    notification. Measured: a repeat, an empty body and a foreign label all answered 500 before."""
    connections = _workflow()["connections"]
    names = {n["name"] for n in _workflow()["nodes"]}
    ends = {n for n in names if not any(c for outs in connections.get(n, {}).get("main", []) for c in outs)}

    assert ends == TERMINALS
    assert _node("Nothing To Post")["type"] == "n8n-nodes-base.noOp"  # always passes its input through


def test_a_gitea_refusal_fails_the_run_so_grafana_hears_a_500_and_sends_again():
    """With `onError: continueRegularOutput` (or any of its relatives) on Post Comment all the other
    tests stay green, a refused post ends in an item, and the notice is dropped behind a 200 with no
    retry. The failure path is the error path: nothing on the Gitea nodes may swallow it."""
    swallowing = ("onError", "continueOnFail", "alwaysOutputData", "retryOnFail")
    for node in _workflow()["nodes"]:
        assert not any(key in node for key in swallowing), node["name"]
        assert not re.search(r"neverError|ignoreHttpStatusErrors", json.dumps(node["parameters"])), node["name"]


def test_the_answer_to_grafana_is_not_gitea_s_comment():
    """A webhook returns its last node's items; Post Comment's are Gitea's comment JSON, with the
    posting account's user object. The posting path ends in a node that answers with a fixed body."""
    connections = _workflow()["connections"]

    assert [c["node"] for c in connections["Post Comment"]["main"][0]] == ["Comment Posted"]
    out = run_code_node(node_js(WORKFLOW, "Comment Posted"), [{"json": {"id": 4, "user": {"login": "reviewer"}}}])
    assert out == [{"posted": True}]


def test_both_ways_of_having_nothing_to_post_reach_the_noop():
    main = _workflow()["connections"]
    no_branch = lambda name: [c["node"] for c in main[name]["main"][1]]  # noqa: E731

    assert no_branch("Any Pull Request?") == ["Nothing To Post"]
    assert no_branch("Needs Comment?") == ["Nothing To Post"]


def test_the_comment_list_is_read_whole_and_bounded_to_this_failure():
    node = _node("Read PR Comments")

    assert node["parameters"]["options"]["response"]["response"]["fullResponse"] is True
    url = node["parameters"]["url"]
    assert "/comments?since={{ $json.since }}&limit=50" in url  # 30 a page by default; the marker is newer than startsAt
    assert node["parameters"]["method"] == "GET"


def test_the_post_serialises_the_comment_instead_of_splicing_it_into_json():
    post = _node("Post Comment")["parameters"]

    assert post["method"] == "POST"
    assert post["jsonBody"] == "={{ JSON.stringify({ body: $json.comment }) }}"


def test_the_webhook_answers_with_the_last_node_and_wants_the_bearer():
    webhook = _node("Webhook Ingress")["parameters"]

    assert webhook["authentication"] == "headerAuth"
    assert webhook["responseMode"] == "lastNode"
    assert webhook["path"] == "forge-review-failed"


def test_the_nodes_reference_the_credentials_the_importer_creates():
    spec = next(s for s in N8N_IMPORT_CATALOG if s.workflow_path.name == WORKFLOW)
    shared = next(c for c in N8N_SHARED_CREDENTIALS if c.name == "gitea-review-notice")

    webhook = _node("Webhook Ingress")["credentials"]["httpHeaderAuth"]
    assert webhook["name"] == spec.credential_name
    for name in ("Read PR Comments", "Post Comment"):
        used = _node(name)["credentials"]["httpHeaderAuth"]
        assert (used["id"], used["name"]) == (shared.credential_id, shared.name), name


def test_the_forge_host_is_resolved_from_the_same_place_the_forge_is_served_from():
    assert PLACEHOLDER_SSOT["RESOLVE_GITEA_DOMAIN"] == "apps.services.core.gitea.domain"
    assert "RESOLVE_GITEA_DOMAIN" in node_js(WORKFLOW, "Parse Alerts")


# --- Grafana's side agrees with the workflow's ---------------------------------------------------


def test_the_workflow_filters_on_the_rule_that_is_committed():
    rule = next(
        r
        for g in yaml.safe_load(RULES.read_text())["groups"]
        for r in g["rules"]
        if r["uid"] == "tool093-reviewer-failed"
    )

    assert "'tool093-reviewer-failed'" in node_js(WORKFLOW, "Parse Alerts")
    # The route matches on the rule's title, the alert's `alertname`.
    assert FIXTURE["body"]["alerts"][0]["labels"]["alertname"] == rule["title"]
