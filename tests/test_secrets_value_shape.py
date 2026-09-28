"""#1699 AC3: a secret can be present, audited, and the wrong kind of value.

The Vikunja API token in SOPS was an 86-character random string: what a
*generated* secret looks like. Vikunja mints its tokens as `tk_` plus 40 hex
characters. `secrets audit` reported it present, because presence was all it
asked, and every Vikunja call n8n made answered 401 (lesson-413).

A catalog entry may now declare the shape its value must have. `audit()` reports
a present value that does not match as MALFORMED, not present, and the CLI
fails on it. Shape is a floor, not the whole validation: `make n8n-probe`
exercises the token by consequence (#1699 AC2). Only key paths are ever
reported, never values.
"""

from __future__ import annotations

import re
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from toolkit.config.settings import PROJECT_ROOT
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.secrets_manager import _CATALOG_BY_KEY, SECRET_CATALOG, SecretsManager

VIKUNJA = "apps.services.automation.n8n.vikunja_api_token"
MINTED = "tk_" + "0123456789abcdef" * 2 + "01234567"
GENERATED = "x" * 86


def _vault(token: str) -> dict:
    return {"apps": {"services": {"automation": {"n8n": {"vikunja_api_token": token}}}}}


def _audit(token: str, env: str = "prod"):
    with patch.object(ConfigurationManager, "_decrypt_sops", return_value=_vault(token)):
        return SecretsManager(PROJECT_ROOT).audit(env)


def test_the_vikunja_token_declares_the_shape_vikunja_mints() -> None:
    spec = _CATALOG_BY_KEY[VIKUNJA]
    assert spec.value_pattern
    assert re.fullmatch(spec.value_pattern, MINTED)
    assert not re.fullmatch(spec.value_pattern, GENERATED)


def test_a_minted_token_is_present() -> None:
    result = _audit(MINTED)
    assert VIKUNJA in result.present
    assert VIKUNJA not in result.malformed


def test_a_generated_value_is_malformed_not_present() -> None:
    result = _audit(GENERATED)
    assert VIKUNJA in result.malformed
    assert VIKUNJA not in result.present
    assert VIKUNJA not in result.missing


def test_the_token_is_required_only_where_vikunja_runs() -> None:
    """Dev runs no Vikunja and no n8n pod reads the value there, so requiring it
    in dev is what kept an unused generated string in `dev.enc.yaml`."""
    assert _CATALOG_BY_KEY[VIKUNJA].envs == ("staging", "prod")


@pytest.mark.parametrize("spec", [s for s in SECRET_CATALOG if s.value_pattern], ids=lambda s: s.key_path)
def test_every_declared_pattern_compiles_and_rejects_the_empty_string(spec) -> None:
    compiled = re.compile(spec.value_pattern)
    assert not compiled.fullmatch("")


def test_the_cli_fails_on_a_malformed_secret_and_names_only_the_key() -> None:
    from toolkit.cli.secrets import app

    with (
        patch.object(ConfigurationManager, "_decrypt_sops", return_value=_vault(GENERATED)),
        patch("toolkit.cli.secrets._report_expiry"),
        patch("toolkit.features.secrets_manager.baselined_orphans", return_value=[]),
    ):
        outcome = CliRunner().invoke(app, ["audit", "--env", "prod"])
    assert outcome.exit_code == 1
    assert VIKUNJA in outcome.output
    assert GENERATED not in outcome.output
