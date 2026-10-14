"""#2273 (TOOL-114): a failed generator fails the command that ran it.

Every generator returns `{"success": bool, ...}`. `config generate` counted a
service as generated with `if result:`, and a dict is truthy whatever `success`
holds, so a failed generator logged an error and the command still printed
"All configurations generated successfully" and exited 0. CI's Config Drift Gate
relied on that: it ran every generator without SOPS, and Authelia and Traefik
failed there on every run, unseen. The gate now runs only the generators whose
output it diffs.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from toolkit.cli import config as config_cli

REPO = Path(__file__).resolve().parents[1]


class _Generator:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result

    def generate(self, _env: str) -> dict[str, object]:
        return self.result


@pytest.mark.parametrize(("success", "exit_code"), [(False, 1), (True, 0)])
def test_the_exit_code_follows_the_generators_success_field(
    monkeypatch: pytest.MonkeyPatch, success: bool, exit_code: int
) -> None:
    result = {"success": success, "error": "planted failure"}
    monkeypatch.setattr(config_cli, "K8sGenerator", lambda: _Generator(result))
    run = CliRunner().invoke(config_cli.app, ["generate", "--env", "staging", "--service", "k8s", "--force"])
    assert run.exit_code == exit_code, run.output


def _discarded_generate_calls(path: Path) -> list[int]:
    """Lines where a generator's `.generate(...)` result is thrown away."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "generate"
    ]


def test_no_caller_discards_a_generators_result() -> None:
    """The defect class: the outcome is in the return value, so ignoring it hides a failure."""
    offenders = [
        f"{path.relative_to(REPO)}:{line}"
        for path in sorted((REPO / "toolkit").rglob("*.py"))
        for line in _discarded_generate_calls(path)
    ]
    assert not offenders, f"generator results discarded at: {offenders}"


def _drift(toolkit: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", "--no-print-directory", "config-check-drift", "ENV=staging", f"TOOLKIT={toolkit}"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )


def _skip_if_refused(run: subprocess.CompletedProcess[str]) -> None:
    if "Refusing to run" in run.stdout:
        pytest.skip("uncommitted changes under the generated overlays; the gate refuses before generating")


@pytest.mark.parametrize(("toolkit", "exit_code", "says"), [("false", 2, "A generator failed"), ("true", 0, "No drift")])
def test_the_drift_gate_fails_on_a_failed_generator(toolkit: str, exit_code: int, says: str) -> None:
    run = _drift(toolkit)
    _skip_if_refused(run)
    assert says in run.stdout, run.stdout + run.stderr
    # make reports a failed recipe as 2, a passing one as 0.
    assert run.returncode == exit_code, run.stdout + run.stderr


def test_a_failed_generator_still_has_its_output_reverted(tmp_path: Path) -> None:
    """A generator that writes, then fails, must not leave a tracked file dirty."""
    tracked = "infra/k8s/overlays/staging/generated/deployments.yaml"
    generator = tmp_path / "toolkit"
    generator.write_text(f"#!/bin/sh\necho '# partial write' >> {REPO / tracked}\nexit 1\n")
    generator.chmod(0o755)
    try:
        run = _drift(str(generator))
        _skip_if_refused(run)
        assert run.returncode == 2, run.stdout + run.stderr
        dirty = subprocess.run(["git", "diff", "--quiet", "--", tracked], cwd=REPO, check=False).returncode
        assert dirty == 0, f"{tracked} was left modified after a failed generator"
    finally:
        subprocess.run(["git", "checkout", "--", tracked], cwd=REPO, check=False)


def test_the_drift_gate_runs_only_the_generators_it_compares() -> None:
    run = subprocess.run(
        ["make", "-n", "--no-print-directory", "config-check-drift", "ENV=staging"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "for _svc in k8s ansible;" in run.stdout
    assert "config generate --env staging --force" not in run.stdout
