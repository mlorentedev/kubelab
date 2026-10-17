"""Uptime Kuma's backup is node_backup, not a copy on a workstation (#2243).

`toolkit monitoring backup` pulled kuma.db to a gitignored path on whichever
machine ran it (no schedule, no retention, nothing off that machine), and
`restore` pushed whatever stale file sat there over the live database. The real
backup is the `uptime_kuma_data` volume shipped to R2 by node_backup
(`backup.sources.rpi3`).
"""

import re
import subprocess
from pathlib import Path

from toolkit.cli.monitoring import app

ROOT = Path(__file__).resolve().parent.parent
RETIRED = re.compile(r"monitoring\s+(backup|restore)\b")
THIS_FILE = Path(__file__).resolve()


def _tracked_text_files():
    """Every file git tracks (docs, Makefile, scripts, CHANGELOG), not a chosen subset."""
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    for name in out.decode().split("\0"):
        path = ROOT / name
        if name and path.resolve() != THIS_FILE and path.is_file():
            try:
                yield path, path.read_text()
            except UnicodeDecodeError:
                continue  # binary


def test_the_workstation_copy_commands_are_gone():
    names = {c.name or c.callback.__name__ for c in app.registered_commands}
    assert not names & {"backup", "restore"}, f"retired commands still registered: {names}"


def test_nothing_tracked_names_the_retired_commands():
    hits = [
        f"{p.relative_to(ROOT)}:{n}: {line.strip()}"
        for p, text in _tracked_text_files()
        for n, line in enumerate(text.splitlines(), 1)
        if RETIRED.search(line)
    ]
    assert not hits, "tracked files still name retired commands:\n" + "\n".join(hits)


def test_the_runbook_points_at_node_backup_for_kuma():
    text = (ROOT / "docs" / "runbooks" / "monitoring.md").read_text()
    assert "make backup-node NODE=rpi3" in text
    assert "offsite-backup-restore.md" in text


def test_what_the_runbook_points_at_exists():
    restore = (ROOT / "docs" / "runbooks" / "offsite-backup-restore.md").read_text()
    # The anchor the runbook links (#restoring--normal-case) must be a real heading,
    # and that section must cover SQLite consumers, which is what Kuma is.
    assert re.search(r"^## Restoring \u2014 normal case$", restore, re.M)
    section = restore.split("## Restoring \u2014 normal case", 1)[1]
    assert "Uptime Kuma" in section.split("\n## ", 1)[0]
    makefile = (ROOT / "Makefile").read_text()
    for target in ("backup-node", "backup-coverage"):
        assert re.search(rf"^{target}:", makefile, re.M), f"make {target} does not exist"
