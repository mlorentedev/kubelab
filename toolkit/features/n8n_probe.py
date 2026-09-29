"""Probe the public n8n webhooks end to end (APP-CONFIG-015 AC4/AC5, #1712).

Unit tests run each Code node on the item n8n really produces, but they cannot
show what the deployed workflow does: which branch an IF took, or whether a write
node ran. #1712 was exactly that gap. Four IF gates always passed, and every test
was green. So this drives the real entry points and judges n8n's own record of
each execution.

Probes, in order:

1. **Signed forge `opened` issue** (AC4): signed with the SOPS forge secret, it
   must answer 201 and create a task, which is read back from Vikunja and then
   deleted. The key is `PROBE-<epoch>`, so a rerun never collides with a task an
   earlier failed cleanup left behind. In prod this also posts one "Task Created"
   message to the operator channel.
2. **Signed forge merge** (APP-CONFIG-016 AC6, #1871): a task is created as in
   probe 1, then a signed `pull_request` `closed` + `merged` event with the same
   key must answer 200 `done`, and Vikunja must show the task done, its
   description unchanged and one comment naming the PR. The task is deleted
   whatever happened. In prod this also posts one "Forge Sync" notice.
3. **Unsigned forge event**, and **forge event under a wrong secret** (AC5). Each
   must answer 200 with `status: ignored` (#1659).
4. **Unsigned Slack command** (AC5). Slack is acknowledged before the gate, so
   the HTTP status says nothing here and only the execution does.
5. **Unauthenticated agent-dispatcher call** (AC5): n8n's Header Auth must refuse
   it with 403 before any execution exists.

"Stops at its gate" is judged from the execution, with two checks. The gate sent
nothing to its TRUE output. And no `httpRequest` node ran; that set is read from
the committed workflow, so it covers every Vikunja, Apprise and Slack call the
workflow makes, now or later.

Each execution is found by id, not by recency: the probe records the workflow's
highest execution id before it POSTs, and then needs exactly one newer one. In
prod, where real deliveries arrive, two newer ones fail the probe as ambiguous
instead of judging the wrong execution.

Nothing secret leaves its place. The forge secret is read from SOPS into memory
and only its HMAC goes on the wire. Executions are read inside the n8n pod, and
only node names and item counts come out. Vikunja is read and cleaned from the
pod too, with the `VIKUNJA_API_TOKEN` the workflow itself uses.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from toolkit.core.logging import logger
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.k8s_kubeconfig import output_path
from toolkit.features.notify_smoke import resolve_service_domain

FORGE_SECRET_KEY = "apps.services.automation.n8n.forge_webhook_secret"

_WORKFLOW_DIR = Path("infra") / "n8n" / "workflows"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_FORGE = "multi-forge-sync.json"
_SLACK = "slack-task-capture.json"
_AGENT = "agent-dispatcher.json"
_FORGE_GATE = "Has Task Key & Valid Sig?"
_SLACK_GATE = "Is Slack Valid?"
_CREATE_NODE = "Create Task from Issue"
_PR_WRITE_NODES = ("Update Vikunja Task State", "Append PR URL Comment")

_NAMESPACE = "kubelab"
_DEPLOYMENT = "deploy/n8n"
_N8N_ROOT = "/usr/local/lib/node_modules/n8n"
_NON_TERMINAL = {"new", "running", "waiting"}
_HTTP_TIMEOUT = 15
_EXEC_TIMEOUT = 60
_REFUSAL_SETTLE_S = 3.0

# (url, body, headers) -> (status, response text)
PostFn = Callable[[str, bytes, dict[str, str]], tuple[int, str]]
# node script on stdin, run in the n8n pod -> the JSON line it printed
ExecFn = Callable[[str], str]


@dataclass(frozen=True)
class ExecutionSummary:
    """What the probe needs from one n8n execution, and nothing that could carry data."""

    id: int
    status: str
    outputs: dict[str, list[int]]
    """Node name -> item count on each output of its first run. A key means the node ran."""
    error: str | None = None
    """For a failed execution: the failing node and its error message, credentials redacted in the pod."""


# ── Pure helpers ──────────────────────────────────────────────────────────────


def load_workflow(name: str, project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or _REPO_ROOT
    return json.loads((root / _WORKFLOW_DIR / name).read_text(encoding="utf-8"))


def webhook_path(workflow: dict[str, Any]) -> str:
    node = next(n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.webhook")
    return f"/webhook/{node['parameters']['path']}"


def http_request_nodes(workflow: dict[str, Any]) -> set[str]:
    return {n["name"] for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.httpRequest"}


def build_issue_event(task_key: str) -> dict[str, Any]:
    """A Gitea `issues` `opened` payload that `Parse Forge Event` reads as a create candidate."""
    return {
        "action": "opened",
        "number": 0,
        "issue": {
            "number": 0,
            "title": f"{task_key}: n8n webhook probe",
            "html_url": "https://forge.invalid/kubelab/n8n-probe/issues/0",
        },
        "repository": {
            "name": "n8n-probe",
            "full_name": "kubelab/n8n-probe",
            "owner": {"login": "kubelab"},
        },
    }


def build_pr_merge_event(task_key: str) -> dict[str, Any]:
    """A Gitea `pull_request` `closed` + `merged` payload: the one PR event that marks a task done."""
    return {
        "action": "closed",
        "number": 0,
        "pull_request": {
            "number": 0,
            "title": f"{task_key}: n8n webhook probe",
            "html_url": f"https://forge.invalid/kubelab/n8n-probe/pulls/{task_key}",
            "merged": True,
            "head": {"ref": "probe/n8n-webhook"},
        },
        "repository": {
            "name": "n8n-probe",
            "full_name": "kubelab/n8n-probe",
            "owner": {"login": "kubelab"},
        },
    }


def forge_headers(raw: bytes, secret: str | None, *, event: str = "issues") -> dict[str, str]:
    """Gitea's delivery headers; signed over `raw` exactly when `secret` is given."""
    headers = {"Content-Type": "application/json", "X-Gitea-Event": event}
    if secret is not None:
        headers["X-Gitea-Signature"] = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return headers


