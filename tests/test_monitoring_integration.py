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
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
import yaml
from uptime_kuma_api import UptimeKumaApi

from toolkit.features import monitoring
from toolkit.features.monitoring_diff import diff_monitors, extract_key

pytestmark = pytest.mark.integration

# PID-suffixed rather than a fixed name: this repo runs several worktree lanes
# in parallel (each with its own `make test`), and a shared literal name meant
# one lane's `docker rm -f` on setup could kill another's live container mid-run
# — the failure then reads as "socket refused", not as a naming collision.
CONTAINER_NAME = f"kubelab-test-kuma-{os.getpid()}"
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


def _wait_until_socket_reachable(url: str, timeout: float = 30.0) -> None:
    """Block until a socket.io handshake actually succeeds, not just Docker's health flag.

    Same family of claim gap as the setup-wizard redirect this file already
    documents: `Health.Status == healthy` is Docker's opinion, not proof this
    process's socket.io endpoint will accept a handshake right now. Belt and
    braces on top of the container-name fix (`CONTAINER_NAME` is PID-suffixed)
    for the collision this project actually hit — a parallel lane's `docker rm
    -f` on the same fixed name killed this container mid-run, which surfaced
    as a bare connection refusal and briefly looked like a health/readiness
    race. Bounded retry on the exact mechanism callers use, not a raw HTTP ping
    standing in for it.
    """
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            probe = UptimeKumaApi(url, timeout=5)
            probe.disconnect()
            return
        except Exception as e:
            last_error = e
            time.sleep(1)
    pytest.fail(f"Uptime Kuma socket never became reachable at {url}: {last_error!r}")


def _start_kuma_container(name: str) -> str:
    """Start a throwaway Kuma v2 container and block until it is actually reachable.

    Returns the URL. Caller owns teardown (`docker rm -f name`) — shared by
    every fixture in this file so the readiness-wait logic has one definition.
    """
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "-e",
            "UPTIME_KUMA_DB_TYPE=sqlite",
            "-p",
            f"127.0.0.1:{port}:3001",
            _pinned_image(),
        ],
        check=True,
        capture_output=True,
    )
    deadline = time.time() + 180
    while time.time() < deadline:
        probe = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", name],
            capture_output=True,
            text=True,
        )
        if probe.stdout.strip() == "healthy":
            _wait_until_socket_reachable(url)
            return url
        time.sleep(3)
    pytest.fail("Uptime Kuma container never became healthy")


def _run_setup(url: str) -> None:
    """Create the admin user via `monitoring._run_setup` — the real code under test.

    `UptimeKumaApi.setup()` times out against v2 — the wrapper is v1-era.
    `monitoring._run_setup` is the production workaround (#962); exercising it
    here rather than a second hand-rolled raw-socket implementation is the point
    — a fixture reimplementing the fix would stop noticing if the fix broke.
    """
    api = UptimeKumaApi(url, timeout=30)
    try:
        monitoring._run_setup(api, ADMIN_USER, ADMIN_PASS)
    finally:
        api.disconnect()


@pytest.fixture(scope="module")
def kuma_url():
    """A disposable, already-set-up Uptime Kuma, torn down whatever happens.

    Yields the URL rather than a client: `apply_monitors` closes the connection
    it is given in its own `finally`, so a shared client would be dead after the
    first apply. Each caller opens its own.
    """
    if not _docker_available():
        pytest.skip("Docker is not available")

    try:
        url = _start_kuma_container(CONTAINER_NAME)
        # A fresh v2 reports healthy while still in its setup wizard — the
        # healthcheck accepts the 302 to /setup-database. Health is not readiness.
        _run_setup(url)
        yield url
    finally:
        subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True)


