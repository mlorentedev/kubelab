"""What the `errors` image sends, measured on the built image (OPS-030 AC4, AC5, ADR-072).

Traefik forwards the client's request headers to this service, so `Accept` decides
between the branded page and a JSON body, and the response headers reach the client:
`Cache-Control: public` + `expires 1d` used to ride along on every 502. nginx is only
configuration, so the only honest test is to run it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from http.client import HTTPResponse
from pathlib import Path

import pytest

CONTEXT = Path(__file__).resolve().parent.parent / "edge" / "errors"


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


@pytest.fixture(scope="module")
def base_url() -> Iterator[str]:
    if not _docker_ready():
        if os.environ.get("CI"):
            pytest.fail("docker is required in CI to run the built errors image")
        pytest.skip("docker not available: cannot run the errors image (a skip is CANNOT CHECK, not OK)")
    tag = f"errors-test:{uuid.uuid4().hex[:8]}"
    name = f"errors-test-{uuid.uuid4().hex[:8]}"
    subprocess.run(["docker", "build", "-q", "-t", tag, str(CONTEXT)], check=True, capture_output=True)
    subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "-p", "127.0.0.1::8080", tag], check=True, capture_output=True)
    try:
        port = subprocess.run(
            ["docker", "port", name, "8080/tcp"], check=True, capture_output=True, text=True
        ).stdout.split(":")[-1].strip()
        url = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                urllib.request.urlopen(f"{url}/health", timeout=1)
                break
            except OSError:
                time.sleep(0.2)
        else:
            logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True).stderr[-400:]
            raise RuntimeError(f"the errors image did not answer /health within 10s: {logs}")
        yield url
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        subprocess.run(["docker", "rmi", "-f", tag], capture_output=True)


def _get(url: str, accept: str | None = None) -> tuple[int, dict[str, str], str]:
    req = urllib.request.Request(url, headers={"Accept": accept} if accept else {})
    try:
        resp: HTTPResponse = urllib.request.urlopen(req, timeout=5)
    except urllib.error.HTTPError as err:
        resp = err  # type: ignore[assignment]
    headers = {k.lower(): v for k, v in resp.headers.items()}
    return resp.status if hasattr(resp, "status") else resp.code, headers, resp.read().decode(errors="replace")


@pytest.mark.parametrize("status", [502, 503, 504])
def test_a_gateway_error_is_json_for_a_client_that_asks(base_url: str, status: int) -> None:
    code, headers, body = _get(f"{base_url}/errors/{status}.html", accept="application/json")
    assert headers["content-type"].startswith("application/json")
    error = json.loads(body)["error"]
    assert error["status"] == status
    assert error["title"] and error["message"]
    assert code == 200  # Traefik, not this service, enforces the original status on the way out


@pytest.mark.parametrize("accept", [None, "text/html,application/xhtml+xml,*/*;q=0.8", "*/*"])
def test_everything_else_still_gets_the_page(base_url: str, accept: str | None) -> None:
    _, headers, body = _get(f"{base_url}/errors/502.html", accept=accept)
    assert headers["content-type"].startswith("text/html")
    assert "<h1" in body


def test_the_catch_all_keeps_its_404_for_both_shapes(base_url: str) -> None:
    code, headers, body = _get(f"{base_url}/nope", accept="application/json")
    assert code == 404 and json.loads(body)["error"]["status"] == 404
    assert headers["content-type"].startswith("application/json")
    code, headers, _ = _get(f"{base_url}/nope")
    assert code == 404 and headers["content-type"].startswith("text/html")


@pytest.mark.parametrize("path", ["/errors/502.html", "/errors/503.html", "/errors/504.html", "/nope"])
@pytest.mark.parametrize("accept", [None, "application/json"])
def test_error_responses_are_never_cached_or_indexed(base_url: str, path: str, accept: str | None) -> None:
    _, headers, _ = _get(f"{base_url}{path}", accept=accept)
    assert headers["cache-control"] == "no-store"
    assert headers["x-robots-tag"] == "noindex"
    assert "expires" not in headers, "the old `expires 1d` must not come back"


@pytest.mark.parametrize("status", [503, 504])
def test_retry_after_on_the_statuses_that_invite_a_retry(base_url: str, status: int) -> None:
    _, headers, _ = _get(f"{base_url}/errors/{status}.html")
    assert headers["retry-after"].isdigit()


def test_502_does_not_invite_an_immediate_retry(base_url: str) -> None:
    _, headers, _ = _get(f"{base_url}/errors/502.html")
    assert "retry-after" not in headers


def test_the_security_headers_survive_the_errors_location(base_url: str) -> None:
    """nginx drops server-level add_header in a location that sets its own: say it out loud."""
    _, headers, _ = _get(f"{base_url}/errors/502.html")
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"


def test_brand_assets_keep_their_long_cache(base_url: str) -> None:
    """The no-store above must not leak into /brand/ (ADR-071)."""
    root = CONTEXT / "html" / "brand"
    asset = next(p for p in root.rglob("*") if p.is_file())
    _, headers, _ = _get(f"{base_url}/brand/{asset.relative_to(root)}")
    assert "immutable" in headers["cache-control"]
