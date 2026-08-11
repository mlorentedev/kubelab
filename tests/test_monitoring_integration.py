"""Integration tests for the declarative monitor sync, against a real Uptime Kuma.

These exist because the defect that mattered was invisible to unit tests. #992's
diff passed 16 unit tests and still reported 31 edits on a converged instance:
the fault lived in the gap between the *real* seed and what the write path
accepts, and no fixture written by the same person who wrote the code was going
to contain that gap.

So this drives `apply_monitors` end to end against a throwaway container — never
rpi3, which is the monitoring of record. The image tag is read from `common.yaml`
rather than hardcoded, so the dev loop cannot silently drift from what production
runs; a v1-era wrapper against the wrong v2 build fails in ways that read as
"my code is broken".

Three things here are not optional:

- `UPTIME_KUMA_DB_TYPE=sqlite`, because Kuma v2 otherwise halts in a database
  wizard and serves HTML at `/socket.io/`, which surfaces as an opaque
  "Unexpected response from server".
- The raw-socket `setup` emit, because the pinned `uptime-kuma-api` predates v2
  and its own `setup()` times out.
- A fresh client per operation, because `apply_monitors` closes the connection it
  is handed in its own `finally`.

Every test wipes the instance first and builds the state it needs, so they do not
depend on each other's ordering — this suite runs under `pytest-randomly`.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
import yaml

from toolkit.features import monitoring
from toolkit.features.monitoring_diff import diff_monitors, extract_key

pytestmark = pytest.mark.integration

CONTAINER_NAME = "kubelab-test-kuma"
ADMIN_USER = "admin"
ADMIN_PASS = "integration-test-pass"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _pinned_image() -> str:
    """Read the Uptime Kuma image from the config SSOT (common.yaml)."""
    values = yaml.safe_load((REPO_ROOT / "infra/config/values/common.yaml").read_text())
    return values["apps"]["services"]["observability"]["uptime_kuma"]["image"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def _run_setup(url: str) -> None:
    """Create the admin user by emitting `setup` on the raw socket.

    `UptimeKumaApi.setup()` times out against v2 — the wrapper is v1-era. The
    server answers the raw event with `{"ok": True, "msg": "successAdded"}`.
    """
    import socketio

    sio = socketio.Client()
    result: dict = {}
    sio.connect(f"{url}/socket.io/", wait_timeout=30, transports=["websocket"])
    try:
        time.sleep(1)
        sio.emit("setup", (ADMIN_USER, ADMIN_PASS), callback=lambda r: result.update(r or {}))
        deadline = time.time() + 30
        while not result and time.time() < deadline:
            time.sleep(0.5)
    finally:
        sio.disconnect()
    if not result.get("ok"):
        raise RuntimeError(f"Uptime Kuma setup failed: {result}")


@pytest.fixture(scope="module")
def kuma_url():
    """A disposable Uptime Kuma, torn down whatever happens.

    Yields the URL rather than a client: `apply_monitors` closes the connection
    it is given in its own `finally`, so a shared client would be dead after the
    first apply. Each caller opens its own.
    """
    if not _docker_available():
        pytest.skip("Docker is not available")

    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True)
    subprocess.run(
        [
            "docker", "run", "-d", "--name", CONTAINER_NAME,
            "-e", "UPTIME_KUMA_DB_TYPE=sqlite",
            "-p", f"127.0.0.1:{port}:3001",
            _pinned_image(),
        ],
        check=True,
        capture_output=True,
    )
    try:
        deadline = time.time() + 180
        while time.time() < deadline:
            probe = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Health.Status}}", CONTAINER_NAME],
                capture_output=True,
                text=True,
            )
            if probe.stdout.strip() == "healthy":
                break
            time.sleep(3)
        else:
            pytest.fail("Uptime Kuma container never became healthy")

        # A fresh v2 reports healthy while still in its setup wizard — the
        # healthcheck accepts the 302 to /setup-database. Health is not readiness.
        _run_setup(url)
        yield url
    finally:
        subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True)


def _client(url: str):
    from uptime_kuma_api import UptimeKumaApi

    api = UptimeKumaApi(url, timeout=60)
    api.login(ADMIN_USER, ADMIN_PASS)
    return api


@pytest.fixture
def live(kuma_url):
    """Read the instance's monitors, authoritatively.

    Opens a fresh connection every call on purpose. `get_monitors()` returns a
    client-side cache fed by socket events, and it does NOT reliably reflect
    writes made over a different connection — an earlier version of this file
    held one client open and watched it report an empty instance while the server
    had all 31 monitors. Same property that made `time.sleep(3)` look necessary
    in the code under test.
    """

    def _read() -> list[dict]:
        api = _client(kuma_url)
        try:
            return api.get_monitors()
        finally:
            api.disconnect()

    return _read


@pytest.fixture
def apply_seed(kuma_url, monkeypatch, tmp_path):
    """Run the real `apply_monitors` against the throwaway, with a given seed.

    Hands it a fresh client each time, since it disconnects what it is given.
    """

    def _apply(seed: list[dict]) -> None:
        export_dir = tmp_path / monitoring.EXPORT_DIR
        export_dir.mkdir(parents=True, exist_ok=True)
        (export_dir / monitoring.MONITORS_FILE).write_text(json.dumps(seed))
        monkeypatch.setattr(
            monitoring, "_connect", lambda _root: (_client(kuma_url), {"url": kuma_url})
        )
        monitoring.apply_monitors(tmp_path)

    return _apply


@pytest.fixture(autouse=True)
def wipe(kuma_url, request):
    """Start every test from an empty instance — no inter-test ordering."""
    if "kuma_url" not in request.fixturenames:
        return
    api = _client(kuma_url)
    try:
        for m in api.get_monitors():
            api.delete_monitor(m["id"])
    finally:
        api.disconnect()


def _real_seed() -> list[dict]:
    return json.loads((REPO_ROOT / "infra/config/uptime-kuma/monitors.json").read_text())


class TestApplyAgainstARealInstance:
    def test_first_apply_creates_the_whole_seed(self, live, apply_seed):
        seed = _real_seed()

        apply_seed(seed)

        assert len(live()) == len(seed)

    def test_second_apply_is_a_no_op_and_preserves_every_id(self, live, apply_seed):
        """AC1 — the regression #962 is about, proven against a real instance."""
        seed = _real_seed()
        apply_seed(seed)
        before = {m["name"]: m["id"] for m in live()}

        create, edit, delete = diff_monitors(seed, live())
        assert (len(create), len(edit), len(delete)) == (0, 0, 0), (
            "a converged instance must plan nothing — this is the check that "
            "caught 31 phantom edits the unit fixtures could not"
        )

        apply_seed(seed)

        assert {m["name"]: m["id"] for m in live()} == before, (
            "ids must survive a sync, because the uptime history hangs off them"
        )

    def test_dropping_a_monitor_from_the_seed_deletes_exactly_that_one(self, live, apply_seed):
        """AC3's real exercise: the delete path, which the spec flagged as untested."""
        seed = _real_seed()
        apply_seed(seed)
        before = {m["name"] for m in live()}

        removed = seed.pop()
        apply_seed(seed)

        after = {m["name"] for m in live()}
        assert before - after == {removed["name"]}, "exactly the dropped monitor, nothing else"
        assert len(after) == len(seed)

    def test_renaming_a_monitor_edits_it_instead_of_recreating_it(self, live, apply_seed):
        """The whole reason identity is a key and not the name."""
        seed = _real_seed()
        seed[0]["key"] = "renamed-under-test"
        apply_seed(seed)

        original_id = next(m["id"] for m in live() if m["name"] == seed[0]["name"])
        stamped = next(m for m in live() if m["id"] == original_id)
        assert extract_key(stamped.get("description")) == "renamed-under-test", (
            "the key must be stamped, or a later rename cannot be tracked"
        )

        seed[0]["name"] = "Renamed By The Integration Test"
        apply_seed(seed)

        live = live()
        assert original_id in {m["id"] for m in live}, "a rename must not recreate the monitor"
        assert next(m["name"] for m in live if m["id"] == original_id) == seed[0]["name"]
        assert len(live) == len(seed), "and must not leave an orphan behind"
