"""The logger's diagnostics go to stderr, so stdout carries only a command's data (#2536).

`promote-prod.yml` pipes `toolkit product app-for-event --json` into `jq`. On a hosted
runner, which has no sops, building the settings printed `[WARNING] SOPS is not
installed` on stdout before the object, and `jq` failed on the `]` of `[WARNING]`.
#2526 fixed that one caller. This holds the class: whatever a command logs on the way,
its stdout is still its answer.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

from toolkit.core.logging import logger


@pytest.mark.parametrize("method", ["info", "success", "warning", "error", "section", "subsection"])
def test_a_diagnostic_never_reaches_stdout(method: str, capsys: pytest.CaptureFixture[str]) -> None:
    getattr(logger, method)("diagnostic-marker")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "diagnostic-marker" in captured.err


def test_a_critical_goes_to_stderr_and_exits(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        logger.critical("diagnostic-marker")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "diagnostic-marker" in captured.err


def test_the_standard_logging_handler_writes_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    logging.getLogger("platform-cli").warning("diagnostic-marker")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "diagnostic-marker" in captured.err


def test_the_console_a_command_prints_its_data_on_stays_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    """Tables, diffs and passed-through command output are the answer, not a diagnostic."""
    logger.console.print("data-marker")

    captured = capsys.readouterr()
    assert "data-marker" in captured.out
    assert captured.err == ""


def test_stdout_is_one_json_object_when_building_the_settings_warns(tmp_path: Path) -> None:
    """A fresh interpreter with no sops on PATH, which is a hosted runner's case."""
    script = "from toolkit.config.settings import get_settings; get_settings(); print('{\"ok\": true}')"
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={"PATH": str(Path(sys.executable).parent)},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert "SOPS is not installed" in result.stderr
    assert json.loads(result.stdout) == {"ok": True}
