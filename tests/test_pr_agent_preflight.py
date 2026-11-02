"""TOOL-082 (#1843): scripts/pr-agent-model-preflight.sh finds the first NaN model that answers.

Before PR-Agent runs, the preflight probes each model of the chain the workflow
declares and hands over the first one that answers, so a retired or hanging model
degrades to the next one loudly instead of to a green job with no review.
Ported from mlorentedev/dotfiles, where `mimo-v2.5` hung for hours on 2026-09-30
and then answered 401 (dotfiles AI-045).

Two halves, because a stub proves what the script ASKS curl to do and nothing
about what curl does with it:

- the stubbed tests put a fake `curl` first on PATH that answers per model from
  STUB_CODES and logs its argv and stdin, so they can prove where the key travels;
- the real tests run the real `curl` against a server on 127.0.0.1, and prove it
  reads the Authorization header from the config on stdin (`-K -`), that
  `-w '%{http_code}'` yields the status, and that `-m` turns a server that never
  answers, or answers only a status line, into the "no answer" path. A misspelt
  config directive passes every stub test and sends no key at all.
"""

from __future__ import annotations

import http.server
import json
import os
import shutil
import socketserver
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PREFLIGHT = REPO_ROOT / "scripts" / "pr-agent-model-preflight.sh"
KEY = "sk-test-not-a-real-key"

pytestmark = pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("bash", "jq", "curl")),
    reason="the preflight needs bash, jq and curl",
)

# Answers per model from STUB_CODES ("model=code ..."; `timeout` behaves like
# curl's exit 28) and logs argv and stdin.
FAKE_CURL = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$STUB_ARGV_LOG"
cat >> "$STUB_STDIN_LOG"
body=""
while [ $# -gt 0 ]; do
    case "$1" in -d|--data) body="$2"; shift ;; esac
    shift
