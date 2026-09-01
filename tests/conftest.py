"""Root conftest — shared pytest configuration and fixtures."""

import functools
import os
import shutil

import pytest


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
    del config  # the hook's signature, not something this needs
    for var in ("FORCE_COLOR", "CLICOLOR_FORCE"):
        os.environ.pop(var, None)


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
