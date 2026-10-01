"""The required Tests job runs every sync target's drift check (#1990).

`make validate-sync` (`toolkit sync all --check`) ran in CI only in the Windows
job of the Config Drift Gate, which is not required. On 2026-10-01 two merges
changed `common.yaml` without regenerating `infra/config/platform.json`, every
required check stayed green, and the stale file sat on master until a later PR
noticed the red Windows job. `sync all` enumerates its targets itself, so running
it in a required job covers a target added tomorrow without editing this file,
with one exception: a target that needs SOPS skips itself in CI, where there is
no key. Each such target is declared below with the SOPS-free test that covers it
in the same job, and a new one fails here until it has one.
"""

from __future__ import annotations

import ast
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
CI = REPO / ".github/workflows/ci.yml"
SYNC = REPO / "toolkit/cli/sync.py"

# Targets `sync all --check` skips without SOPS, each with the test that checks
# its committed output without SOPS. `test_oidc_clients.py` compares every field
# of the generated `oidc-clients.yml` except `client_secret`.
SKIPPED_WITHOUT_SOPS = {"oidc": "tests/test_oidc_clients.py"}


def _steps(job: str) -> list[dict]:
    return yaml.safe_load(CI.read_text())["jobs"][job]["steps"]


def test_the_required_tests_job_runs_validate_sync() -> None:
    runs = [str(step.get("run", "")) for step in _steps("tests")]
    assert any("make validate-sync" in run for run in runs), "the Tests job must run `make validate-sync`"


def test_the_local_definition_of_done_still_names_it() -> None:
    """CI mirrors `make check`; if the local gate drops validate-sync, revisit this one."""
    check = next(line for line in (REPO / "Makefile").read_text().splitlines() if line.startswith("check:"))
    assert "validate-sync" in check, check


def _sops_gated_labels() -> list[str]:
    """Each `failures.append(<label>)` inside an `if not _sops_available()` branch's else, in `sync_all`."""
    tree = ast.parse(SYNC.read_text())
    [sync_all] = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "sync_all"]
    labels: list[str] = []
    for node in ast.walk(sync_all):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        gated = (
            isinstance(test, ast.UnaryOp)
            and isinstance(test.operand, ast.Call)
            and getattr(test.operand.func, "id", "") == "_sops_available"
        )
        if not gated:
            continue
        for inner in ast.walk(ast.Module(body=node.orelse, type_ignores=[])):
            if isinstance(inner, ast.Call) and getattr(inner.func, "attr", "") == "append":
                labels += [a.value for a in inner.args if isinstance(a, ast.Constant)]
    return labels


def test_every_target_ci_skips_has_a_sops_free_test() -> None:
    labels = _sops_gated_labels()
    assert labels, "found no SOPS-gated target in sync_all; the matcher is broken"
    undeclared = sorted(set(labels) - set(SKIPPED_WITHOUT_SOPS))
    assert not undeclared, (
        f"{undeclared} skip in CI without SOPS; add a SOPS-free test of their output and declare it here"
    )
    for label, test in SKIPPED_WITHOUT_SOPS.items():
        assert (REPO / test).is_file(), f"{label}'s SOPS-free test {test} does not exist"