def judge_gate_stop(summary: ExecutionSummary, gate: str, http_nodes: set[str]) -> list[str]:
    """Why `summary` is NOT an execution that stopped at `gate`; empty when it is."""
    errors = []
    if summary.status != "success":
        detail = f": {summary.error}" if summary.error else ""
        errors.append(f"execution {summary.id} ended with status {summary.status}, not success{detail}")
    outputs = summary.outputs.get(gate)
    if outputs is None:
        errors.append(f"gate {gate!r} never ran in execution {summary.id}")
    else:
        to_true = outputs[0] if outputs else 0
        to_false = outputs[1] if len(outputs) > 1 else 0
        if to_true:
            errors.append(f"gate {gate!r} sent {to_true} item(s) to TRUE")
        if not to_false:
            errors.append(f"gate {gate!r} sent nothing to FALSE")
    ran = sorted(n for n in summary.outputs if n in http_nodes)
    if ran:
        errors.append("HTTP nodes ran past the gate: " + ", ".join(ran))
    return errors


def wait_for_execution(
    fetch: Callable[[], list[dict[str, Any]]],
    *,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    timeout: float,
    interval: float = 1.0,
) -> tuple[ExecutionSummary | None, str | None]:
    """Poll `fetch` until exactly one new execution has finished.

    Returns (summary, None), or (None, reason). More than one new execution is
    ambiguous and never guessed between.
    """
    deadline = clock() + timeout
    rows: list[dict[str, Any]] = []
    while True:
        rows = fetch()
        if len(rows) > 1:
            ids = ", ".join(str(r["id"]) for r in rows)
            return None, f"ambiguous: {len(rows)} new executions ({ids}); another delivery arrived, re-run"
        if len(rows) == 1 and rows[0]["status"] not in _NON_TERMINAL:
            row = rows[0]
            summary = ExecutionSummary(
                id=int(row["id"]), status=str(row["status"]), outputs=row["outputs"], error=row.get("error")
            )
            return summary, None
        if clock() >= deadline:
            break
        sleep(interval)
    if rows:
        return None, f"execution {rows[0]['id']} still {rows[0]['status']} after {timeout:.0f}s"
    return None, (
        f"no execution recorded within {timeout:.0f}s; check that n8n saves executions "
        "(EXECUTIONS_DATA_SAVE_ON_SUCCESS / EXECUTIONS_DATA_SAVE_ON_ERROR)"
    )


