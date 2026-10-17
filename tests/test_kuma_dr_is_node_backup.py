"""Uptime Kuma's backup is node_backup, not a copy on a workstation (#2243).

`toolkit monitoring backup` pulled kuma.db to a gitignored path on whichever
machine ran it (no schedule, no retention, nothing off that machine), and
`restore` pushed whatever stale file sat there over the live database. The real
backup is the `uptime_kuma_data` volume shipped to R2 by node_backup
(`backup.sources.rpi3`).
"""

import re
from pathlib import Path

from toolkit.cli.monitoring import app

ROOT = Path(__file__).resolve().parent.parent
RETIRED = re.compile(r"monitoring\s+(backup|restore)\b")
# Prose and shell docs a reader copies commands from.
DOCS = [*sorted((ROOT / "docs" / "runbooks").glob("*.md")), ROOT / "toolkit" / "README.md", ROOT / ".gitignore"]


def test_the_workstation_copy_commands_are_gone():
    names = {c.name or c.callback.__name__ for c in app.registered_commands}
    assert not names & {"backup", "restore"}, f"retired commands still registered: {names}"


def test_no_doc_sends_a_reader_to_the_retired_commands():
    hits = [f"{p.relative_to(ROOT)}:{n}: {line.strip()}"
            for p in DOCS if p.exists()
            for n, line in enumerate(p.read_text().splitlines(), 1)
            if RETIRED.search(line)]
    assert not hits, "docs still name retired commands:\n" + "\n".join(hits)


def test_the_runbook_points_at_node_backup_for_kuma():
    text = (ROOT / "docs" / "runbooks" / "monitoring.md").read_text()
    assert "make backup-node NODE=rpi3" in text
    assert "offsite-backup-restore.md" in text
