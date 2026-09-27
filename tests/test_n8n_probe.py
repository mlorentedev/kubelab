"""`toolkit infra n8n probe`: the public n8n webhooks, driven end to end (APP-CONFIG-015 AC4/AC5).

The pure parts (signing, the event, the verdict on an execution) are tested on
their own. The orchestrator is tested with `post` and `exec_node` injected, so no
cluster, no SOPS and no HTTP are needed. What the fakes return is the shape the
in-pod script emits, which is what `summarise` in the script builds from
`execution_entity` and `execution_data`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from toolkit.features.n8n_probe import (
    FORGE_SECRET_KEY,
    ExecutionSummary,
    build_issue_event,
    forge_headers,
    http_request_nodes,
    judge_gate_stop,
    load_workflow,
    run_n8n_probe,
    wait_for_execution,
    webhook_path,
)

_SECRET = "forge-secret"
_DOMAIN = "n8n.staging.kubelab.live"

FORGE = "multi-forge-sync.json"
SLACK = "slack-task-capture.json"
AGENT = "agent-dispatcher.json"


# ── Pure helpers ──────────────────────────────────────────────────────────────


def test_forge_headers_carry_a_gitea_signature_over_the_exact_bytes() -> None:
    raw = b'{\n  "a": 1\n}'
    headers = forge_headers(raw, _SECRET)
    assert headers["X-Gitea-Event"] == "issues"
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Gitea-Signature"] == hmac.new(_SECRET.encode(), raw, hashlib.sha256).hexdigest()


def test_forge_headers_without_a_secret_are_unsigned() -> None:
    headers = forge_headers(b"{}", None)
    assert "X-Gitea-Signature" not in headers
    assert "X-Hub-Signature-256" not in headers


def test_issue_event_is_a_create_candidate_shape() -> None:
    event = build_issue_event("PROBE-1700000000")
    assert event["action"] == "opened"
    assert event["issue"]["title"].startswith("PROBE-1700000000")
    assert "pull_request" not in event and "pull_request" not in event["issue"]
    assert event["repository"]["owner"]["login"]


def test_webhook_path_and_http_nodes_are_read_from_the_committed_workflow() -> None:
    forge = load_workflow(FORGE)
    assert webhook_path(forge) == "/webhook/multi-forge-sync"
    nodes = http_request_nodes(forge)
    assert "Create Task from Issue" in nodes
    assert "Notify #dev-activity" in nodes
    assert "Parse Forge Event" not in nodes


def _summary(outputs: dict[str, list[int]], status: str = "success") -> ExecutionSummary:
    return ExecutionSummary(id=7, status=status, outputs=outputs)


def test_an_execution_that_stops_at_its_gate_is_accepted() -> None:
    summary = _summary({"Webhook Ingress": [1], "Parse Forge Event": [1], "Has Task Key & Valid Sig?": [0, 1]})
    assert judge_gate_stop(summary, "Has Task Key & Valid Sig?", {"Create Task from Issue"}) == []


def test_a_gate_that_let_the_item_through_is_reported() -> None:
    summary = _summary({"Has Task Key & Valid Sig?": [1, 0], "Is Issue Event?": [1, 0]})
    errors = judge_gate_stop(summary, "Has Task Key & Valid Sig?", {"Create Task from Issue"})
    assert any("TRUE" in e for e in errors)


def test_an_http_node_that_ran_is_reported_even_if_the_gate_looks_right() -> None:
    summary = _summary({"Is Slack Valid?": [0, 1], "Lookup Vikunja Projects": [3]})
    errors = judge_gate_stop(summary, "Is Slack Valid?", {"Lookup Vikunja Projects"})
    assert any("Lookup Vikunja Projects" in e for e in errors)


def test_a_gate_that_never_ran_is_reported() -> None:
    errors = judge_gate_stop(_summary({"Webhook Ingress": [1]}), "Is Slack Valid?", set())
    assert any("never ran" in e for e in errors)


def test_a_failed_execution_is_reported() -> None:
    errors = judge_gate_stop(_summary({"Is Slack Valid?": [0, 1]}, status="error"), "Is Slack Valid?", set())
    assert any("error" in e for e in errors)


# ── Finding the execution ─────────────────────────────────────────────────────


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _rows(*rows: tuple[int, str]) -> list[dict[str, Any]]:
    return [{"id": i, "status": s, "outputs": {"Webhook Ingress": [1]}} for i, s in rows]


def test_waits_until_the_new_execution_is_terminal() -> None:
    clock = _Clock()
    answers = iter([[], _rows((5, "running")), _rows((5, "success"))])
    summary, error = wait_for_execution(lambda: next(answers), clock=clock, sleep=clock.sleep, timeout=30)
    assert error is None
    assert summary is not None and summary.id == 5 and summary.status == "success"


def test_two_new_executions_are_ambiguous_not_guessed() -> None:
    clock = _Clock()
    summary, error = wait_for_execution(
        lambda: _rows((5, "success"), (6, "success")), clock=clock, sleep=clock.sleep, timeout=30
    )
    assert summary is None
    assert error is not None and "ambiguous" in error


def test_no_execution_before_the_timeout_names_the_save_setting() -> None:
    clock = _Clock()
    summary, error = wait_for_execution(lambda: [], clock=clock, sleep=clock.sleep, timeout=10)
    assert summary is None
    assert error is not None and "EXECUTIONS_DATA_SAVE" in error


# ── Orchestrator ──────────────────────────────────────────────────────────────


def _cm(secret: str | None = _SECRET) -> MagicMock:
    cm = MagicMock()
    cm.get_secret_by_path.side_effect = lambda p: secret if p == FORGE_SECRET_KEY else None
    cm.get_merged_config.return_value = {"apps": {"services": {"automation": {"n8n": {"domain": _DOMAIN}}}}}
    return cm


class _Cluster:
    """Fakes the n8n pod: executions per workflow, and the Vikunja task store.

    `respond` decides what each POST does to the cluster, keyed by webhook path and
    whether the request carried a valid forge signature.
    """

    def __init__(self, *, signed_creates: bool = True, delete_status: int = 204, open_gates: bool = False) -> None:
        self.executions: dict[str, list[dict[str, Any]]] = {}
        self.tasks: dict[int, str] = {}
        self.deleted: list[int] = []
        self.signed_creates = signed_creates
        self.delete_status = delete_status
        self.open_gates = open_gates  # the #1712 defect: every gate routes to TRUE
        self.posts: list[tuple[str, bytes, dict[str, str]]] = []
        self.workflow_ids = {name: load_workflow(name)["id"] for name in (FORGE, SLACK, AGENT)}

    def _run(self, workflow: str, outputs: dict[str, list[int]]) -> None:
        wf_id = self.workflow_ids[workflow]
        rows = self.executions.setdefault(wf_id, [])
        rows.append({"id": sum(len(r) for r in self.executions.values()) + 1, "status": "success", "outputs": outputs})

    def post(self, url: str, body: bytes, headers: dict[str, str]) -> tuple[int, str]:
        self.posts.append((url, body, headers))
        if url.endswith("/webhook/multi-forge-sync"):
            expected = hmac.new(_SECRET.encode(), body, hashlib.sha256).hexdigest()
            if headers.get("X-Gitea-Signature") == expected and self.signed_creates:
                task_id = 100 + len(self.tasks)
                self.tasks[task_id] = json.loads(body)["issue"]["title"]
                self._run(FORGE, {"Has Task Key & Valid Sig?": [1, 0], "Create Task from Issue": [1]})
                return 201, json.dumps({"status": "ok", "created": True, "taskId": task_id})
            if self.open_gates:
                self._run(FORGE, {"Has Task Key & Valid Sig?": [1, 0], "Find Task for Issue": [0]})
            else:
                self._run(FORGE, {"Has Task Key & Valid Sig?": [0, 1], "Respond 200": [1]})
            return 200, json.dumps({"status": "ok"})
        if url.endswith("/webhook/slack-task-capture"):
            if self.open_gates:
                self._run(SLACK, {"Is Slack Valid?": [1, 0], "Lookup Vikunja Projects": [1]})
            else:
                self._run(SLACK, {"Instant Slack Ack (<500ms)": [1], "Is Slack Valid?": [0, 1]})
            return 200, "{}"
        if url.endswith("/webhook/agent-dispatcher"):
            return 403, "Authorization data is wrong!"
        return 404, ""

    def exec_node(self, script: str) -> str:
        request = json.loads(script.split("const REQUEST = ", 1)[1].split(";\n", 1)[0])
        op = request["op"]
        if op == "max_execution_id":
            rows = self.executions.get(request["workflowId"], [])
            return json.dumps({"max": max((r["id"] for r in rows), default=0)})
        if op == "executions_after":
            rows = self.executions.get(request["workflowId"], [])
            return json.dumps([r for r in rows if r["id"] > request["after"]])
        if op == "get_task":
            title = self.tasks.get(request["taskId"])
            return json.dumps({"status": 200 if title else 404, "title": title})
        if op == "delete_task":
            self.deleted.append(request["taskId"])
            return json.dumps({"status": self.delete_status})
        raise AssertionError(f"unexpected op {op}")


def _run(cluster: _Cluster, cm: MagicMock | None = None) -> bool:
    clock = _Clock()
    return run_n8n_probe(
        "staging",
        cm=cm or _cm(),
        post=cluster.post,
        exec_node=cluster.exec_node,
        clock=clock,
        sleep=clock.sleep,
    )


def test_every_probe_passes_against_a_fixed_cluster() -> None:
    cluster = _Cluster()
    assert _run(cluster) is True
    assert list(cluster.tasks) == cluster.deleted, "the created probe task must be deleted"
    urls = [u for u, _, _ in cluster.posts]
    assert f"https://{_DOMAIN}/webhook/multi-forge-sync" in urls
    assert f"https://{_DOMAIN}/webhook/slack-task-capture" in urls
    assert f"https://{_DOMAIN}/webhook/agent-dispatcher" in urls


def test_the_unsigned_probes_send_no_signature_and_no_auth() -> None:
    cluster = _Cluster()
    _run(cluster)
    slack = [h for u, _, h in cluster.posts if u.endswith("slack-task-capture")]
    agent = [h for u, _, h in cluster.posts if u.endswith("agent-dispatcher")]
    assert slack and not any(k.lower().startswith("x-slack") for h in slack for k in h)
    assert agent and not any(k.lower() == "authorization" for h in agent for k in h)


def test_a_signed_event_the_cluster_rejects_fails_and_names_the_secret_divergence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The project logger renders through Rich to stdout, not through `logging`,
    # so capsys is the surface; every assertion is on a single token Rich cannot wrap.
    cluster = _Cluster(signed_creates=False)
    assert _run(cluster) is False
    assert FORGE_SECRET_KEY in capsys.readouterr().out


def test_a_failed_cleanup_fails_the_probe_and_names_the_task(capsys: pytest.CaptureFixture[str]) -> None:
    cluster = _Cluster(delete_status=500)
    assert _run(cluster) is False
    assert f"task {cluster.deleted[0]}" in " ".join(capsys.readouterr().out.split())


def test_a_missing_forge_secret_fails_before_any_request() -> None:
    cluster = _Cluster()
    assert _run(cluster, cm=_cm(secret=None)) is False
    assert cluster.posts == []


def test_the_secret_never_reaches_the_log(capsys: pytest.CaptureFixture[str]) -> None:
    cluster = _Cluster(signed_creates=False)
    _run(cluster)
    assert _SECRET not in capsys.readouterr().out


def test_the_1712_defect_open_gates_fails_the_probe(capsys: pytest.CaptureFixture[str]) -> None:
    """Gates that route unsigned requests to TRUE, as before the fix, must not pass."""
    cluster = _Cluster(open_gates=True)
    assert _run(cluster) is False
    out = " ".join(capsys.readouterr().out.split())
    assert "Find Task for Issue" in out
    assert "Lookup Vikunja Projects" in out


def test_the_in_pod_script_redacts_credentials_from_error_messages() -> None:
    """The failing node's message leaves the pod, and an HTTP error can quote the request."""
    import subprocess

    from toolkit.features.n8n_probe import pod_script

    line = next(ln for ln in pod_script({"op": "noop"}).splitlines() if ln.startswith("const redact"))
    message = 'Find Task: HTTP 401 Authorization: Bearer abc.def-123 token=xyz9 {"key":"k1"}'
    out = subprocess.run(
        ["node", "-e", f"{line}\nprocess.stdout.write(redact({message!r}))"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    for leaked in ("abc.def-123", "xyz9", "k1"):
        assert leaked not in out
    assert "HTTP 401" in out
