"""toolkit forces UTF-8 stdout/stderr at import time (TOOL-020).

Windows' default console codepage (cp1252) can't encode characters like
`→`, used in bare `print()` calls (e.g. sync_homepage_config.py) that
bypass the Rich-backed logger. Without a fix, that raises
UnicodeEncodeError before a sync even reaches comparison — the exact
crash reproduced in process-audit-2026-07-07.md.

pytest's own stdout capture is already UTF-8 regardless of the host OS, so
asserting on `sys.stdout.encoding` inside a normal test proves nothing about
the real bug. These tests manufacture a genuine cp1252 stream instead, so
the first test fails without the fix in place (real repro), and the second
proves `force_utf8_stdio()` neutralizes it.
"""

from __future__ import annotations

import io
import sys

import pytest

from toolkit.core.io import force_utf8_stdio


def _cp1252_stream() -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252", write_through=True)


class TestForceUtf8Stdio:
    def test_cp1252_stream_reproduces_the_crash(self) -> None:
        # Sanity check: proves the harness below exercises the real bug,
        # not an artifact of pytest's own (always-UTF-8) capture.
        stream = _cp1252_stream()
        with pytest.raises(UnicodeEncodeError):
            stream.write("template.name → output_name")

    def test_reconfigures_stdout_and_stderr_to_utf8(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "stdout", _cp1252_stream())
        monkeypatch.setattr(sys, "stderr", _cp1252_stream())

        force_utf8_stdio()

        assert sys.stdout.encoding.lower().replace("_", "-") in ("utf-8", "utf8")
        assert sys.stderr.encoding.lower().replace("_", "-") in ("utf-8", "utf8")

    def test_arrow_character_no_longer_crashes_after_fix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "stdout", _cp1252_stream())

        force_utf8_stdio()

        sys.stdout.write("template.name → output_name")  # must not raise

    def test_tolerates_streams_without_reconfigure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # e.g. some third-party capture/redirect wrappers don't support reconfigure().
        class NoReconfigure:
            pass

        monkeypatch.setattr(sys, "stdout", NoReconfigure())
        monkeypatch.setattr(sys, "stderr", NoReconfigure())

        force_utf8_stdio()  # must not raise
