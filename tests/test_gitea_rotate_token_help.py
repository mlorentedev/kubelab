"""`gitea rotate-token --token` names every rotatable credential.

The help said `bot or admin` after the reviewer's and the agent's tokens became
rotatable, so it hid two of the four values the option accepts. It is derived
from `ROTATABLE_TOKENS` now; this pins that no key is left out.
"""

from __future__ import annotations

from typer.testing import CliRunner

from toolkit.cli.services import app
from toolkit.features.gitea_tokens import ROTATABLE_TOKENS


def test_the_help_names_every_rotatable_token() -> None:
    result = CliRunner().invoke(app, ["gitea", "rotate-token", "--help"], env={"COLUMNS": "200"})

    assert result.exit_code == 0, result.output
    for label in ROTATABLE_TOKENS:
        assert label in result.output, f"--token help omits {label!r}"
    assert "agent" in ROTATABLE_TOKENS and "reviewer" in ROTATABLE_TOKENS