# ── In-pod script ─────────────────────────────────────────────────────────────

# One script, parameterised by REQUEST. The first line is the only part that
# varies, and it is JSON, so nothing the probe sends can change the code that runs.
_POD_SCRIPT = """
const DB = '/home/node/.n8n/database.sqlite';
const out = (v) => process.stdout.write(JSON.stringify(v) + '\\n');

// Only node names, item counts and the failing node's message leave the pod. An
// HTTP node's error can quote the request, so anything shaped like a credential
// is cut before it is printed.
const redact = (s) => String(s).replace(/(Bearer|Basic|token|secret|key)(["'=: ]+)[^\\s"',}]+/gi, '$1$2[REDACTED]');

function summarise(data) {
  if (!data) return { outputs: {}, error: null };
  const { parse } = require('flatted');
  const result = (parse(data) || {}).resultData || {};
  const outputs = {};
  for (const [name, runs] of Object.entries(result.runData || {})) {
    const main = (runs[0] && runs[0].data && runs[0].data.main) || [];
    outputs[name] = main.map((o) => (Array.isArray(o) ? o.length : 0));
  }
  const e = result.error;
  const code = e && e.httpCode ? 'HTTP ' + e.httpCode + ' ' : '';
  const error = e ? redact(`${result.lastNodeExecuted || '?'}: ${code}${e.message || ''}`).slice(0, 300) : null;
  return { outputs, error };
}

const TASKS = 'http://vikunja:3456/api/v1/tasks/';
const AUTH = { Authorization: 'Bearer ' + (process.env.VIKUNJA_API_TOKEN || '') };

// The description leaves the pod only as a digest: the probe compares it before
// and after a write, and has no use for what it says.
async function getTask(taskId) {
  const res = await fetch(TASKS + Number(taskId), { headers: AUTH });
  if (!res.ok) return { status: res.status, title: null, done: null, descriptionSha256: null };
  const task = await res.json();
  const digest = require('crypto').createHash('sha256').update(String(task.description ?? '')).digest('hex');
  return {
    status: res.status,
    title: task.title == null ? null : String(task.title),
    done: Boolean(task.done),
    descriptionSha256: digest,
  };
}

async function deleteTask(taskId) {
  return { status: (await fetch(TASKS + Number(taskId), { method: 'DELETE', headers: AUTH })).status };
}

async function countComments(taskId, contains) {
  const res = await fetch(TASKS + Number(taskId) + '/comments', { headers: AUTH });
  if (!res.ok) return { status: res.status, count: 0 };
  const comments = await res.json();
  const count = (Array.isArray(comments) ? comments : [])
    .filter((c) => String(c.comment || '').includes(contains)).length;
  return { status: res.status, count };
}

async function findTasks(key) {
  const res = await fetch('http://vikunja:3456/api/v1/tasks?s=' + encodeURIComponent(key), {
    headers: { Authorization: 'Bearer ' + (process.env.VIKUNJA_API_TOKEN || '') },
  });
  if (!res.ok) return { status: res.status, ids: [] };
  const tasks = await res.json();
  const ids = (Array.isArray(tasks) ? tasks : [])
    .filter((t) => String(t.title || '').startsWith(key + ':'))
    .map((t) => t.id);
  return { status: res.status, ids };
}

async function main() {
  if (REQUEST.op === 'find_tasks') return out(await findTasks(REQUEST.key));
  if (REQUEST.op === 'get_task') return out(await getTask(REQUEST.taskId));
  if (REQUEST.op === 'delete_task') return out(await deleteTask(REQUEST.taskId));
  if (REQUEST.op === 'count_comments') return out(await countComments(REQUEST.taskId, REQUEST.contains));
  const sqlite3 = require('sqlite3');
  const db = new sqlite3.Database(DB, sqlite3.OPEN_READONLY);
  const all = (sql, params) => new Promise((ok, ko) => db.all(sql, params, (e, rows) => (e ? ko(e) : ok(rows))));
  if (REQUEST.op === 'max_execution_id') {
    const [row] = await all(
      'SELECT COALESCE(MAX(id), 0) AS max FROM execution_entity WHERE workflowId = ?', [REQUEST.workflowId]);
    return out({ max: Number(row.max) });
  }
  if (REQUEST.op === 'executions_after') {
    const rows = await all(
      'SELECT e.id, e.status, d.data FROM execution_entity e '
      + 'LEFT JOIN execution_data d ON d.executionId = e.id '
      + 'WHERE e.workflowId = ? AND e.id > ? ORDER BY e.id',
      [REQUEST.workflowId, REQUEST.after]);
    return out(rows.map((r) => ({ id: Number(r.id), status: r.status, ...summarise(r.data) })));
  }
  throw new Error('unknown op ' + REQUEST.op);
}

main().catch((e) => { process.stderr.write(String((e && e.message) || e) + '\\n'); process.exit(1); });
"""


