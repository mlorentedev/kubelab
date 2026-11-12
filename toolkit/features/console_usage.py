"""Read the console's A8 usage counter (ADR-066 A8, #3341).

`console_usage` (#3334) holds one row per operator identity and UTC day on which the
console page was opened. The Vikunja retirement (#2587) waits until the console was
opened on at least `GATE_DAYS` of `WINDOW_DAYS` consecutive days. That gate is read
here, from the rows, through a read-only transaction in the Postgres container: the
same path the restore drill counts rows through (`postgres_drill`).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Optional

WINDOW_DAYS = 14
GATE_DAYS = 5

# READ ONLY makes the server refuse any write in the transaction, whatever the role can do.
QUERY = "BEGIN READ ONLY;\nSELECT identity, day FROM console_usage ORDER BY identity, day;\nCOMMIT;\n"

Run = Callable[..., "tuple[int, str, str]"]


class ReadError(RuntimeError):
    """The counter could not be read; never reported as zero days of use."""


@dataclass(frozen=True)
class Window:
    start: Optional[date]
    days_used: int

    @property
    def holds(self) -> bool:
        return self.days_used >= GATE_DAYS


def best_window(days: list[date]) -> Window:
    """The run of `WINDOW_DAYS` consecutive days holding the most days of use.

    A best window always starts on a day of use, so only those starts are tried.
    """
    used = sorted(set(days))
    best = Window(None, 0)
    for i, start in enumerate(used):
        end = start + timedelta(days=WINDOW_DAYS - 1)
        count = sum(1 for d in used[i:] if d <= end)
        if count > best.days_used:
            best = Window(start, count)
    return best


def parse_rows(text: str) -> dict[str, list[date]]:
    """`identity|YYYY-MM-DD` lines, as `psql -At -F '|'` prints them."""
    rows: dict[str, list[date]] = {}
    for line in text.splitlines():
        if not line or line in ("BEGIN", "COMMIT"):
            continue
        identity, sep, day = line.partition("|")
        if not sep or not identity:
            raise ValueError(f"not an identity|day row: {line!r}")
        rows.setdefault(identity, []).append(date.fromisoformat(day))
    return rows


def _default_run(argv: list[str], stdin: Optional[str] = None) -> tuple[int, str, str]:
    proc = subprocess.run(argv, input=stdin, capture_output=True, text=True, encoding="utf-8", check=False)
    return proc.returncode, proc.stdout, proc.stderr


def report(
    env: str,
    *,
    kubeconfig: str,
    database: str,
    namespace: str = "kubelab",
    deployment: str = "postgres",
    container: str = "postgres",
    run: Run = _default_run,
) -> list[str]:
    """One line per identity: its best window and whether the A8 gate holds."""
    argv = [
        "kubectl", "--kubeconfig", kubeconfig, "exec", "-i", "-n", namespace, f"deploy/{deployment}",
        "-c", container, "--", "sh", "-c", 'psql -U "$POSTGRES_USER" -At -F "|" -v ON_ERROR_STOP=1 -f - -d "$1"',
        "sh", database,
    ]  # fmt: skip
    rc, out, err = run(argv, stdin=QUERY)
    if rc != 0:
        raise ReadError(f"{env}: cannot read console_usage: {err.strip()[:200]}")
    rows = parse_rows(out)
    if not rows:
        return [f"{env}: no day of console use recorded yet; the A8 gate does not hold"]
    lines = []
    for identity, days in sorted(rows.items()):
        w = best_window(days)
        verdict = "holds" if w.holds else "not yet"
        lines.append(
            f"{env}: {identity}: {w.days_used} of {WINDOW_DAYS} days from {w.start} "
            f"({len(days)} days recorded, last {max(days)}); A8 gate ({GATE_DAYS} of {WINDOW_DAYS}) {verdict}"
        )
    return lines
