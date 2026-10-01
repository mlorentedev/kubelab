"""Root conftest — shared pytest configuration and fixtures."""

import functools
import os
import shutil
import subprocess
from collections.abc import Generator
from pathlib import Path

import pytest

from tests.host_clients import denied


def pytest_configure(config: pytest.Config) -> None:
    """Strip colour-forcing variables so CLI assertions do not depend on the shell.

    Rich renders an option name as several styled runs, so with colour ON the
    literal `--check` is emitted as `-`, an escape sequence, then `-check`. Every
    `assert "--check" in result.output` in the CLI tests then fails — while
    passing in CI, which has no TTY and no forced colour. Five tests in
    `test_sync.py` failed exactly this way on 2026-08-31 against unmodified
    master, which reads as a regression in whatever branch you happen to be on.

    `NO_COLOR` does NOT fix it: Rich gives `FORCE_COLOR` precedence, so removing
    the variables is the only reliable move.

    A HOOK AND NOT A FIXTURE, which the first attempt got wrong. Rich decides
    whether to emit colour when its Console is constructed, and the CLI modules
    build theirs at import — which happens during collection, before any fixture
    runs. Even an autouse session fixture is too late; `pytest_configure` runs
    before collection, which is the only window that works.
    """
    for var in ("FORCE_COLOR", "CLICOLOR_FORCE"):
        os.environ.pop(var, None)
    del config  # the hook's signature, not something this needs
    _install_host_client_barrier()


# --- Host-client barrier (#1886) -------------------------------------------------
#
# A unit test that reaches `kubectl` without mocking it does not fail where the
# binary is missing: it skips, or the toolkit swallows the FileNotFoundError. So
# it passes in CI and deletes a Secret on staging from a workstation with a
# kubeconfig (#1886: `apply_secrets` grew a `delete_retired_secrets` step, and
# the old tests that mocked its neighbours one by one ran it for real).
#
# Every subprocess goes through `Popen.__init__`, so that is where the barrier
# sits. It raises a BaseException because the toolkit catches `OSError` and
# `Exception` around its subprocess calls, and a refusal it could swallow would
# be a refusal nobody sees; the hit is also recorded on the item and the report
# forced red, in case something catches BaseException after all.
#
# Outside a test (collection, e.g. `sops_can_decrypt`) nothing is refused.
# Set KUBELAB_HOST_CLIENT_REPORT=<file> to record hits instead of refusing them.

HOST_CLIENT_EXEMPT_MARKERS = ("integration", "e2e", "infra")
HOST_CLIENT_EXEMPT_DIRS = ("e2e", "infra")
_TESTS_DIR = Path(__file__).resolve().parent
_current_item: pytest.Item | None = None


class HostClientRefused(BaseException):
    """A unit test spawned a client that reaches a cluster or a host."""


def _host_clients_allowed(item: pytest.Item) -> bool:
    if any(item.get_closest_marker(m) for m in HOST_CLIENT_EXEMPT_MARKERS):
        return True
    if item.get_closest_marker("allow_host_clients"):
        return True  # its reason is checked in pytest_runtest_setup
    try:
        relative = Path(item.path).resolve().relative_to(_TESTS_DIR)
    except ValueError:
        return False
    return relative.parts[0] in HOST_CLIENT_EXEMPT_DIRS


def _install_host_client_barrier() -> None:
    original_init = subprocess.Popen.__init__
    if getattr(original_init, "_host_client_barrier", False):
        return

    def guarded_init(self, args, *pargs, **kwargs):  # noqa: ANN001, ANN202
        item = _current_item
        if item is not None and not _host_clients_allowed(item):
            client = denied(args, shell=bool(kwargs.get("shell")))
            if client:
                report = os.environ.get("KUBELAB_HOST_CLIENT_REPORT")
                if report:
                    with open(report, "a", encoding="utf-8") as fh:
                        fh.write(f"{item.nodeid}\t{client}\n")
                else:
                    message = (
                        f"unit test spawned `{client}`, which reaches a real cluster or host. "
                        "Mock it, or mark the test "
                        '@pytest.mark.allow_host_clients(reason="...") if it must (#1886).'
                    )
                    item.stash.setdefault(_REFUSALS, []).append(message)
                    raise HostClientRefused(message)
        original_init(self, args, *pargs, **kwargs)

    guarded_init._host_client_barrier = True  # type: ignore[attr-defined]
    subprocess.Popen.__init__ = guarded_init  # type: ignore[method-assign]