def pod_script(request: dict[str, Any]) -> str:
    return f"const REQUEST = {json.dumps(request)};\n{_POD_SCRIPT}"


# ── Public API ────────────────────────────────────────────────────────────────


def run_n8n_probe(
    env: str,
    project_root: Path | None = None,
    *,
    cm: ConfigurationManager | None = None,
    post: PostFn | None = None,
    exec_node: ExecFn | None = None,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    verify_tls: bool | None = None,
    timeout: float = 60.0,
) -> bool:
    """Run every probe against `env`. Returns True iff all of them held."""
    logger.section(f"n8n webhook probe — {env.upper()}")
    cm = cm or ConfigurationManager(env, project_root)

    secret = cm.get_secret_by_path(FORGE_SECRET_KEY)
    if not secret:
        logger.error(f"Missing SOPS value at '{FORGE_SECRET_KEY}': cannot sign the forge probe")
        return False
    try:
        domain = resolve_service_domain(cm.get_merged_config(), "n8n")
    except ValueError as exc:
        logger.error(str(exc))
        return False

    probe = _Probe(
        env=env,
        base_url=f"https://{domain}",
        post=post or _default_post(env == "prod" if verify_tls is None else verify_tls),
        exec_node=exec_node or _default_exec(env),
        clock=clock,
        sleep=sleep,
        timeout=timeout,
        project_root=project_root,
    )
    checks: list[tuple[str, Callable[[], bool]]] = [
        ("signed forge", lambda: probe.signed_forge_creates_a_task(secret)),
        ("signed forge merge", lambda: probe.signed_pr_merge_closes_its_task(secret)),
        ("unsigned forge", lambda: probe.forge_stops_at_its_gate("unsigned forge event", None)),
        (
            "wrong-secret forge",
            lambda: probe.forge_stops_at_its_gate("forge event under a wrong secret", secrets.token_hex(16)),
        ),
        ("unsigned Slack", probe.unsigned_slack_stops_at_its_gate),
        ("agent-dispatcher", probe.unauthenticated_agent_dispatch_is_refused),
    ]
    results = [_guarded(name, check) for name, check in checks]
    if all(results):
        logger.success("n8n webhook probe passed")
        return True
    logger.error("n8n webhook probe FAILED; see the probes above")
    return False


# ── Internals ─────────────────────────────────────────────────────────────────


