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


# A terraform command inside any string: `terraform plan`, `'terraform apply'`,
# `/usr/local/bin/terraform destroy`, `bash -c "terraform init"`.
COMMAND_IN_TEXT = re.compile(rf"(^|[\s'\"/;&|(`]){{1}}terraform\s+(-chdir=\S+\s+)?{TERRAFORM_VERBS}\b")


def _is_terraform_binary(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and Path(node.value).name == "terraform"


def _is_command_list(node: ast.expr) -> bool:
    """`["terraform", <verb or anything computed>, ...]`, assigned or passed.

    `["terraform", "traefik"]` (a list of service names) is not one: every
    element after the first is a literal that is neither a verb nor a flag.
    """
    if not isinstance(node, (ast.List, ast.Tuple)) or len(node.elts) < 2 or not _is_terraform_binary(node.elts[0]):
        return False
    return any(
        not (isinstance(e, ast.Constant) and isinstance(e.value, str))
        or re.fullmatch(TERRAFORM_VERBS, e.value)
        or e.value.startswith("-")
        for e in node.elts[1:]
    )


def _docstrings(tree: ast.AST) -> set[int]:
    return {
        id(body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and (body := node.body)
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
    }


def _terraform_spawns(path: Path) -> list[str]:
    """Anything in a module that can name a terraform command, however it is built.

    Structural, not a list of call shapes: a command list anywhere (assigned
    to a variable first included), a string carrying a command (a shell line,
    an absolute binary path), and an f-string that starts with the binary.
    Docstrings are prose and are skipped.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    skip = _docstrings(tree)
    hits = []
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        if (
            _is_command_list(node)
            or (isinstance(node, ast.Constant) and isinstance(node.value, str) and COMMAND_IN_TEXT.search(node.value))
            or (
                isinstance(node, ast.JoinedStr)
                and node.values
                and isinstance(node.values[0], ast.Constant)
                and re.match(r"\s*(\S*/)?terraform\s", str(node.values[0].value))
            )
        ):
            hits.append(f"{path.relative_to(REPO) if path.is_relative_to(REPO) else path}:{node.lineno}")
    return hits


def test_no_toolkit_module_spawns_terraform_but_the_runner() -> None:
    offenders = [
        hit for path in sorted((REPO / "toolkit").rglob("*.py")) if path != RUNNER for hit in _terraform_spawns(path)
    ]
    assert not offenders, "go through toolkit.features.terraform_runner:\n" + "\n".join(offenders)


@pytest.mark.parametrize(
    "source",
    [
        'subprocess.run(["terraform", "plan"])',
        'cmd = ["terraform", verb]\nsubprocess.run(cmd)',
        'subprocess.run(f"terraform {verb} -auto-approve", shell=True)',
        "subprocess.run(\"bash -c 'terraform apply'\", shell=True)",
        'subprocess.run(["/usr/local/bin/terraform", "destroy"])',
        'os.execvp("terraform", ("terraform", "-chdir=x", "apply"))',
    ],
)
def test_the_scan_sees_every_way_to_build_the_command(tmp_path: Path, source: str) -> None:
    """The shapes a call-argument match alone missed (review of #2236)."""
    module = tmp_path / "probe.py"
    module.write_text(source + "\n", encoding="utf-8")
    assert _terraform_spawns(module), source


@pytest.mark.parametrize(
    "source",
    ['services = ("terraform",)', 'names = ["terraform", "traefik"]', 'def f():\n    """Run terraform plan."""\n'],
)
def test_the_scan_leaves_names_and_prose_alone(tmp_path: Path, source: str) -> None:
    module = tmp_path / "probe.py"
    module.write_text(source + "\n", encoding="utf-8")
    assert not _terraform_spawns(module), source


# Everything else that can run a command: CI, scripts, Ansible, compose files.
OTHER_CALLERS = (".github", "scripts", "infra/ansible", "infra/stacks", "edge")

# `fmt` is the one verb allowed there: it rewrites or checks .tf text and reads no
# secret, no state and no plan, so a CI formatting gate (TF-016, #2228) may call
# it directly. Everything else, `validate` included (it needs `init`), goes
# through the runner.
OUTSIDE_VERBS = TERRAFORM_VERBS.replace("|fmt", "")
COMMAND_OUTSIDE = re.compile(rf"(^|[\s'\"/;&|(`]){{1}}terraform\s+(-chdir=\S+\s+)?{OUTSIDE_VERBS}\b")


SCANNED_SUFFIXES = {".yml", ".yaml", ".sh", ".j2", ".py", ".mk", ""}


def _text_spawns(path: Path) -> list[str]:
    """Lines that run terraform in a workflow, script or playbook. Comments are prose."""
    return [
        f"{n}: {line.strip()}"
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1)
        if not line.lstrip().startswith("#") and COMMAND_OUTSIDE.search(line)
    ]


def test_nothing_outside_the_toolkit_runs_terraform() -> None:
    offenders = [
        f"{path.relative_to(REPO)}:{hit}"
        for top in OTHER_CALLERS
        for path in sorted((REPO / top).rglob("*"))
        if path.is_file() and path.suffix in SCANNED_SUFFIXES
        for hit in _text_spawns(path)
    ]
    assert not offenders, "go through `make tf-<root>-<action>`:\n" + "\n".join(offenders)


def test_the_text_scan_sees_a_workflow_step_and_skips_a_comment(tmp_path: Path) -> None:
    workflow = tmp_path / "plan.yml"
    workflow.write_text(
        "# terraform plan is run by the runner\n"
        "      - run: cd infra/terraform/dns && terraform apply -auto-approve\n"
        "      - run: /usr/bin/terraform -chdir=x plan\n"
        "      - run: terraform fmt -check -recursive infra/terraform\n",
        encoding="utf-8",
    )
    assert [hit.split(":")[0] for hit in _text_spawns(workflow)] == ["2", "3"]


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
    "tf-compute-plan": "compute plan",
    "tf-compute-apply": "compute apply",
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
