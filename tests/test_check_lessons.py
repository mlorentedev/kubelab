"""check-lessons finds an indexed lesson in an index larger than a pipe buffer (#2765).

The script compared each lesson against the index's targets with
`printf '%s\n' "$targets" | grep -qxF`. `grep -q` exits at its first match and
closes the pipe; when `printf` is still writing, it takes SIGPIPE, and under
`pipefail` the pipeline fails although the match was found. So a lesson listed
early in a large index read as missing, intermittently: the writer races grep.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check-lessons.sh"

# The writer always fails only past twice the pipe buffer (64 KiB on Linux): grep
# reads at most one buffer before it matches and exits, the writer refills one more,
# and whatever is left meets a closed pipe. Below that it is a race the writer can win.
PIPE_BUFFER = 64 * 1024
LESSONS = 600
SLUG = "a-long-slug-" * 19  # names up to 242 bytes, inside the 255 a filename allows


def test_a_lesson_early_in_a_large_index_is_found(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    shutil.copy2(SCRIPT, tmp_path / "scripts/check-lessons.sh")
    category = tmp_path / "docs/lessons/category"
    category.mkdir(parents=True)
    names = [f"lesson-{number}-{SLUG}.md" for number in range(1, LESSONS + 1)]
    rows = []
    for number, name in enumerate(names, 1):
        (category / name).write_text("# lesson\n", encoding="utf-8")
        rows.append(f"| {number} | [lesson]({name}) | 2026-10-30 |")
    (category / "_index.md").write_text(
        "| # | Lesson | Date |\n|---|---|---|\n" + "\n".join(rows) + "\n", encoding="utf-8"
    )
    (tmp_path / "docs/lessons/_index.md").write_text("[category](category/_index.md)\n", encoding="utf-8")
    # What the script pipes is the index's link targets, not its rows.
    assert len("\n".join(names)) > 2 * PIPE_BUFFER

    # `which`, not the bare name: CreateProcess searches System32 before PATH, so a bare
    # "bash" is C:\Windows\System32\bash.exe (the WSL launcher) on a seat that has WSL —
    # and that launcher drops every argument after the command and cannot open a C:/ path,
    # so bash answered 127 for a file that was there (TOOL-132). `as_posix` because MSYS
    # bash opens C:/x but not C:\x.
    script = (tmp_path / "scripts/check-lessons.sh").as_posix()
    result = subprocess.run(
        [shutil.which("bash") or "bash", script], capture_output=True, text=True
    )

    assert result.returncode == 0, result.stdout[-600:] + result.stderr[-600:]
    assert f"OK ({LESSONS} lessons)" in result.stdout


# One `|` or `|&`: after `||` the reader runs only when the writer has already failed.
PIPE = re.compile(r"(?<!\|)\|&?(?!\|)")
# What ends the command a pipe feeds.
COMMAND_END = re.compile(r";|&&|\|\||\||\)")


def _stops_early(command: str) -> bool:
    """`head`, or a `grep` told to stop at a match: `-q` (`--quiet`, `--silent`) or
    `-m N` (`--max-count`), in any option cluster or position before `--`."""
    words = COMMAND_END.split(command, maxsplit=1)[0].split()
    if words[:1] == ["head"]:
        return True
    if words[:1] != ["grep"]:
        return False
    for word in words[1:]:
        if word == "--":
            break
        if re.fullmatch(r"--(?:quiet|silent|max-count)(?:=.*)?|-[A-Za-z]*[qm].*", word):
            return True
    return False


def _early_readers(text: str) -> list[int]:
    """The lines where a pipe into a reader that stops early starts. A command
    continued by a trailing `\\` or a trailing pipe is read as one."""
    found, start, command = [], 0, ""
    for number, line in enumerate(text.splitlines(), 1):
        if not command and line.lstrip().startswith("#"):
            continue
        start, command = start or number, f"{command} {line.rstrip()}"
        if command.endswith("\\"):
            command = command[:-1]
        elif not re.search(r"(?<!\|)\|&?$", command):
            if any(_stops_early(after) for after in PIPE.split(command)[1:]):
                found.append(start)
            start, command = 0, ""
    return found


def test_no_repository_script_pipes_into_a_reader_that_stops_early() -> None:
    """The scripts here read inputs that grow with the repository, so a writer that
    fits the pipe buffer today need not tomorrow. Under `pipefail` the pipe then fails
    when the reader has found what it wanted."""
    found = [
        f"{path.name}:{number}"
        for path in sorted(SCRIPT.parent.glob("*.sh"))
        if "pipefail" in (text := path.read_text(encoding="utf-8"))
        for number in _early_readers(text)
    ]
    assert not found, f"feed the reader a here-string or a file instead: {found}"


def test_the_guard_spawns_no_process_per_lesson() -> None:
    """An external command per lesson file is one fork per lesson: free on Linux, ~0.22s
    each under MSYS (measured), so the pre-commit hook that runs this script read as a hung
    commit on Windows (723 lessons, ~3 minutes, no output — TOOL-132). Both offenders were
    of this shape: `$(basename "$f")` to strip the path, and `grep -qxF -- "$name" <<<
    "$targets"` to test membership. The defect is invisible on the platform CI runs on, so
    the assertion is on the source, not on a measurement."""
    text = SCRIPT.read_text(encoding="utf-8")
    # A variable naming the lesson being iterated...
    per_lesson = re.compile(r"\$\{?(?:f|file|name|lesson)\b")
    # ...fed to something that costs a process.
    external = re.compile(r"basename|\$\(|-exec|\bgrep\b|\bsed\b|\bawk\b|\bwc\b")
    offenders = [
        f"scripts/check-lessons.sh:{number}"
        for number, line in enumerate(text.splitlines(), 1)
        if "-exec basename" in line or (per_lesson.search(line) and external.search(line))
    ]
    assert not offenders, f"answer it once for the directory instead: {offenders}"


def test_the_guard_reads_every_spelling_of_a_reader_that_stops_early() -> None:
    early = [
        'printf \'%s\\n\' "$targets" | grep -qxF -- "$name"',  # the line #2765 fixed
        "x | grep -q y",
        "x | grep -E -q y",
        'x | grep -e "$pattern" -q y',
        'x | grep "$name" -q',
        "x | grep -m1 y",
        "x | grep --quiet y",
        "x | grep --max-count 1 y",
        "x | grep --max-count=1 y",
        "x |& grep -q y",
        "x | head -1",
        "x \\\n  | grep -q y",
        "x | \\\n  grep -q y",
        "x |\n  grep -q y",
    ]
    late = [
        "a || grep -q b",
        "a ||\n  grep -q b",
        "x | grep -c y",
        "x | grep -x pattern-with-m",
        "x | grep -c y; grep -q z file",
        "x | grep -c -- -q",
        "x | headers",
        "grep -q y file",
        "# x | grep -q y",
    ]
    assert [text for text in early if not _early_readers(text)] == []
    assert [text for text in late if _early_readers(text)] == []
