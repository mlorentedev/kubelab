"""Measure the reviewer identity's minimal grant against a disposable local Gitea.

Run:  dotf secrets run --only NAN_API_KEY -- .venv/bin/python specs/TOOL-080-forge-pr-reviewer/scope-lab.py

Knobs, for comparing a configuration against the one the spec first proposed:
  LAB_HOOK_EVENTS       JSON list for the webhook's `events` (default ["pull_request"])
  LAB_FINAL_UPDATE      value of PR_REVIEWER__FINAL_UPDATE_MESSAGE (default "true", upstream's)
  LAB_SKIP_SCOPES=1     skip the per-scope probe table

Nothing here touches the prod forge. It starts gitea/gitea:1.25.5 (the prod pin) and
pragent/pr-agent:0.45.0-gitea_app on a private Docker network, reproduces the target
topology (public org, REQUIRE_SIGNIN_VIEW, reviewer in a read team, signed webhook), and
records:

1. the status of every call the reviewer could need, per token scope set;
2. that a prohibit_login=true account's token is refused by the API;
3. every API call the webhook server makes on `opened` and on a push, with its status,
   read back from Gitea's access log;
4. that the review is one comment edited in place, and that the PR's title and body stay
   as the author wrote them;
5. that unsigned and wrongly signed deliveries are refused.

Every credential is generated here and lives only in this process and the containers'
environment. Docker receives secret values by name (`-e NAME`), never in argv, and any
container log line printed is redacted first. Everything is removed on exit.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import time
from typing import Any

import requests

NET, GITEA, AGENT = "tool080-lab", "tool080-gitea", "tool080-pragent"
GITEA_IMAGE = "gitea/gitea:1.25.5"
AGENT_IMAGE = "pragent/pr-agent:0.45.0-gitea_app"
API = "http://127.0.0.1:3999/api/v1"
AGENT_LOCAL = "http://127.0.0.1:3998/api/v1/gitea_webhooks"
INTERNAL = f"http://{GITEA}:3000"
REPO = "personal/resume"
SCOPE_SETS = {
    "issue": ["write:issue"],
    "issue+repo": ["write:issue", "read:repository"],
    "issue+repo+user": ["write:issue", "read:repository", "read:user"],
}
SECRET_VALUES: list[str] = []


def redact(text: str) -> str:
    for value in SECRET_VALUES:
        if value:
            text = text.replace(value, "<redacted>")
    return text


def docker(*args: str, env: dict[str, str] | None = None, check: bool = True) -> str:
    full_env = {**os.environ, **(env or {})}
    proc = subprocess.run(["docker", *args], capture_output=True, text=True, env=full_env, check=False)
    if check and proc.returncode:
        sys.exit(f"docker {args[0]} failed: {redact(proc.stderr.strip())[:400]}")
    return proc.stdout


def call(method: str, path: str, auth: Any, **kw: Any) -> requests.Response:
    headers = kw.pop("headers", {})
    if isinstance(auth, str):
        headers["Authorization"] = f"token {auth}"
        auth = None
    return requests.request(method, API + path, auth=auth, headers=headers, timeout=60, **kw)


def ok(resp: requests.Response, what: str) -> Any:
    if resp.status_code >= 300:
        sys.exit(f"setup step failed: {what} -> {resp.status_code} {redact(resp.text)[:300]}")
    return resp.json() if resp.text else None


def wait_for(predicate: Any, timeout: int, step: float = 3.0) -> Any:
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    return None


def start_gitea() -> tuple[str, str]:
    docker("network", "create", NET, check=False)
    docker(
        "run",
        "-d",
        "--name",
        GITEA,
        "--network",
        NET,
        "-p",
        "127.0.0.1:3999:3000",
        "-e",
        "GITEA__security__INSTALL_LOCK=true",
        "-e",
        "GITEA__database__DB_TYPE=sqlite3",
        "-e",
        f"GITEA__server__ROOT_URL={INTERNAL}/",
        "-e",
        f"GITEA__server__DOMAIN={GITEA}",
        "-e",
        "GITEA__service__REQUIRE_SIGNIN_VIEW=true",
        "-e",
        "GITEA__service__DISABLE_REGISTRATION=true",
        "-e",
        "GITEA__webhook__ALLOWED_HOST_LIST=*",
        "-e",
        "GITEA__log__logger_0X2E_access_0X2E_MODE=console",
        GITEA_IMAGE,
    )
    if not wait_for(lambda: _healthy(), 120):
        sys.exit("local gitea did not become healthy")
    out = docker(
        "exec",
        "-u",
        "git",
        GITEA,
        "gitea",
        "admin",
        "user",
        "create",
        "--admin",
        "--username",
        "labadmin",
        "--email",
        "labadmin@lab.invalid",
        "--random-password",
        "--must-change-password=false",
    )
    match = re.search(r"generated random password is '([^']+)'", out)
    if not match:
        sys.exit("could not read the generated admin password")
    SECRET_VALUES.append(match.group(1))
    return "labadmin", match.group(1)


def _healthy() -> bool:
    try:
        return requests.get("http://127.0.0.1:3999/api/healthz", timeout=5).status_code == 200
    except requests.RequestException:
        return False


def make_user(admin: Any, name: str, **extra: Any) -> str:
    password = secrets.token_urlsafe(24)
    SECRET_VALUES.append(password)
    ok(
        call(
            "POST",
            "/admin/users",
            admin,
            json={
                "username": name,
                "email": f"{name}@lab.invalid",
                "password": password,
                "must_change_password": False,
                **extra,
            },
        ),
        f"create user {name}",
    )
    return password


def mint(user: str, password: str, name: str, scopes: list[str]) -> str:
    body = ok(
        call("POST", f"/users/{user}/tokens", (user, password), json={"name": name, "scopes": scopes}), f"mint {name}"
    )
    SECRET_VALUES.append(body["sha1"])
    return body["sha1"]


def seed(admin: Any) -> dict[str, Any]:
    ok(call("POST", "/orgs", admin, json={"username": "personal", "visibility": "public"}), "org")
    ok(
        call(
            "POST",
            "/orgs/personal/repos",
            admin,
            json={
                "name": "resume",
                "auto_init": True,
                "default_branch": "main",
                "private": False,
            },
        ),
        "repo",
    )
    label = ok(
        call("POST", f"/repos/{REPO}/labels", admin, json={"name": "Review effort 1/5", "color": "#ededed"}), "label"
    )
    team = ok(
        call(
            "POST",
            "/orgs/personal/teams",
            admin,
            json={
                "name": "reviewers",
                "permission": "read",
                "includes_all_repositories": True,
                "units": ["repo.code", "repo.issues", "repo.pulls"],
                "units_map": {"repo.code": "read", "repo.issues": "read", "repo.pulls": "read"},
            },
        ),
        "read team",
    )
    return {"label_id": label["id"], "team_id": team["id"]}


def open_pr(admin: Any, branch: str, title: str, body: str) -> int:
    code = "def greet(name):\n    return 'hello ' + name\n"
    ok(
        call(
            "POST",
            f"/repos/{REPO}/contents/{branch.replace('/', '_')}.py",
            admin,
            json={
                "content": base64.b64encode(code.encode()).decode(),
                "message": f"feat: add {branch}",
                "branch": "main",
                "new_branch": branch,
            },
        ),
        f"branch {branch}",
    )
    pr = ok(
        call(
            "POST",
            f"/repos/{REPO}/pulls",
            admin,
            json={
                "head": branch,
                "base": "main",
                "title": title,
                "body": body,
            },
        ),
        f"pr {branch}",
    )
    return int(pr["number"])


def push_commit(admin: Any, branch: str) -> None:
    path = f"{branch.replace('/', '_')}.py"
    current = ok(call("GET", f"/repos/{REPO}/contents/{path}?ref={branch}", admin), "read file")
    code = "def greet(name):\n    if not name:\n        raise ValueError('empty')\n    return 'hello ' + name\n"
    ok(
        call(
            "PUT",
            f"/repos/{REPO}/contents/{path}",
            admin,
            json={
                "content": base64.b64encode(code.encode()).decode(),
                "sha": current["sha"],
                "message": "fix: reject empty names",
                "branch": branch,
            },
        ),
        "push",
    )


def probe_scopes(token: str, pr: int, label_id: int) -> dict[str, int]:
    rows: dict[str, int] = {}

    def rec(key: str, method: str, path: str, **kw: Any) -> requests.Response:
        resp = call(method, path, token, **kw)
        rows[key] = resp.status_code
        return resp

    rec("GET /user", "GET", "/user")
    rec("GET /repos/{r}", "GET", f"/repos/{REPO}")
    rec("GET pulls/{n}", "GET", f"/repos/{REPO}/pulls/{pr}")
    rec("GET pulls/{n}.diff", "GET", f"/repos/{REPO}/pulls/{pr}.diff")
    rec("GET pulls/{n}/files", "GET", f"/repos/{REPO}/pulls/{pr}/files")
    rec("GET pulls/{n}/commits", "GET", f"/repos/{REPO}/pulls/{pr}/commits")
    rec("GET languages", "GET", f"/repos/{REPO}/languages")
    rec("GET issues/{n}/comments", "GET", f"/repos/{REPO}/issues/{pr}/comments")
    created = rec(
        "POST issues/{n}/comments", "POST", f"/repos/{REPO}/issues/{pr}/comments", json={"body": "scope probe"}
    )
    if created.status_code == 201:
        cid = created.json()["id"]
        rec("PATCH own comment", "PATCH", f"/repos/{REPO}/issues/comments/{cid}", json={"body": "edited"})
        rec("POST comment reaction", "POST", f"/repos/{REPO}/issues/comments/{cid}/reactions", json={"content": "eyes"})
        rec("DELETE own comment", "DELETE", f"/repos/{REPO}/issues/comments/{cid}")
    review = rec(
        "POST pulls/{n}/reviews (COMMENT)",
        "POST",
        f"/repos/{REPO}/pulls/{pr}/reviews",
        json={"body": "scope probe review", "event": "COMMENT", "comments": []},
    )
    if review.status_code in (200, 201):
        rec("DELETE own review", "DELETE", f"/repos/{REPO}/pulls/{pr}/reviews/{review.json()['id']}")
    rec("GET issues/{n}/labels", "GET", f"/repos/{REPO}/issues/{pr}/labels")
    rec("POST repo labels", "POST", f"/repos/{REPO}/labels", json={"name": "probe", "color": "#000000"})
    rec("POST issues/{n}/labels", "POST", f"/repos/{REPO}/issues/{pr}/labels", json={"labels": [label_id]})
    rec("PATCH pulls/{n} (title)", "PATCH", f"/repos/{REPO}/pulls/{pr}", json={"title": "rewritten"})
    rec("GET contents (default branch)", "GET", f"/repos/{REPO}/contents/README.md")
    return rows


def start_agent(token: str, webhook_secret: str, nan_key: str) -> None:
    env = {
        "GITEA__PERSONAL_ACCESS_TOKEN": token,
        "GITEA__WEBHOOK_SECRET": webhook_secret,
        "OPENAI__KEY": nan_key,
    }
    docker(
        "run",
        "-d",
        "--name",
        AGENT,
        "--network",
        NET,
        "-p",
        "127.0.0.1:3998:3000",
        "-e",
        "GITEA__PERSONAL_ACCESS_TOKEN",
        "-e",
        "GITEA__WEBHOOK_SECRET",
        "-e",
        "OPENAI__KEY",
        "-e",
        "CONFIG__GIT_PROVIDER=gitea",
        "-e",
        f"GITEA__URL={INTERNAL}",
        "-e",
        "OPENAI__API_BASE=https://api.nan.builders/v1",
        "-e",
        "CONFIG__MODEL=openai/mimo-v2.5",
        "-e",
        'CONFIG__FALLBACK_MODELS=["openai/deepseek-v4-flash"]',
        "-e",
        "CONFIG__CUSTOM_MODEL_MAX_TOKENS=200000",
        "-e",
        "CONFIG__PUBLISH_OUTPUT_PROGRESS=false",
        "-e",
        'GITEA__PR_COMMANDS=["/review"]',
        "-e",
        "GITEA__HANDLE_PUSH_TRIGGER=true",
        "-e",
        'GITEA__PUSH_COMMANDS=["/review"]',
        "-e",
        "PR_REVIEWER__PERSISTENT_COMMENT=true",
        "-e",
        f"PR_REVIEWER__FINAL_UPDATE_MESSAGE={os.environ.get('LAB_FINAL_UPDATE', 'true')}",
        AGENT_IMAGE,
        env=env,
    )

    def up() -> bool:
        try:
            return requests.post(AGENT_LOCAL, data=b"{}", timeout=5).status_code in (400, 401, 422, 200)
        except requests.RequestException:
            return False

    if not wait_for(up, 90):
        sys.exit("pr-agent server did not come up")


def reviewer_comments(admin: Any, pr: int) -> list[dict[str, Any]]:
    comments = ok(call("GET", f"/repos/{REPO}/issues/{pr}/comments", admin), "list comments")
    return [c for c in comments if c["user"]["login"] == "reviewer"]


def access_log_for(user: str) -> list[str]:
    raw = subprocess.run(["docker", "logs", GITEA], capture_output=True, text=True, check=False)
    lines = (raw.stdout + raw.stderr).splitlines()
    picked = []
    for line in lines:
        if f" - {user} " in line and "/api/v1/" in line:
            m = re.search(r'"(GET|POST|PATCH|PUT|DELETE) (\S+) HTTP/[\d.]+" (\d{3})', line)
            if m:
                path = re.sub(r"/\d+(?=/|$|\?)", "/{n}", m.group(2).split("?")[0])
                picked.append(f"{m.group(3)} {m.group(1)} {path}")
    return picked


def main() -> None:
    nan_key = os.environ.get("NAN_API_KEY", "")
    if not nan_key:
        sys.exit("NAN_API_KEY is not in the environment; run under `dotf secrets run --only NAN_API_KEY --`")
    SECRET_VALUES.append(nan_key)
    results: dict[str, Any] = {}
    try:
        admin = start_gitea()
        ids = seed(admin)
        reviewer_pw = make_user(admin, "reviewer")
        ok(call("PUT", f"/teams/{ids['team_id']}/members/reviewer", admin), "team member")
        probe_pr = open_pr(admin, "probe/scopes", "feat: scope probe", "probe body")

        if os.environ.get("LAB_SKIP_SCOPES") != "1":
            results["scopes"] = {
                name: probe_scopes(mint("reviewer", reviewer_pw, f"lab-{name}", scopes), probe_pr, ids["label_id"])
                for name, scopes in SCOPE_SETS.items()
            }

        prohibited_pw = make_user(admin, "prohibited")
        prohibited_token = mint("prohibited", prohibited_pw, "lab-prohibited", ["read:user"])
        before = call("GET", "/user", prohibited_token).status_code
        ok(
            call(
                "PATCH",
                "/admin/users/prohibited",
                admin,
                json={"prohibit_login": True, "login_name": "prohibited", "source_id": 0},
            ),
            "prohibit",
        )
        after = call("GET", "/user", prohibited_token)
        results["prohibit_login"] = {
            "before": before,
            "after": after.status_code,
            "message": after.json().get("message", ""),
        }

        hook_events = json.loads(os.environ.get("LAB_HOOK_EVENTS", '["pull_request"]'))
        results["config"] = {
            "hook_events": hook_events,
            "final_update_message": os.environ.get("LAB_FINAL_UPDATE", "true"),
        }
        webhook_secret = secrets.token_hex(32)
        SECRET_VALUES.append(webhook_secret)
        agent_token = mint("reviewer", reviewer_pw, "lab-agent", SCOPE_SETS["issue+repo"])
        start_agent(agent_token, webhook_secret, nan_key)

        unsigned = requests.post(AGENT_LOCAL, json={"action": "opened"}, timeout=10)
        wrong = requests.post(
            AGENT_LOCAL,
            data=b'{"action":"opened"}',
            timeout=10,
            headers={
                "Content-Type": "application/json",
                "X-Gitea-Signature": hmac.new(b"wrong", b'{"action":"opened"}', hashlib.sha256).hexdigest(),
            },
        )
        results["signature"] = {"unsigned": unsigned.status_code, "wrong_signature": wrong.status_code}

        ok(
            call(
                "POST",
                f"/repos/{REPO}/hooks",
                admin,
                json={
                    "type": "gitea",
                    "active": True,
                    "events": hook_events,
                    "config": {
                        "url": f"http://{AGENT}:3000/api/v1/gitea_webhooks",
                        "content_type": "json",
                        "secret": webhook_secret,
                    },
                },
            ),
            "webhook",
        )

        # The scope probes above also ran as `reviewer`, so the server's calls are the
        # access-log lines after each marker. A settle wait lets trailing calls land.
        mark0 = len(access_log_for("reviewer"))
        title, body = "feat: add greet", "Author-written body. The reviewer must not rewrite it."
        pr = open_pr(admin, "feat/greet", title, body)
        first = wait_for(lambda: reviewer_comments(admin, pr), 240, 5)
        time.sleep(20)
        mark1 = len(access_log_for("reviewer"))
        results["on_open"] = {
            "reviewer_comments": len(first or []),
            "is_reviewer_guide": bool(first and "PR Reviewer Guide" in first[0]["body"]),
            "api_calls": access_log_for("reviewer")[mark0:mark1],
        }
        if first:
            first_updated = first[0]["updated_at"]
            push_commit(admin, "feat/greet")
            edited = wait_for(
                lambda: [c for c in reviewer_comments(admin, pr) if c["updated_at"] != first_updated] or None, 240, 5
            )
            time.sleep(20)
            now = reviewer_comments(admin, pr)
            results["on_push"] = {
                "reviewer_comments": len(now),
                "same_comment_edited": bool(edited and edited[0]["id"] == first[0]["id"]),
                "api_calls": access_log_for("reviewer")[mark1:],
            }
        # Slash commands written by the PR's author. The spec keeps them out of scope,
        # so the question is whether the hook delivers comment events at all.
        mark2 = len(access_log_for("reviewer"))
        before = len(reviewer_comments(admin, pr))
        ok(
            call(
                "POST",
                f"/repos/{REPO}/issues/{pr}/comments",
                admin,
                json={"body": "/ask What does greet return for an empty name?"},
            ),
            "slash ask",
        )
        answered = wait_for(lambda: len(reviewer_comments(admin, pr)) > before, 150, 5)
        ok(call("POST", f"/repos/{REPO}/issues/{pr}/comments", admin, json={"body": "/describe"}), "slash describe")
        time.sleep(60)
        results["slash_commands"] = {
            "ask_answered_by_reviewer": bool(answered),
            "api_calls": access_log_for("reviewer")[mark2:],
        }
        pr_now = ok(call("GET", f"/repos/{REPO}/pulls/{pr}", admin), "read pr")
        results["pr_untouched"] = {"title": pr_now["title"] == title, "body": pr_now["body"] == body}
        hooks = ok(call("GET", f"/repos/{REPO}/hooks", admin), "hooks")
        results["hook_events_stored"] = hooks[0].get("events")
        agent_log = subprocess.run(["docker", "logs", AGENT], capture_output=True, text=True, check=False)
        results["agent_log_errors"] = sorted(
            {
                redact(line)[-220:]
                for line in (agent_log.stdout + agent_log.stderr).splitlines()
                if re.search(r"\| (ERROR|WARNING) ", line) and "Settings file not found" not in line
            }
        )[:25]
    finally:
        docker("rm", "-f", AGENT, GITEA, check=False)
        docker("network", "rm", NET, check=False)
    print(redact(json.dumps(results, indent=2)))


if __name__ == "__main__":
    main()
