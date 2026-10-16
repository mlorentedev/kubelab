#!/usr/bin/env python3
"""hermes-kubelab's daily health and consumption digest (spec AI-012 AC5).

A no-agent job: Hermes delivers this script's stdout to Slack as it is, and a script
that prints nothing sends nothing. So it always prints: a stopped gateway, an
unreachable Docker or a missing database each become a line of the report, never
an empty message.

It runs in the gateway, which sees `HERMES_HOME` and the Docker socket (the sandbox
containers are started through it) and nothing of the host or the vault. The usage
comes from `session_model_usage`, which the gateway writes; nothing here calls a
provider.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

GATEWAY = "hermes-kubelab"
SIDECAR = "hermes-kubelab-tailscale"
DISK_LOW = 0.15  # free fraction below which the disk is called low
FALLBACK_PROVIDER = "anthropic"
MAX_LINES = 40


def _connect(db_path: Path) -> sqlite3.Connection:
    """Read only: a report must not be able to change the gateway's session store."""
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _containers() -> list[tuple[str, str, str]] | None:
    """(name, state, status) of every container the gateway's daemon knows, or None."""
    try:
        done = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.State}}\t{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    rows = [line.split("\t") for line in done.stdout.splitlines() if line.strip()]
    return [(r[0], r[1], r[2] if len(r) > 2 else "") for r in rows if len(r) >= 2]


def _usage(db_path: Path, month_start: float) -> list[tuple] | None:
    """(model, provider, calls, tokens in, tokens out, cost) per model and provider this month.

    A row's cost is the larger of the actual and the estimate: Hermes writes 0.0 to the
    actual until a provider reconciles it, so the first non-null would hide the estimate.

    The table keeps one cumulative row per session, model and provider, with no per-event
    timestamp, so a session that straddles the month boundary counts whole in the later
    month. Measured on ace2 (2026-10-16, 43 rows since 2026-10-07): the longest session
    spanned 48 hours and none straddled a month, so the overstatement is bounded by one
    session's usage."""
    if not db_path.exists():
        return None
    with _connect(db_path) as db:
        return db.execute(
            """SELECT model, COALESCE(NULLIF(billing_provider, ''), 'unknown'),
                      SUM(api_call_count), SUM(input_tokens), SUM(output_tokens),
                      SUM(MAX(COALESCE(actual_cost_usd, 0), COALESCE(estimated_cost_usd, 0)))
               FROM session_model_usage WHERE last_seen >= ?
               GROUP BY 1, 2 ORDER BY 6 DESC, 4 DESC""",
            (month_start,),
        ).fetchall()


def _health(containers: list[tuple[str, str, str]] | None) -> list[str]:
    if containers is None:
        return ["Docker is unreachable from the gateway: container state unknown."]
    by_name = {name: (state, status) for name, state, status in containers}
    lines = []
    for name in (GATEWAY, SIDECAR):
        state, status = by_name.get(name, ("missing", ""))
        lines.append(f"{name}: {status}" if state == "running" else f"{name}: NOT running ({state} {status})".strip())
    sandboxes = [n for n, (state, _) in by_name.items() if state == "running" and n not in (GATEWAY, SIDECAR)]
    lines.append(f"{len(sandboxes)} sandbox{'' if len(sandboxes) == 1 else 'es'} running")
    return lines


def report(
    db_path: Path, now: float, containers: list[tuple[str, str, str]] | None, disk: tuple[int, int] | None
) -> str:
    when = datetime.fromtimestamp(now, UTC)
    month_start = datetime(when.year, when.month, 1, tzinfo=UTC).timestamp()
    health = _health(containers)
    head = f"hermes-kubelab {when:%Y-%m-%d %H:%M} UTC"
    # What is wrong goes first, so the message's preview is the problem.
    problems = [line for line in health if "NOT running" in line or "unreachable" in line]
    lines = [*problems, head, *(line for line in health if line not in problems)]

    if disk is None:
        lines.append("Disk: cannot be read (is the data directory there?)")
    else:
        total, free = disk
        flag = " (disk low)" if total and free / total < DISK_LOW else ""
        lines.append(f"Disk: {free / 1024**3:.1f} GB free of {total / 1024**3:.0f} GB{flag}")

    lines += ["", f"Usage, {when:%Y-%m} to date:"]
    try:
        usage = _usage(db_path, month_start)
    except sqlite3.Error as error:
        usage = None
        lines.append(f"  cannot read the usage ({error})")
    if usage is None:
        lines.append("  no usage database yet")
    elif not usage:
        lines.append("  no usage recorded this month")
    else:
        shown = usage[: MAX_LINES - len(lines)]
        for model, provider, calls, tin, tout, cost in shown:
            lines.append(
                f"  {model} / {provider}: {calls or 0} calls, in {tin or 0:,} out {tout or 0:,}, {cost or 0:.2f} USD"
            )
        if len(shown) < len(usage):
            lines.append(f"  ({len(usage) - len(shown)} more not shown)")
        fallback = sum(cost or 0 for _, provider, _, _, _, cost in usage if provider == FALLBACK_PROVIDER)
        lines.append(f"Fallback ({FALLBACK_PROVIDER}) spend this month: {fallback:.2f} USD")
    return "\n".join(lines)


def main() -> int:
    home = Path(os.environ.get("HERMES_HOME", "/opt/data"))
    try:
        usage = shutil.disk_usage(home)
        disk: tuple[int, int] | None = (usage.total, usage.free)
    except OSError:
        disk = None
    try:
        print(report(home / "state.db", time.time(), _containers(), disk))
    except Exception as error:  # noqa: BLE001 (whatever broke, the channel must hear it)
        print(f"hermes-kubelab digest FAILED: {type(error).__name__}: {error}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
