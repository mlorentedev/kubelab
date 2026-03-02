"""Root conftest — shared pytest configuration and fixtures."""

import pytest


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
