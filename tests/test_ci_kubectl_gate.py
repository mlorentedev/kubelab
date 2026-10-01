"""In CI, a render test that skips for want of kubectl fails instead (#2003).

The required Tests job runs 18 render tests that skip without kubectl. A skip is
CANNOT CHECK, and in the required job CANNOT CHECK under a green check is the
vacuous-green shape lesson-416 names. CI therefore installs a pinned kubectl, and
`tests/conftest.py` turns any skip that names kubectl into a failure there. These
tests pin both halves: the hook, by running a throwaway test file in a child
pytest, and the pin, against the k3s version the cluster runs.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

PROBE = """
import pytest

def test_render():
    pytest.skip("kubectl not on PATH: cannot render the overlay (a skip is CANNOT CHECK, not OK)")

def test_unrelated():
    pytest.skip("SOPS key not available")

@pytest.mark.xfail(reason="kubectl quirk, known")
def test_expected_failure():
    raise AssertionError
"""


def _child_pytest(tmp_path: Path, *, ci: bool) -> subprocess.CompletedProcess:
    """Run PROBE under this repository's conftest, with or without CI set."""
    env = {k: v for k, v in os.environ.items() if k != "CI"}
    if ci:
        env["CI"] = "true"
    target = REPO_ROOT / "tests" / f"test_zz_kubectl_gate_probe_{tmp_path.name}.py"
    target.write_text(textwrap.dedent(PROBE))
    try:
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider", "--no-cov", str(target)],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        target.unlink()


def test_a_kubectl_skip_fails_in_ci(tmp_path: Path) -> None:
    result = _child_pytest(tmp_path, ci=True)
    assert result.returncode == 1, result.stdout
    assert "1 failed, 1 skipped, 1 xfailed" in result.stdout, result.stdout
    assert "the render went unchecked" in result.stdout


def test_a_kubectl_skip_stays_a_skip_outside_ci(tmp_path: Path) -> None:
    result = _child_pytest(tmp_path, ci=False)
    assert result.returncode == 0, result.stdout
    assert "2 skipped, 1 xfailed" in result.stdout, result.stdout


def _workflow_env() -> dict[str, str]:
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text())
    return workflow["jobs"]["tests"]["env"]


def test_ci_pins_kubectl_to_the_cluster_version() -> None:
    """The kubectl that renders in CI is the one the cluster runs, and kustomize comes with it.

    `kubectl kustomize` embeds its own kustomize, so a different kubectl renders
    with a different kustomize. Bumping `k3s.version` fails this test until the
    workflow's version and checksum are bumped with it.
    """
    common = yaml.safe_load((REPO_ROOT / "infra" / "config" / "values" / "common.yaml").read_text())
    cluster = common["k3s"]["version"].split("+", 1)[0]
    env = _workflow_env()
    assert env["KUBECTL_VERSION"] == cluster, (
        f"ci.yml installs kubectl {env['KUBECTL_VERSION']} but k3s.version is {cluster}: "
        f"bump KUBECTL_VERSION and KUBECTL_SHA256 (from dl.k8s.io/release/{cluster}/bin/linux/amd64/kubectl.sha256)"
    )
    assert len(env["KUBECTL_SHA256"]) == 64


@pytest.mark.parametrize("step", ["Install kubectl", "kubectl is present"])
def test_the_tests_job_installs_and_requires_kubectl_before_make_test(step: str) -> None:
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text())
    names = [s.get("name") for s in workflow["jobs"]["tests"]["steps"]]
    assert step in names, names
    assert names.index(step) < names.index("Tests"), names