done
model=$(printf '%s' "$body" | jq -r '.model')
code=$(printf '%s\n' $STUB_CODES | sed -n "s/^${model}=//p")
if [ "$code" = "timeout" ]; then printf '000'; exit 28; fi
printf '%s' "${code:-404}"
"""

# Variables a developer's shell may carry that would change what the script does.
LEAKY = ("NAN_API_KEY", "NAN_API_BASE", "PREFLIGHT_TIMEOUT", "GITHUB_STEP_SUMMARY")


def _base_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in LEAKY}
    env["NAN_API_KEY"] = KEY
    return env


class Preflight:
    """The preflight run against a fake curl, with its output file and logs."""

    def __init__(self, tmp_path: Path) -> None:
        self.out = tmp_path / "output"
        self.out.write_text("", encoding="utf-8")
        self.argv_log = tmp_path / "argv.log"
        self.stdin_log = tmp_path / "stdin.log"
        self.summary = tmp_path / "summary.md"
        bindir = tmp_path / "bin"
        bindir.mkdir()
        curl = bindir / "curl"
        curl.write_text(FAKE_CURL, encoding="utf-8")
        curl.chmod(0o755)
        self.env = _base_env()
        self.env["PATH"] = f"{bindir}{os.pathsep}{os.environ['PATH']}"
        self.env["STUB_ARGV_LOG"] = str(self.argv_log)
        self.env["STUB_STDIN_LOG"] = str(self.stdin_log)

    def run(
        self,
        codes: str,
        *,
        summary: bool = False,
        model: str = "openai/mimo-v2.6-flash",
        fallbacks: str = '["openai/deepseek-v4-flash"]',
    ) -> subprocess.CompletedProcess[str]:
        env = {**self.env, "STUB_CODES": codes}
        if summary:
            env["GITHUB_STEP_SUMMARY"] = str(self.summary)
        return subprocess.run(  # noqa: S603
            [str(PREFLIGHT), "--model", model, "--fallbacks", fallbacks, "--output", str(self.out)],
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def lines(self) -> list[str]:
        return self.out.read_text(encoding="utf-8").splitlines()


@pytest.fixture
def preflight(tmp_path: Path) -> Preflight:
    return Preflight(tmp_path)


def _output(proc: subprocess.CompletedProcess[str]) -> str:
    return proc.stdout + proc.stderr


def _in_order(text: str, *parts: str) -> bool:
    """True when every part occurs in `text`, each after the one before it."""
    at = 0
    for part in parts:
        at = text.find(part, at)
        if at < 0:
            return False
        at += len(part)
    return True


def test_the_primary_answers_so_it_reviews_and_the_fallback_stays_behind_it(preflight: Preflight) -> None:
    proc = preflight.run("mimo-v2.6-flash=200 deepseek-v4-flash=200")
    assert proc.returncode == 0, _output(proc)
    assert "model=openai/mimo-v2.6-flash" in preflight.lines()
    assert 'fallbacks=["openai/deepseek-v4-flash"]' in preflight.lines()
    assert not any(line.startswith("retry_model=") for line in preflight.lines())
    assert "::warning::" not in _output(proc)


def test_a_retired_primary_401_hands_the_review_to_the_fallback_and_says_so(preflight: Preflight) -> None:
    proc = preflight.run("mimo-v2.6-flash=401 deepseek-v4-flash=200")
    assert proc.returncode == 0, _output(proc)
    assert "model=openai/deepseek-v4-flash" in preflight.lines()
    assert "fallbacks=[]" in preflight.lines()
    assert not any(line.startswith("retry_model=") for line in preflight.lines())
    assert _in_order(_output(proc), "::warning::", "openai/mimo-v2.6-flash", "HTTP 401", "openai/deepseek-v4-flash"), (
        _output(proc)
    )


def test_a_primary_that_hangs_is_skipped_like_one_that_refuses(preflight: Preflight) -> None:
    proc = preflight.run("mimo-v2.6-flash=timeout deepseek-v4-flash=200")
    assert proc.returncode == 0, _output(proc)
    assert "model=openai/deepseek-v4-flash" in preflight.lines()
    assert _in_order(_output(proc), "::warning::", "openai/mimo-v2.6-flash", "no answer within"), _output(proc)


def test_the_warning_names_the_fix_by_status_class_not_one_remedy_for_all(preflight: Preflight) -> None:
    """401/403/404: the key cannot call it, so the chain is wrong. 402/429: quota
    or NaN's per-model concurrency (mlorentedev/dotfiles#1107), where editing the
    chain is the wrong advice. 5xx and a hang: NaN did not answer this time."""
    proc = preflight.run("mimo-v2.6-flash=429 deepseek-v4-flash=200")
    assert proc.returncode == 0, _output(proc)
    assert _in_order(_output(proc), "openai/mimo-v2.6-flash answered HTTP 429", "quota or concurrency")
    assert "Fix the chain" not in _output(proc)

    proc = preflight.run("mimo-v2.6-flash=401 deepseek-v4-flash=200")
    assert _in_order(_output(proc), "HTTP 401", "Fix the chain"), _output(proc)

    proc = preflight.run("mimo-v2.6-flash=503 deepseek-v4-flash=200")
    assert _in_order(_output(proc), "HTTP 503", "NaN did not serve it"), _output(proc)
    assert "Fix the chain" not in _output(proc)


def test_when_no_declared_model_answers_the_step_fails_and_nan_leaves_the_pool(preflight: Preflight) -> None:
    proc = preflight.run("mimo-v2.6-flash=401 deepseek-v4-flash=429")
    assert proc.returncode == 1, _output(proc)
    assert "::warning::No model in PR-Agent's declared NaN chain answered" in _output(proc)
    assert not any(line.startswith("model=") for line in preflight.lines())


def test_it_never_picks_a_model_outside_the_declared_chain(preflight: Preflight) -> None:
    """Every other id answers; only the two declared ones refuse."""
    proc = preflight.run("mimo-v2.6-flash=401 deepseek-v4-flash=401 glm5.3-flash=200 qwen3.6=200")
    assert proc.returncode == 1, _output(proc)
    written = preflight.out.read_text(encoding="utf-8")
    assert "glm5.3-flash" not in written
    assert "qwen3.6" not in written


def test_it_probes_the_bare_nan_id_and_hands_pr_agent_the_transport_prefixed_one(preflight: Preflight) -> None:
    proc = preflight.run("mimo-v2.6-flash=200 deepseek-v4-flash=200")
    assert proc.returncode == 0, _output(proc)
    argv = preflight.argv_log.read_text(encoding="utf-8")
    assert '"model":"mimo-v2.6-flash"' in argv
    assert '"model":"openai/' not in argv


def test_the_key_reaches_curl_on_stdin_never_on_its_argv(preflight: Preflight) -> None:
    proc = preflight.run("mimo-v2.6-flash=200 deepseek-v4-flash=200")
    assert proc.returncode == 0, _output(proc)
    assert KEY not in preflight.argv_log.read_text(encoding="utf-8")
    assert f"Bearer {KEY}" in preflight.stdin_log.read_text(encoding="utf-8")
    assert KEY not in _output(proc)


def test_the_job_summary_names_the_model_that_reviews_and_every_one_that_did_not_answer(
    preflight: Preflight,
) -> None:
    proc = preflight.run("mimo-v2.6-flash=401 deepseek-v4-flash=200", summary=True)
    assert proc.returncode == 0, _output(proc)
    summary = preflight.summary.read_text(encoding="utf-8")
    assert "openai/deepseek-v4-flash" in summary
    assert any("openai/mimo-v2.6-flash" in line and "401" in line for line in summary.splitlines())


def test_a_missing_key_or_model_is_a_usage_error_not_a_model_failure(preflight: Preflight) -> None:
    def run(env: dict[str, str], *args: str) -> int:
        return subprocess.run(  # noqa: S603
            [str(PREFLIGHT), *args, "--output", str(preflight.out)],
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
        ).returncode

    no_key = {k: v for k, v in preflight.env.items() if k != "NAN_API_KEY"}
    assert run(no_key, "--model", "openai/x", "--fallbacks", "[]") == 2
    assert run(preflight.env, "--fallbacks", "[]") == 2
    assert run(preflight.env, "--model", "openai/x", "--fallbacks", "not json") == 2


# --- the real curl ---------------------------------------------------------------


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

    # HTTPServer.server_bind resolves socket.getfqdn(host) only to fill
    # server_name. On a macOS runner that reverse lookup outlived the start-up
    # wait, so every test failed in setup. Nothing here reads server_name.
    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = str(self.server_address[0]), self.server_address[1]


class LocalNaN:
    """A NaN stand-in on 127.0.0.1. The model in the request picks the behaviour:
    `alive` answers 200, `hang` holds the connection open, `stall` sends a 200
    status line and never the body, anything else answers 401."""

    def __init__(self) -> None:
        self.authorizations: list[str] = []
        self.release = threading.Event()
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.authorizations.append(f"{body['model']} {self.headers.get('Authorization', '<none>')}")
                if body["model"] == "hang":
                    owner.release.wait(30)
                    return
                if body["model"] == "stall":
                    self.send_response(200)
                    self.send_header("Content-Length", "100")
                    self.end_headers()
                    self.wfile.flush()
                    owner.release.wait(30)
                    return
                self.send_response(200 if body["model"] == "alive" else 401)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args: object) -> None:
                pass

        self.server = _Server(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> LocalNaN:
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release.set()
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def nan() -> Iterator[LocalNaN]:
    with LocalNaN() as server:
        yield server


def _run_real(nan: LocalNaN, tmp_path: Path, model: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    out = tmp_path / "output"
    out.write_text("", encoding="utf-8")
    env = {**_base_env(), "NAN_API_BASE": nan.url, "PREFLIGHT_TIMEOUT": "2"}
    proc = subprocess.run(  # noqa: S603
        [str(PREFLIGHT), "--model", model, "--fallbacks", '["openai/alive"]', "--output", str(out)],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc, out.read_text(encoding="utf-8").splitlines()


def test_real_curl_sends_the_key_read_from_stdin_and_the_status_comes_back(nan: LocalNaN, tmp_path: Path) -> None:
    proc, lines = _run_real(nan, tmp_path, "openai/dead")
    assert proc.returncode == 0, _output(proc)
    assert "model=openai/alive" in lines
    assert "openai/dead answered HTTP 401" in _output(proc)
    # Every probe carried the key, so `-K -` parsed the config line.
    assert [a for a in nan.authorizations if a.endswith(f"Bearer {KEY}")] == nan.authorizations
    assert len(nan.authorizations) == 2


def test_real_curl_a_server_that_never_answers_ends_at_the_timeout_as_no_answer(nan: LocalNaN, tmp_path: Path) -> None:
    proc, lines = _run_real(nan, tmp_path, "openai/hang")
    assert proc.returncode == 0, _output(proc)
    assert "model=openai/alive" in lines
    assert "openai/hang gave no answer within 2s" in _output(proc)


def test_real_curl_a_200_status_line_whose_body_never_arrives_is_no_answer(nan: LocalNaN, tmp_path: Path) -> None:
    proc, lines = _run_real(nan, tmp_path, "openai/stall")
    assert proc.returncode == 0, _output(proc)
    assert "model=openai/alive" in lines
    assert "openai/stall gave no answer within 2s" in _output(proc)
