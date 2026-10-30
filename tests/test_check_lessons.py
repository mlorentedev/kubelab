"""check-lessons finds an indexed lesson in an index larger than a pipe buffer (#2765).

The script compared each lesson against the index's targets with
`printf '%s\n' "$targets" | grep -qxF`. `grep -q` exits at its first match and
closes the pipe; when the targets exceed the pipe buffer, `printf` is still
writing, takes SIGPIPE, and under `pipefail` the pipeline fails although the
match was found. So a lesson listed early in a large index read as missing.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check-lessons.sh"

# Well past Linux's 64 KiB pipe buffer, so the writer is mid-write when grep exits.
LESSONS = 600
SLUG = "a-long-slug-" * 12


def test_a_lesson_early_in_a_large_index_is_found(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    shutil.copy2(SCRIPT, tmp_path / "scripts/check-lessons.sh")
    category = tmp_path / "docs/lessons/category"
    category.mkdir(parents=True)
    rows = []
    for number in range(1, LESSONS + 1):
        name = f"lesson-{number}-{SLUG}.md"
        (category / name).write_text("# lesson\n")
        rows.append(f"| {number} | [lesson]({name}) | 2026-10-30 |")
    (category / "_index.md").write_text("| # | Lesson | Date |\n|---|---|---|\n" + "\n".join(rows) + "\n")
    (tmp_path / "docs/lessons/_index.md").write_text("[category](category/_index.md)\n")
    assert len("\n".join(rows)) > 64 * 1024

    result = subprocess.run(["bash", str(tmp_path / "scripts/check-lessons.sh")], capture_output=True, text=True)

    assert result.returncode == 0, result.stdout[-600:] + result.stderr[-600:]
    assert f"OK ({LESSONS} lessons)" in result.stdout


# A reader that stops early: `grep -q`, `grep -m N`, `head`.
EARLY_EXIT = re.compile(r"\|\s*(?:grep\s+-[A-Za-z]*[qm]|head)\b")


def test_no_repository_script_pipes_into_a_reader_that_stops_early() -> None:
    """The scripts here read inputs that grow with the repository, so a writer that
    fits the pipe buffer today need not tomorrow. Under `pipefail` the pipe then fails
    when the reader has found what it wanted."""
    found = [
        f"{path.name}:{number}"
        for path in sorted(SCRIPT.parent.glob("*.sh"))
        if "pipefail" in (text := path.read_text(encoding="utf-8"))
        for number, line in enumerate(text.splitlines(), 1)
        if EARLY_EXIT.search(line) and not line.lstrip().startswith("#")
    ]
    assert not found, f"feed the reader a here-string or a file instead: {found}"
