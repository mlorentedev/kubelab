#!/usr/bin/env python3
"""What the operator talked about with the agent in the last 24 hours (spec AI-012 AC5).

The data for the daily session record. It runs inside the gateway before the job's
turn, because the agent cannot list its own sessions: its tools see the vault, and
`state.db` is in HERMES_HOME. Hermes injects this output into the turn, and cuts it
at 8000 characters, so the report stays under that.

With nothing to record the last line is {"wakeAgent": false}, and Hermes skips the
turn, the delivery and the token spend.
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

WINDOW = 24 * 3600
# Sessions the agent or the scheduler started themselves: the job's own run would
# otherwise be the activity it records.
AUTOMATED = ("cron", "subagent", "tool", "recovered", "kanban")
MESSAGE_CHARS = 500
BUDGET = 7000
NOTHING = '{"wakeAgent": false}'
# A credential pasted into a chat must not be copied into the vault.
SECRETS = re.compile(
    r"sk-[A-Za-z0-9_-]{20,}|xox[a-z]-[A-Za-z0-9-]{10,}|gh[pousr]_[A-Za-z0-9]{30,}"
    r"|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|authelia_(?:at|rt|ac)_[A-Za-z0-9._-]+"
    r"|(?i:bearer)\s+[A-Za-z0-9._~+/-]{20,}"
    r"|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
)


def _clean(text: object) -> str:
    one_line = " ".join(SECRETS.sub("[redacted]", str(text)).split())
    return one_line if len(one_line) <= MESSAGE_CHARS else one_line[:MESSAGE_CHARS] + "..."


def _connect(db_path: Path) -> sqlite3.Connection:
    """Read only: a report must not be able to change the gateway's session store."""
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def report(db_path: Path, now: float) -> str:
    if not db_path.exists():
        return f"No conversation database yet.\n{NOTHING}"
    marks = ",".join("?" for _ in AUTOMATED)
    with _connect(db_path) as db:
        rows = db.execute(
            f"""SELECT s.id, s.source, s.title, s.started_at, m.role, m.content
                FROM messages m JOIN sessions s ON s.id = m.session_id
                WHERE m.timestamp >= ? AND s.source NOT IN ({marks})
                  AND m.role IN ('user', 'assistant') AND m.active = 1
                  AND m.content IS NOT NULL AND TRIM(m.content) != ''
                ORDER BY s.started_at, s.id, m.timestamp""",  # noqa: S608 (placeholders only)
            (now - WINDOW, *AUTOMATED),
        ).fetchall()
    if not rows:
        return f"No conversation with the operator in the last 24 hours.\n{NOTHING}"

    stamp = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"Conversations with the operator in the 24 hours before {stamp}.", ""]
    used = sum(len(line) + 1 for line in lines)
    seen: set[str] = set()
    for index, (sid, source, title, started, role, content) in enumerate(rows):
        entry = f"- {role}: {_clean(content)}"
        header = []
        if sid not in seen:
            opened = datetime.fromtimestamp(started, UTC).strftime("%H:%M")
            header = ["", f"## {opened} UTC, {source}, {_clean(title) if title else 'untitled'}"]
        cost = sum(len(line) + 1 for line in [*header, entry])
        if used + cost > BUDGET:
            left = len(rows) - index
            lines.append(f"({left} more message{'s' if left != 1 else ''} not shown)")
            break
        seen.add(sid)
        lines += [*header, entry]
        used += cost
    return "\n".join(lines)


def main() -> int:
    path = Path(os.environ.get("HERMES_HOME", "/opt/data")) / "state.db"
    try:
        print(report(path, time.time()))
    except sqlite3.Error as error:
        print(f"session-activity: cannot read {path.name}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
