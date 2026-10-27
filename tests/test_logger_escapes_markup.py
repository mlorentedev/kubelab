"""The logger prints a message as written; it never reads it as rich markup.

`PlatformLogger` built its line by interpolating the message into a markup string, so any
`[`...`]` in the message was parsed as a tag. `toolkit tools mutate` relays pytest's output
one line at a time through `logger.info(line)`, and pytest prints `[/...]` and parametrize ids
such as `test_x[param-1]`: a closing tag that matches nothing raised `MarkupError`, and an
opening or unknown one was swallowed with its text, silently.

The fix is in the logger and not in each caller, because the text comes from whatever the
caller is reporting (a subprocess's output, an exception, a file name) and cannot be trusted
to be free of brackets.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from rich.console import Console

from toolkit.core import logging as toolkit_logging
from toolkit.core.logging import logger

#: Short on purpose: rich wraps at 80 columns when stderr is not a terminal, and these are
#: compared whole. The last three are the ways escaping itself can go wrong: a trailing
#: backslash that escaping doubles, a backslash that escapes a tag, and text that is not
#: markup at all but that rich would turn into emoji (`:cd:` is a disc, `:tada:` a party).
HOSTILE_MESSAGES = [
    "[/blue] x",
    "[bold]x",
    "t.py::test_x[param-1] FAILED",
    "[red]y[/red] z",
    "a [/] b",
    "ends in a backslash\\",
    "ends in two backslashes\\\\",
    "\\[bold]x",
    "[#ff0000]x",
    "mac a0:cd:11 and 12:30:45 :tada:",
]

LEVELS = ["info", "success", "warning", "error"]


def _call(method: str, message: str) -> None:
    """Call a level method; `critical` exits, which is part of its contract."""
    if method == "critical":
        with pytest.raises(SystemExit):
            logger.critical(message)
    else:
        getattr(logger, method)(message)


@pytest.mark.parametrize("message", HOSTILE_MESSAGES)
@pytest.mark.parametrize("method", [*LEVELS, "critical"])
def test_a_message_with_brackets_is_neither_rejected_nor_shortened(
    method: str, message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    _call(method, message)

    assert capsys.readouterr().err == f"[{method.upper()}] {message}\n"


@pytest.mark.parametrize("method", [*LEVELS, "critical"])
def test_the_level_label_is_still_printed(method: str, capsys: pytest.CaptureFixture[str]) -> None:
    _call(method, "[bold]x")

    assert capsys.readouterr().err.startswith(f"[{method.upper()}] ")


@pytest.mark.parametrize("method", ["section", "subsection"])
def test_a_title_with_brackets_is_printed_as_written(method: str, capsys: pytest.CaptureFixture[str]) -> None:
    # 63 characters, so `section` has no padding to put between the title and its end.
    title = "deploy [/blue] [bold]x" + "." * 40 + "\\"

    getattr(logger, method)(title)

    # One trailing backslash, not the two that escaping a text which ends in one would print.
    err = capsys.readouterr().err
    assert title in err
    assert title + "\\" not in err


def test_a_message_that_is_not_a_string_is_printed(capsys: pytest.CaptureFixture[str]) -> None:
    """The callers' type hint says str; an exception object arrives all the same."""
    logger.error(ValueError("boom [/x]"))  # type: ignore[arg-type]

    assert "boom [/x]" in capsys.readouterr().err


def _styled_stderr(monkeypatch: pytest.MonkeyPatch) -> io.StringIO:
    """Point the logger at a console that emits ANSI styles, as a terminal would.

    `highlight=False` keeps rich's automatic highlighter (which bolds every bracket it
    sees) out of the output, so the only styles left are the ones the logger asked for.
    """
    buffer = io.StringIO()
    monkeypatch.setattr(
        toolkit_logging,
        "err_console",
        Console(file=buffer, force_terminal=True, color_system="standard", width=80, highlight=False),
    )
    return buffer


@pytest.mark.parametrize(
    ("method", "ansi"),
    [("info", "\x1b[34m"), ("success", "\x1b[32m"), ("warning", "\x1b[33m"), ("error", "\x1b[31m")],
)
def test_the_label_keeps_its_colour_and_the_message_takes_none_from_its_brackets(
    method: str, ansi: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    buffer = _styled_stderr(monkeypatch)

    getattr(logger, method)("[bold]x")

    out = buffer.getvalue()
    assert f"{ansi}[{method.upper()}]" in out
    assert "[bold]x" in out
    assert "\x1b[1m" not in out, "the message's [bold] was applied as a style"


def test_markup_is_honoured_only_when_the_caller_asks_for_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """The one deliberate use: `toolkit services list` colours a heading."""
    buffer = _styled_stderr(monkeypatch)

    logger.info("[cyan]HEADING[/cyan]", markup=True)

    out = buffer.getvalue()
    assert "\x1b[36mHEADING" in out
    assert "[cyan]" not in out


@pytest.mark.parametrize("method", [*LEVELS, "critical"])
def test_the_default_is_to_print_the_text_as_written(method: str, monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = _styled_stderr(monkeypatch)
    call: Callable[..., Any] = getattr(logger, method)

    if method == "critical":
        with pytest.raises(SystemExit):
            call("[cyan]HEADING[/cyan]")
    else:
        call("[cyan]HEADING[/cyan]")

    out = buffer.getvalue()
    assert "[cyan]HEADING[/cyan]" in out
    assert "\x1b[36m" not in out


def test_the_services_listing_still_colours_its_headings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`toolkit services list` is the one caller that writes markup into the logger on purpose.

    Escaping by default would have turned its `[cyan]APPS[/cyan]` into literal text, so it
    opts in with `markup=True`; the project's other callers pass plain text.
    """
    from toolkit.cli import services

    (tmp_path / "apps" / "api").mkdir(parents=True)
    monkeypatch.setattr(services, "get_settings", lambda: SimpleNamespace(project_root=tmp_path))
    buffer = _styled_stderr(monkeypatch)

    services.list_components()

    out = buffer.getvalue()
    assert "\x1b[36mAPPS" in out
    assert "[cyan]" not in out