@pytest.fixture
def fresh_kuma_url():
    """A disposable Uptime Kuma with NO admin user yet — for `bootstrap()` itself.

    Own container (distinct name, function-scoped): the module fixture above is
    pre-set-up on purpose so `apply_monitors` tests never pay for it twice, but
    `bootstrap()`'s fresh-install branch (`need_setup() == True`) needs a genuinely
    unset-up instance to exercise for real.
    """
    if not _docker_available():
        pytest.skip("Docker is not available")

    name = f"{CONTAINER_NAME}-bootstrap"
    try:
        yield _start_kuma_container(name)
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def _client(url: str):
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
        monkeypatch.setattr(monitoring, "_connect", lambda _root: (_client(kuma_url), {"url": kuma_url}))
        monitoring.apply_monitors(tmp_path)

    return _apply


@pytest.fixture(autouse=True)
def wipe(request):
    """Start every test from an empty instance — no inter-test ordering.

    Takes `request` only, not `kuma_url` directly: declaring the fixture as a
    parameter forces pytest to instantiate it (and its container) before the
    `in request.fixturenames` guard below ever runs — every test in this file
    is `autouse`, including the `TestBootstrapAgainstAFreshInstance` ones that
    use `fresh_kuma_url` instead, so that would spin up both containers for
    every bootstrap test. `getfixturevalue` defers instantiation until after
    the guard confirms it is actually needed.
    """
    if "kuma_url" not in request.fixturenames:
        return
    kuma_url = request.getfixturevalue("kuma_url")
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


class TestBootstrapAgainstAFreshInstance:
    """`bootstrap()` end to end (#962) — the three things unit mocks cannot see:

    `need_setup()`'s own reply on a cold socket, `login()` reusing the same
    connection `_run_setup()` just used, and `upload_backup`'s v1 envelope
    against a v2 server (flagged in the ticket as "not yet tested").
    """

    def _seed(self) -> list[dict]:
        return [
            {"type": "http", "name": "bootstrap-test-1", "url": "https://example.com", "active": True},
            {"type": "http", "name": "bootstrap-test-2", "url": "https://example.org", "active": True},
        ]

    def test_bootstrap_creates_admin_and_imports_the_seed(self, fresh_kuma_url, monkeypatch, tmp_path):
        monkeypatch.setattr(
            monitoring,
            "_get_kuma_creds",
            lambda _root: {"url": fresh_kuma_url, "host": "127.0.0.1", "username": ADMIN_USER, "password": ADMIN_PASS},
        )
        export_dir = tmp_path / monitoring.EXPORT_DIR
        export_dir.mkdir(parents=True, exist_ok=True)
        (export_dir / monitoring.MONITORS_FILE).write_text(json.dumps(self._seed()))

        monitoring.bootstrap(tmp_path)

        api = _client(fresh_kuma_url)
        try:
            assert api.need_setup() is False, "the admin user must exist after bootstrap"
            assert len(api.get_monitors()) == len(self._seed()), (
                "upload_backup's v1 envelope against v2 was untested before this — "
                "if it silently drops monitors, this is the check that would catch it"
            )
        finally:
            api.disconnect()

    def test_bootstrap_run_twice_is_a_no_op_second_time(self, fresh_kuma_url, monkeypatch, tmp_path):
        """Idempotency: the second run must skip setup and skip import, not error."""
        monkeypatch.setattr(
            monitoring,
            "_get_kuma_creds",
            lambda _root: {"url": fresh_kuma_url, "host": "127.0.0.1", "username": ADMIN_USER, "password": ADMIN_PASS},
        )
        export_dir = tmp_path / monitoring.EXPORT_DIR
        export_dir.mkdir(parents=True, exist_ok=True)
        (export_dir / monitoring.MONITORS_FILE).write_text(json.dumps(self._seed()))
        monitoring.bootstrap(tmp_path)

        monitoring.bootstrap(tmp_path)  # must not raise, must not duplicate

        api = _client(fresh_kuma_url)
        try:
            assert len(api.get_monitors()) == len(self._seed())
        finally:
            api.disconnect()