@dataclass
class _Probe:
    env: str
    base_url: str
    post: PostFn
    exec_node: ExecFn
    clock: Callable[[], float]
    sleep: Callable[[float], None]
    timeout: float
    project_root: Path | None

    def _workflow(self, name: str) -> dict[str, Any]:
        return load_workflow(name, self.project_root)

    def _pod(self, request: dict[str, Any]) -> Any:
        return json.loads(self.exec_node(pod_script(request)))

    def _max_id(self, workflow_id: str) -> int:
        return int(self._pod({"op": "max_execution_id", "workflowId": workflow_id})["max"])

    def _await_one(self, workflow_id: str, before: int) -> tuple[ExecutionSummary | None, str | None]:
        return wait_for_execution(
            lambda: self._pod({"op": "executions_after", "workflowId": workflow_id, "after": before}),
            clock=self.clock,
            sleep=self.sleep,
            timeout=self.timeout,
        )

    def _send(self, label: str, path: str, body: bytes, headers: dict[str, str]) -> tuple[int, str] | None:
        try:
            return self.post(self.base_url + path, body, headers)
        except Exception as exc:  # network, TLS, timeout: a failed probe, not a crash
            logger.error(f"  {label}: request failed: {exc}")
            return None

    def _verdict(self, label: str, errors: list[str]) -> bool:
        if errors:
            for error in errors:
                logger.error(f"  {label}: {error}")
            return False
        logger.info(f"  {label}: ok")
        return True

    def signed_forge_creates_a_task(self, secret: str) -> bool:
        label = "signed forge opened issue (AC4)"
        task_key = f"PROBE-{int(self.clock())}"
        task_id, before, errors = self._create_task(label, secret, task_key)
        if task_id is None:
            return self._verdict(label, errors)
        try:
            errors += self._confirm_created(label, before, task_id, task_key)[1]
        finally:
            errors += self._delete(task_id)
        return self._verdict(label, errors)

    def signed_pr_merge_closes_its_task(self, secret: str) -> bool:
        """A merged PR marks its task done, keeps the task's content, and says so in a comment.

        The description is compared by digest because Vikunja's `POST /tasks/{id}`
        is a full update: a write that sent `{done: true}` alone would pass a
        check of `done` and still erase the task (#1871).
        """
        label = "signed forge merged PR (APP-CONFIG-016 AC6)"
        # Its own AREA, so its key never equals the issue probe's in the same second.
        task_key = f"PROBE-MERGE-{int(self.clock())}"
        task_id, before, errors = self._create_task(label, secret, task_key)
        if task_id is None:
            return self._verdict(label, errors)
        try:
            created, errors = self._confirm_created(label, before, task_id, task_key)
            if created is not None:
                errors += self._merge_lands(label, secret, task_key, task_id, created)
        finally:
            errors += self._delete(task_id)
        return self._verdict(label, errors)

    def _create_task(self, label: str, secret: str, task_key: str) -> tuple[int | None, int, list[str]]:
        """POST a signed `opened` issue. Returns (task id, execution floor, errors).

        A task id is returned as soon as the 201 names one, so the caller's
        `finally` owns its deletion before anything else can fail.
        """
        workflow = self._workflow(_FORGE)
        raw = json.dumps(build_issue_event(task_key), indent=2).encode()
        before = self._max_id(workflow["id"])
        sent = self._send(label, webhook_path(workflow), raw, forge_headers(raw, secret))
        if sent is None:
            return None, before, ["no response to the signed issue event"]
        status, text = sent
        if status != 201:
            return None, before, self._why_not_created(workflow["id"], before, status, text)
        task_id = _task_id(text)
        if task_id is None:
            missing = [f"HTTP 201 without a taskId in the response: {text[:200]}"]
            return None, before, missing + self._sweep(label, task_key)
        return task_id, before, []

    def _confirm_created(
        self, label: str, before: int, task_id: int, task_key: str
    ) -> tuple[dict[str, Any] | None, list[str]]:
        """The create execution ran its create node, and Vikunja holds the task. Returns (task, errors)."""
        errors: list[str] = []
        summary, error = self._await_one(self._workflow(_FORGE)["id"], before)
        if error or summary is None:
            errors.append(error or "no execution")
        elif summary.status != "success" or _CREATE_NODE not in summary.outputs:
            errors.append(f"execution {summary.id} ({summary.status}) did not run {_CREATE_NODE!r}")
        task = self._pod({"op": "get_task", "taskId": task_id})
        if task["status"] != 200 or not str(task["title"] or "").startswith(task_key):
            errors.append(f"task {task_id} read back from Vikunja as HTTP {task['status']}, title {task['title']!r}")
            return None, errors
        logger.info(f"  {label}: task {task_id} {task['title']!r} read back from Vikunja")
        return task, errors

    def _merge_lands(self, label: str, secret: str, task_key: str, task_id: int, created: dict[str, Any]) -> list[str]:
        """Send the signed merge for `task_key`; why the task does not show it, or nothing."""
        workflow = self._workflow(_FORGE)
        event = build_pr_merge_event(task_key)
        raw = json.dumps(event, indent=2).encode()
        before = self._max_id(workflow["id"])
        sent = self._send(label, webhook_path(workflow), raw, forge_headers(raw, secret, event="pull_request"))
        if sent is None:
            return ["no response to the signed merged PR event"]
        status, text = sent
        summary, error = self._await_one(workflow["id"], before)
        answer = _json_object(text)
        errors: list[str] = []
        if status != 200 or answer.get("status") != "done" or answer.get("taskId") != task_id:
            errors.append(f"merged PR answered HTTP {status}, expected 200 done for task {task_id}: {text[:200]}")
        if error or summary is None:
            errors.append(error or "no execution")
        else:
            if summary.status != "success":
                detail = f": {summary.error}" if summary.error else ""
                errors.append(f"merged PR execution {summary.id} ended {summary.status}{detail}")
            skipped = [n for n in _PR_WRITE_NODES if n not in summary.outputs]
            if skipped:
                errors.append(f"merged PR execution {summary.id} never ran {', '.join(skipped)}")
        task = self._pod({"op": "get_task", "taskId": task_id})
        if task["done"] is not True:
            errors.append(f"merged PR left task {task_id} with done={task['done']}")
        if task["descriptionSha256"] != created["descriptionSha256"]:
            errors.append(f"merged PR changed task {task_id}'s description: the write is not a whole-task update")
        pr_url = event["pull_request"]["html_url"]
        comments = self._pod({"op": "count_comments", "taskId": task_id, "contains": pr_url})
        if comments["status"] != 200 or comments["count"] != 1:
            errors.append(
                f"merged PR left {comments['count']} comment(s) naming it on task {task_id} "
                f"(HTTP {comments['status']}), expected 1"
            )
        if not errors:
            logger.info(f"  {label}: task {task_id} done, description intact, PR comment present")
        return errors

    def _delete(self, task_id: int) -> list[str]:
        deleted = self._pod({"op": "delete_task", "taskId": task_id})["status"]
        if 200 <= int(deleted) < 300:
            return []
        return [f"cleanup failed (HTTP {deleted}): delete task {task_id} in Vikunja by hand"]

    def _sweep(self, label: str, task_key: str) -> list[str]:
        """Delete what a 201 created when the response did not say which task it was.

        The key carries the probe's own timestamp, so matching titles by it can
        only find this run's task, never a real one.
        """
        found = self._pod({"op": "find_tasks", "key": task_key})
        if found["status"] != 200:
            return [f"cleanup search failed (HTTP {found['status']}): delete tasks titled {task_key!r} by hand"]
        errors: list[str] = []
        for task_id in found["ids"]:
            failed = self._delete(task_id)
            if not failed:
                logger.info(f"  {label}: deleted task {task_id}, found by its key")
            errors += failed
        return errors

    def _why_not_created(self, workflow_id: str, before: int, status: int, text: str) -> list[str]:
        """Explain a signed event that created nothing, from the path its execution took.

        The response body carries only the workflow's own status fields (taskKey,
        reason), never request data, so it is safe to show.
        """
        errors = [f"HTTP {status}, expected 201 (task created); response: {text[:200]}"]
        summary, error = self._await_one(workflow_id, before)
        if error or summary is None:
            return [*errors, error or "no execution"]
        errors.append(f"execution {summary.id} ({summary.status}) ran: {', '.join(summary.outputs)}")
        if summary.error:
            errors.append(f"execution {summary.id} failed in {summary.error}")
        gate = summary.outputs.get(_FORGE_GATE, [])
        if len(gate) > 1 and gate[1] and not gate[0]:
            errors.append(
                f"the signature gate rejected a correctly signed event: the SOPS value at {FORGE_SECRET_KEY} "
                f"differs from the pod's FORGE_WEBHOOK_SECRET (make apply-secrets ENV={self.env})"
            )
        return errors

    def forge_stops_at_its_gate(self, label: str, secret: str | None) -> bool:
        label = f"{label} (AC5)"
        workflow = self._workflow(_FORGE)
        raw = json.dumps(build_issue_event(f"PROBE-{int(self.clock())}"), indent=2).encode()
        return self._stops_at_gate(label, workflow, _FORGE_GATE, raw, forge_headers(raw, secret), answer="ignored")

    def unsigned_slack_stops_at_its_gate(self) -> bool:
        workflow = self._workflow(_SLACK)
        body = urlencode(
            {
                "token": "n8n-probe",
                "command": "/task",
                "text": "create n8n webhook probe",
                "user_name": "n8n-probe",
                "response_url": "https://slack.invalid/n8n-probe",
            }
        ).encode()
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        return self._stops_at_gate("unsigned Slack command (AC5)", workflow, _SLACK_GATE, body, headers)

    def _stops_at_gate(
        self,
        label: str,
        workflow: dict[str, Any],
        gate: str,
        body: bytes,
        headers: dict[str, str],
        answer: str | None = None,
    ) -> bool:
        """`answer`, when given, is the `status` the 200 body must carry (#1659)."""
        before = self._max_id(workflow["id"])
        sent = self._send(label, webhook_path(workflow), body, headers)
        if sent is None:
            return False
        status, text = sent
        if status != 200:
            return self._verdict(label, [f"HTTP {status}, expected 200"])
        if answer is not None and _json_object(text).get("status") != answer:
            return self._verdict(label, [f"HTTP 200 without status {answer!r} in the body: {text[:200]}"])
        summary, error = self._await_one(workflow["id"], before)
        if error or summary is None:
            return self._verdict(label, [error or "no execution"])
        errors = judge_gate_stop(summary, gate, http_request_nodes(workflow))
        if not errors:
            logger.info(f"  {label}: execution {summary.id} stopped at {gate!r}")
        return self._verdict(label, errors)

    def unauthenticated_agent_dispatch_is_refused(self) -> bool:
        label = "unauthenticated agent-dispatcher call (AC5)"
        workflow = self._workflow(_AGENT)
        before = self._max_id(workflow["id"])
        sent = self._send(label, webhook_path(workflow), b"{}", {"Content-Type": "application/json"})
        if sent is None:
            return False
        status, _ = sent
        errors = [] if status == 403 else [f"HTTP {status}, expected 403 from n8n Header Auth"]
        self.sleep(_REFUSAL_SETTLE_S)
        started = self._pod({"op": "executions_after", "workflowId": workflow["id"], "after": before})
        if started:
            errors.append(f"{len(started)} execution(s) started for a refused request")
        return self._verdict(label, errors)