_REFUSALS = pytest.StashKey[list[str]]()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item) -> Generator[None, None, None]:
    """Track the running test, setup and teardown included, for the barrier."""
    global _current_item
    _current_item = item
    try:
        yield
    finally:
        _current_item = None


def pytest_runtest_setup(item: pytest.Item) -> None:
    marker = item.get_closest_marker("allow_host_clients")
    if marker is not None and not str(marker.kwargs.get("reason", "")).strip():
        pytest.fail(
            '@pytest.mark.allow_host_clients needs reason="..." naming what the test reaches and why',
            pytrace=False,
        )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item) -> Generator[None, None, None]:
    """Fail a test whose refusal was caught before it could fail it."""
    outcome = yield
    report = outcome.get_result()
    refusals = item.stash.get(_REFUSALS, [])
    if refusals and report.passed and report.when != "teardown":
        report.outcome = "failed"
        report.longrepr = "\n".join(refusals) + "\n(the refusal was caught by the code under test)"
        refusals.clear()


@functools.lru_cache(maxsize=1)
def sops_can_decrypt() -> bool:
    """Whether this machine can actually decrypt the SOPS secrets.

    True on a workstation with the age key, false on a runner without it. Mirrors
    `_sops_available()` in toolkit/cli/sync.py, which already guards the drift
    check the same way — same question, so the same answer shape.

    Cached: decryption spawns `sops` and the answer cannot change mid-session.
    """
    if not shutil.which("sops"):
        return False

    # Import errors are NOT swallowed. A typo here would make this return False
    # forever, silently skipping the thirteen tests it guards on every machine —
    # which is exactly what happened while writing it (`toolkit.core.settings`
    # does not exist; the real module is `toolkit.config.settings`). A guard that
    # degrades to "always skip" is worse than no guard, because it reports green.
    from toolkit.config.settings import settings
    from toolkit.features.configuration import ConfigurationManager

    try:
        cm = ConfigurationManager("staging", settings.project_root)
        sops_file = cm.secrets_path / "staging.enc.yaml"
        return bool(sops_file.exists() and cm._decrypt_sops(sops_file))
    except Exception:
        # Only decryption failure lands here — the expected case on a runner
        # without the age key.
        return False


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip tests needing real SOPS material when it cannot be decrypted.

    Thirteen tests assert that a generator's output is coherent with the values
    in SOPS, so they need the age key rather than a fixture. They passed silently
    for as long as the suite ran only on workstations; the first CI run failed
    them with `assert ''` — the generator returning empty because nothing
    decrypted — which reads as a code defect and is not one.

    Skipping keeps that visible AND honest: a skip with this reason is CANNOT
    CHECK, which is not OK, and it appears in the summary rather than being
    deselected out of the count. The alternative — handing a test job the key
    that decrypts every production secret in a public repo — is a security
    decision, not a test-plumbing one, and is deliberately left to a human
    (the `SOPS_AGE_KEY` repo secret exists but no workflow uses it).
    """
    if sops_can_decrypt():
        return
    skip = pytest.mark.skip(
        reason="CANNOT CHECK: SOPS cannot decrypt here (no age key), so this "
        "asserts against empty input rather than against the real values. Not a "
        "pass — run `make test` on a workstation to actually exercise it."
    )
    for item in items:
        if "requires_sops" in item.keywords:
            item.add_marker(skip)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add custom CLI options for all tests."""
    parser.addoption(
        "--env",
        default="dev",
        choices=["dev", "staging", "prod"],
        help="Target environment for e2e tests (default: dev)",
    )


@pytest.fixture(scope="session")
def env(request: pytest.FixtureRequest) -> str:
    """Target environment from --env CLI option."""
    return request.config.getoption("--env")  # type: ignore[return-value]
