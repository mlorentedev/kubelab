"""Cross-platform-safe I/O for the toolkit (TOOL-020)."""

import sys
from pathlib import Path


def force_utf8_stdio() -> None:
    """Reconfigure stdout/stderr to UTF-8, tolerating streams that can't.

    Windows' default console codepage (cp1252) can't encode characters like
    ``→`` used in bare ``print()`` calls, raising ``UnicodeEncodeError``
    before the caller even gets to log an error. Called once at ``toolkit``
    import time; safe to call again (e.g. in tests after monkeypatching
    ``sys.stdout``/``sys.stderr``).
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def write_text_lf(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` as UTF-8 with LF-only line endings.

    ``Path.write_text()`` with no ``newline=`` translates ``\\n`` to
    ``os.linesep`` on write, so the same generator emits CRLF on Windows and
    LF on Linux/CI — a byte difference the sync drift comparator then reports
    as false SSOT drift. Every toolkit generated-file writer must go through
    this helper instead of calling ``write_text`` directly.
    """
    path.write_text(content, encoding="utf-8", newline="\n")
