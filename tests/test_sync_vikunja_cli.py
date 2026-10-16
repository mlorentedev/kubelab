"""`toolkit sync vikunja` takes its credential from SOPS and from nowhere else (#1701, AC1)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from toolkit.cli import sync

TOKEN_KEY = "apps.services.core.vikunja.reconciler_api_token"
SECRET = "tk_" + "ab" * 20


def _config(token: str | None) -> dict[str, Any]:
    vikunja: dict[str, Any] = {
        "domain": "tasks.example.test",
        "projects": ["Bitacora"],
        "team": {"name": "kubelab", "right": "write", "members": ["superadmin"]},
    }
    if token is not None:
        vikunja["reconciler_api_token"] = token
    return {"apps": {"services": {"core": {"vikunja": vikunja}}, "auth": {"identities": {"superadmin": "manu"}}}}


def _invoke(config: dict[str, Any], args: list[str] | None = None, env: dict[str, str] | None = None):  # noqa: ANN202
    manager = MagicMock()
    manager.return_value.get_merged_config.return_value = config
    vikunja = config["apps"]["services"]["core"]["vikunja"]
    manager.return_value.get_secret_by_path.side_effect = lambda path: vikunja.get("reconciler_api_token")
    client = MagicMock()
    with (
        patch("toolkit.features.configuration.ConfigurationManager", manager),
        patch("toolkit.features.vikunja_client.VikunjaClient", client),
        patch("toolkit.features.vikunja_reconciler.VikunjaReconciler") as reconciler,
    ):
        reconciler.return_value.reconcile.return_value = MagicMock(changed=False)
        result = CliRunner().invoke(sync.app, ["vikunja", *(args or [])], env=env)
    return result, client


def test_the_token_comes_from_sops_with_nothing_exported() -> None:
    result, client = _invoke(_config(SECRET), env={"VIKUNJA_API_TOKEN": ""})
    assert result.exit_code == 0, result.output
    assert client.call_args.kwargs["api_token"] == SECRET
    assert client.call_args.kwargs["base_url"] == "https://tasks.example.test/api/v1"


def test_the_token_is_never_printed() -> None:
    result, _ = _invoke(_config(SECRET))
    assert SECRET not in result.output


def test_a_missing_token_fails_closed_naming_the_key() -> None:
    result, client = _invoke(_config(None))
    assert result.exit_code != 0
    assert TOKEN_KEY in result.output
    client.assert_not_called()


def test_an_empty_token_is_missing_too() -> None:
    result, client = _invoke(_config(""))
    assert result.exit_code != 0
    assert TOKEN_KEY in result.output
    client.assert_not_called()


def test_there_is_no_token_flag_so_argv_cannot_carry_one() -> None:
    result, client = _invoke(_config(SECRET), args=["--token", SECRET])
    assert result.exit_code != 0
    client.assert_not_called()


@pytest.mark.parametrize("env_value", ["tk_from_env"])
def test_an_exported_variable_does_not_override_sops(env_value: str) -> None:
    """One source, not a precedence chain: what ran is what SOPS says."""
    _, client = _invoke(_config(SECRET), env={"VIKUNJA_API_TOKEN": env_value})
    assert client.call_args.kwargs["api_token"] == SECRET
