"""#3443: the console frontend's host is `infra.forge.console_domain`, declared once.

The api answers `/console` only for the host it is told (`INFRA_FORGE_CONSOLE_DOMAIN`), and the
frontend's route must serve that same host. Two declarations of it is how they drift, and the api
would then 404 every data call behind a route that looked right. `apps.platform.console.domain`
is therefore derived, and ASSIGNED rather than defaulted: a stale value in an env file must not
win over the host the api is told.
"""

from __future__ import annotations

import pytest

from toolkit.features.configuration import ConfigurationManager

derive = ConfigurationManager._inject_console_domain_derivation


def _config(domain: str | None, console: dict | None) -> dict:
    config: dict = {"infra": {"forge": {}}, "apps": {"platform": {}}}
    if domain is not None:
        config["infra"]["forge"]["console_domain"] = domain
    if console is not None:
        config["apps"]["platform"]["console"] = console
    return config


def test_the_app_domain_is_the_declared_console_domain() -> None:
    config = _config("console.example.test", {"name": "console"})
    derive(config)
    assert config["apps"]["platform"]["console"]["domain"] == "console.example.test"


def test_a_stale_domain_in_an_env_file_does_not_win() -> None:
    config = _config("console.example.test", {"domain": "stale.example.test"})
    derive(config)
    assert config["apps"]["platform"]["console"]["domain"] == "console.example.test"


@pytest.mark.parametrize("domain", [None, ""])
def test_no_declared_host_leaves_the_app_without_a_domain(domain: str | None) -> None:
    """No host means no route: the generator skips an app with no domain, so the console is
    served nowhere rather than on a guess."""
    config = _config(domain, {"name": "console"})
    derive(config)
    assert "domain" not in config["apps"]["platform"]["console"]


def test_an_env_that_declares_no_console_app_gains_none() -> None:
    config = _config("console.example.test", None)
    derive(config)
    assert "console" not in config["apps"]["platform"]


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_the_real_config_gives_the_frontend_the_host_the_api_is_told(env: str) -> None:
    """Read through the loader every generator uses, so it fails if the derivation is not wired in."""
    env_vars = ConfigurationManager(env).get_env_vars()
    told = env_vars["INFRA_FORGE_CONSOLE_DOMAIN"]
    assert told, f"{env}: the api is told no console host"
    assert env_vars["APPS_PLATFORM_CONSOLE_DOMAIN"] == told
