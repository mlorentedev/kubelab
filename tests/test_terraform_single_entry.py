"""Nothing invokes `terraform` except the runner (TF-007 AC3).

TOOL-039 was a rendered `aws.tfvars`, carrying two credentials, left on disk
after a failed plan because one of nine hand-written Make recipes put its `rm`
on a line make never reached. The fix then was a harness that executed every
recipe with a stub `terraform`. The fix now is that there are no recipes: every
target is one line into `toolkit infra terraform run`, whose cleanup is a
`TemporaryDirectory` and is tested once (tests/test_terraform_runner.py).

That only holds while nothing goes around the runner, which is what this file
checks. A second caller would skip the secret handling, the cleanup, the `init`,
the plan guard and, from TF-007 PR 1b on, the remote backend and its
credentials, which is how a state file ends up written somewhere local again.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from toolkit.features import terraform_runner as tr

REPO = Path(__file__).resolve().parent.parent
MAKEFILE = (REPO / "Makefile").read_text(encoding="utf-8")
RUNNER = REPO / "toolkit" / "features" / "terraform_runner.py"

TERRAFORM_VERBS = (
    r"(init|plan|apply|destroy|output|untaint|taint|show|state|import|validate|fmt|refresh|console|force-unlock)"
)


def _recipe_lines() -> list[tuple[int, str]]:
    return [(n, line) for n, line in enumerate(MAKEFILE.splitlines(), 1) if line.startswith("\t")]


def test_no_make_recipe_runs_terraform() -> None:
    offenders = [
        f"Makefile:{n}: {line.strip()}"
        for n, line in _recipe_lines()
        if re.search(rf"(^|[\s;&|(`$]){{1}}terraform\s+(-chdir=\S+\s+)?{TERRAFORM_VERBS}\b", line)
        or "cd infra/terraform" in line
    ]
    assert not offenders, "call `$(_TF) <root> <action>` instead:\n" + "\n".join(offenders)


def _spawns_terraform(arg: ast.expr) -> bool:
    if isinstance(arg, (ast.List, ast.Tuple)) and arg.elts:
        first = arg.elts[0]
        return isinstance(first, ast.Constant) and first.value == "terraform"
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return bool(re.match(rf"terraform\s+(-chdir=\S+\s+)?{TERRAFORM_VERBS}\b", arg.value))
    return False


def _terraform_spawns(path: Path) -> list[str]:
    """Calls whose command is `terraform`: an argv list, or a shell string.

    Matched on the first argument of a call, so `services=("terraform",)` in
    the secret catalog is a service name and not a spawn.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        f"{path.relative_to(REPO)}:{node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and node.args and _spawns_terraform(node.args[0])
    ]


def test_no_toolkit_module_spawns_terraform_but_the_runner() -> None:
    offenders = [
        hit for path in sorted((REPO / "toolkit").rglob("*.py")) if path != RUNNER for hit in _terraform_spawns(path)
    ]
    assert not offenders, "go through toolkit.features.terraform_runner:\n" + "\n".join(offenders)


def test_the_runner_is_where_terraform_is_spawned() -> None:
    """Keeps the scan above honest: it must find the one real spawn."""
    assert _terraform_spawns(RUNNER)


TARGETS = {
    "tf-dns-plan": "dns plan",
    "tf-dns-apply": "dns apply",
    "tf-r2-plan": "r2 plan",
    "tf-r2-apply": "r2 apply",
    "tf-vps-firewall-plan": "vps-firewall plan",
    "tf-vps-firewall-apply": "vps-firewall apply",
    "tf-aws-plan": "aws plan",
    "tf-aws-apply": "aws apply",
    "tf-aws-destroy": "aws destroy",
    "tf-gcp-bootstrap-plan": "gcp-bootstrap plan",
    "tf-gcp-bootstrap-apply": "gcp-bootstrap apply",
    "tf-gcp-plan": "gcp plan",
    "tf-gcp-apply": "gcp apply",
    "tf-gcp-destroy": "gcp destroy",
    "gcp-killswitch-teardown": "gcp-killswitch-test destroy",
}


@pytest.mark.parametrize(("target", "call"), sorted(TARGETS.items()))
def test_each_terraform_target_is_one_runner_call(target: str, call: str) -> None:
    match = re.search(rf"^{re.escape(target)}:[^\n]*\n((?:\t.*\n?)+)", MAKEFILE, re.M)
    assert match, f"{target} is gone from the Makefile"
    lines = [line.strip() for line in match.group(1).splitlines()]
    assert len(lines) == 1 and lines[0].startswith(f"@$(_TF) {call}"), lines
    assert call.split()[0] in tr.ROOTS


def test_the_runner_macro_is_the_toolkit_command() -> None:
    assert re.search(r"^_TF = \$\(TOOLKIT\) infra terraform run$", MAKEFILE, re.M)


def test_there_is_deliberately_no_bootstrap_destroy() -> None:
    """The bootstrap root holds the project with `prevent_destroy`; a destroy
    target next to the weekly ones is one keystroke too close."""
    assert not re.search(r"^tf-gcp-bootstrap-destroy:", MAKEFILE, re.M)
