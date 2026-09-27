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
2. **Unsigned forge event**, and **forge event under a wrong secret** (AC5).
3. **Unsigned Slack command** (AC5). Slack is acknowledged before the gate, so
   the HTTP status says nothing here and only the execution does.
4. **Unauthenticated agent-dispatcher call** (AC5): n8n's Header Auth must refuse
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


def forge_headers(raw: bytes, secret: str | None) -> dict[str, str]:
    """Gitea's delivery headers; signed over `raw` exactly when `secret` is given."""
    headers = {"Content-Type": "application/json", "X-Gitea-Event": "issues"}
    if secret is not None:
        headers["X-Gitea-Signature"] = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return headers


def judge_gate_stop(summary: ExecutionSummary, gate: str, http_nodes: set[str]) -> list[str]:
    """Why `summary` is NOT an execution that stopped at `gate`; empty when it is."""
    errors = []
    if summary.status != "success":
        errors.append(f"execution {summary.id} ended with status {summary.status}, not success")
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
            return ExecutionSummary(id=int(row["id"]), status=str(row["status"]), outputs=row["outputs"]), None
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

function summarise(data) {
  if (!data) return {};
  const { parse } = require('flatted');
  const runData = ((parse(data) || {}).resultData || {}).runData || {};
  const outputs = {};
  for (const [name, runs] of Object.entries(runData)) {
    const main = (runs[0] && runs[0].data && runs[0].data.main) || [];
    outputs[name] = main.map((o) => (Array.isArray(o) ? o.length : 0));
  }
  return outputs;
}

async function vikunja(method, taskId) {
  const res = await fetch('http://vikunja:3456/api/v1/tasks/' + Number(taskId), {
    method,
    headers: { Authorization: 'Bearer ' + (process.env.VIKUNJA_API_TOKEN || '') },
  });
  if (method === 'DELETE' || !res.ok) return { status: res.status, title: null };
  const task = await res.json();
  return { status: res.status, title: task.title == null ? null : String(task.title) };
}

async function main() {
  if (REQUEST.op === 'get_task') return out(await vikunja('GET', REQUEST.taskId));
  if (REQUEST.op === 'delete_task') return out({ status: (await vikunja('DELETE', REQUEST.taskId)).status });
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
    return out(rows.map((r) => ({ id: Number(r.id), status: r.status, outputs: summarise(r.data) })));
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
        workflow = self._workflow(_FORGE)
        task_key = f"PROBE-{int(self.clock())}"
        raw = json.dumps(build_issue_event(task_key), indent=2).encode()
        before = self._max_id(workflow["id"])
        sent = self._send(label, webhook_path(workflow), raw, forge_headers(raw, secret))
        if sent is None:
            return False
        status, text = sent
        if status != 201:
            return self._verdict(
                label,
                [
                    f"HTTP {status}, expected 201 (task created). If the gate rejected the signature, the "
                    f"SOPS value at {FORGE_SECRET_KEY} differs from the pod's FORGE_WEBHOOK_SECRET: "
                    f"make apply-secrets ENV={self.env}"
                ],
            )
        task_id = _task_id(text)
        if task_id is None:
            return self._verdict(label, [f"HTTP 201 without a taskId in the response: {text[:200]}"])
        errors: list[str] = []
        try:
            summary, error = self._await_one(workflow["id"], before)
            if error or summary is None:
                errors.append(error or "no execution")
            elif summary.status != "success" or _CREATE_NODE not in summary.outputs:
                errors.append(f"execution {summary.id} ({summary.status}) did not run {_CREATE_NODE!r}")
            task = self._pod({"op": "get_task", "taskId": task_id})
            if task["status"] != 200 or not str(task["title"] or "").startswith(task_key):
                errors.append(
                    f"task {task_id} read back from Vikunja as HTTP {task['status']}, title {task['title']!r}"
                )
            else:
                logger.info(f"  {label}: task {task_id} {task['title']!r} read back from Vikunja")
        finally:
            deleted = self._pod({"op": "delete_task", "taskId": task_id})["status"]
        if not 200 <= int(deleted) < 300:
            errors.append(f"cleanup failed (HTTP {deleted}): delete task {task_id} in Vikunja by hand")
        return self._verdict(label, errors)

    def forge_stops_at_its_gate(self, label: str, secret: str | None) -> bool:
        label = f"{label} (AC5)"
        workflow = self._workflow(_FORGE)
        raw = json.dumps(build_issue_event(f"PROBE-{int(self.clock())}"), indent=2).encode()
        return self._stops_at_gate(label, workflow, _FORGE_GATE, raw, forge_headers(raw, secret))

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
        self, label: str, workflow: dict[str, Any], gate: str, body: bytes, headers: dict[str, str]
    ) -> bool:
        before = self._max_id(workflow["id"])
        sent = self._send(label, webhook_path(workflow), body, headers)
        if sent is None:
            return False
        status, _ = sent
        if status != 200:
            return self._verdict(label, [f"HTTP {status}, expected 200"])
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
