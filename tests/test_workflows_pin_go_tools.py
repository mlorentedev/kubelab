"""A workflow must not install a Go tool at a floating version.

`go install <tool>@latest` follows the tool's newest release, which can demand
a newer Go than the job runs (GOTOOLCHAIN=local): govulncheck v1.8.0 moved to
Go 1.26 and failed every apps/api PR at the install step (#2389). The step only
runs when apps/api changes, so master never showed it.
"""

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
FLOATING = re.compile(r"go\s+install\s+\S+@(latest|master|main)\b")


def _go_install_lines():
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if "go install" in line:
                yield path.name, number, line.strip()


def test_workflows_install_go_tools_at_a_pinned_version():
    floating = [f"{n}:{i}: {line}" for n, i, line in _go_install_lines() if FLOATING.search(line)]
    assert not floating, "pin these to a version the job's Go can build:\n" + "\n".join(floating)


def test_the_detector_sees_a_floating_install():
    assert FLOATING.search("run: go install golang.org/x/vuln/cmd/govulncheck@latest")
    assert not FLOATING.search("run: go install golang.org/x/vuln/cmd/govulncheck@v1.7.0")