def _guarded(name: str, check: Callable[[], bool]) -> bool:
    """Run one probe; an in-pod script failure fails that probe instead of aborting the rest."""
    try:
        return check()
    except RuntimeError as exc:
        logger.error(f"  {name}: {exc}")
        return False


def _json_object(text: str) -> dict[str, Any]:
    """A response body as a JSON object; anything else reads as empty."""
    try:
        value = json.loads(text)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _task_id(text: str) -> int | None:
    try:
        value = json.loads(text).get("taskId")
    except (ValueError, AttributeError):
        return None
    return int(value) if isinstance(value, int) or (isinstance(value, str) and value.isdigit()) else None


def _default_post(verify_tls: bool) -> PostFn:
    """Real HTTP poster (lazy import so tests never need `requests`)."""
    import requests

    def post(url: str, body: bytes, headers: dict[str, str]) -> tuple[int, str]:
        resp = requests.post(url, data=body, headers=headers, timeout=_HTTP_TIMEOUT, verify=verify_tls)
        return int(resp.status_code), resp.text[:500]

    return post


def _default_exec(env: str) -> ExecFn:
    """Run a node script in the n8n pod (stdin, never argv) and return its last stdout line."""
    kubeconfig = str(output_path(env))

    def run(script: str) -> str:
        proc = subprocess.run(
            [
                "kubectl",
                "exec",
                "-i",
                "-n",
                _NAMESPACE,
                _DEPLOYMENT,
                "--kubeconfig",
                kubeconfig,
                "--",
                "sh",
                "-c",
                f"cd {_N8N_ROOT} && node -",
            ],
            input=script,
            capture_output=True,
            text=True,
            timeout=_EXEC_TIMEOUT,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"in-pod script failed: {proc.stderr.strip()[-300:]}")
        lines = proc.stdout.strip().splitlines()
        if not lines:
            raise RuntimeError("in-pod script printed nothing")
        return lines[-1]

    return run
