"""Under `pipefail`, a pipe into `grep -q` can report a match as a miss (#3185).

`grep -q` exits at its first match and closes the pipe. A producer that still
has a line to write gets SIGPIPE and exits 141, and `pipefail` makes that the
pipeline's status. bash's `printf` writes line by line into a pipe, so
`printf '%s\\n' "$LIST" | grep -qx item` fails whenever `item` is not the last
line and the scheduler lets grep run before printf finishes. Measured on
ubuntu:24.04 with eight loops in parallel: 5 misreads in 16000.

It surfaced as a flaky test of the maintenance timer, and the timer itself had
it: a held package read as unheld, the timer recorded the hold as its own and
released it after its run, undoing the provision's hold on the CI engine.

The fix is to let grep read its whole input (`grep ... >/dev/null`), so the
producer never writes into a closed pipe.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Shipped code only, CI workflows included: their steps set pipefail
# themselves (`set -euo pipefail`), and a quiet grep there misread a label it
# had just written (#3227). specs/ holds one-off probes from closed work.
ROOTS = ("infra", "toolkit", "edge", "scripts", ".github/workflows")
QUIET_AFTER_PIPE = re.compile(r"\|\s*grep\s+(?:-[A-Za-z]*q[A-Za-z]*|--quiet|--silent)\b")


def _tracked() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--", *ROOTS, "Makefile"],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    return [REPO / line for line in out.splitlines() if line]


def _offenders() -> list[str]:
    found = []
    for path in _tracked():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        # The Makefile sets pipefail once in .SHELLFLAGS, for every recipe.
        if "pipefail" not in text:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if QUIET_AFTER_PIPE.search(line):
                found.append(f"{path.relative_to(REPO)}:{number}: {line.strip()}")
    return found


def test_no_pipefail_script_pipes_into_a_quiet_grep() -> None:
    offenders = _offenders()
    assert not offenders, (
        "a pipe into `grep -q` under pipefail can read a match as a miss; "
        "use `grep ... >/dev/null` so grep reads all of its input:\n" + "\n".join(offenders)
    )


def _status(pipeline: str) -> int:
    return subprocess.run(["bash", "-o", "pipefail", "-c", pipeline], check=False).returncode


def test_the_mechanism_a_quiet_grep_fails_a_pipeline_that_matched() -> None:
    """Deterministic form of the race: the producer keeps writing after grep has matched.

    Several late writes, so a grep slow to start on a loaded runner still exits
    before the last of them.
    """
    producer = "{ echo held; for _ in 1 2 3 4 5; do sleep 0.2; echo other; done; }"
    assert _status(f"{producer} | grep -qx held") == 141
    assert _status(f"{producer} | grep -x held >/dev/null") == 0


def test_the_detector_sees_the_files_and_matches_the_known_forms() -> None:
    """A guard that scans nothing, or matches nothing, reports the repository clean."""
    scanned = {str(p.relative_to(REPO)) for p in _tracked()}
    assert "Makefile" in scanned
    assert "infra/ansible/roles/node_maintenance/templates/kubelab-maintenance.sh.j2" in scanned
    assert ".github/workflows/pr-agent.yml" in scanned
    for bad in (
        """if ! printf '%s\\n' "$HELD_BEFORE" | grep -qx 'docker-ce'; then""",
        """tail -n 5 "$f" | grep -qxF -- 'done'""",
        """kubectl auth can-i list pods | grep -q "yes" ||""",
        "cmd | grep --quiet x",
    ):
        assert QUIET_AFTER_PIPE.search(bad), bad
    for good in ("""printf '%s\\n' "$L" | grep -xF 'x' >/dev/null""", "grep -q x file", "a && grep -q x f"):
        assert not QUIET_AFTER_PIPE.search(good), good
