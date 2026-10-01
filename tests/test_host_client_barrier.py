"""The default-deny that keeps unit tests off real clusters and hosts (#1886).

`denied` is a pure predicate over the argv a test is about to spawn, so it is
tested here with no subprocess at all. The hook in `conftest.py` that applies
it is tested by running a throwaway test file in a child pytest.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.host_clients import denied

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "args",
    [
        ["kubectl", "get", "pods"],
        ["kubectl", "delete", "secret", "retired-secret", "--ignore-not-found"],
        ["kubectl", "--kubeconfig", "/home/x/.kube/kubelab-staging-config", "apply", "-f", "-"],
        ["kubectl", "-n", "kubelab", "rollout", "restart", "deploy/authelia"],
        ["kubectl", "version"],
        ["/usr/local/bin/kubectl", "get", "ns"],
        ["kubectl.exe", "get", "ns"],
        ["helm", "upgrade", "--install", "argocd", "argo/argo-cd"],
        ["ssh", "deployer@vps", "true"],
        ["scp", "a", "host:b"],
        ["rsync", "-a", "a", "host:b"],
        ["ansible-playbook", "site.yml"],
        ["ansible", "all", "-m", "ping"],
        ["terraform", "apply"],
        ["tofu", "plan"],
        ["tailscale", "status"],
        ["restic", "-r", "s3:r2/x", "snapshots"],
        ["sudo", "-n", "kubectl", "get", "pods"],
        ["timeout", "10", "ssh", "host", "true"],
        ["env", "KUBECONFIG=/x", "kubectl", "get", "pods"],
        ["sudo", "-u", "deployer", "kubectl", "get", "pods"],
        ["timeout", "-s", "KILL", "5", "ssh", "host", "true"],
        ["sh", "-c", "kubectl get pods | head -1"],
        ["bash", "-ec", "kubectl delete secret x"],
        ["bash", "-lc", "ssh host true"],
        ["sh", "-e", "-c", "kubectl get pods"],
        ["bash", "-o", "pipefail", "-c", "kubectl get pods | wc -l"],
        "kubectl get pods",
        "set -e; ssh host true",
    ],
)
def test_a_cluster_or_host_client_is_denied(args) -> None:
    assert denied(args)


@pytest.mark.parametrize(
    "args",
    [
        ["kubectl", "kustomize", "infra/k8s/overlays/prod"],
        ["kubectl", "--kubeconfig", "/x", "kustomize", "infra/k8s/overlays/prod"],
        ["kubectl", "version", "--client", "-o", "yaml"],
        ["helm", "template", "argocd", "argo/argo-cd"],
        ["helm", "lint", "chart"],
        ["sh", "-c", "kubectl kustomize infra/k8s/overlays/staging"],
        ["bash", "-ec", "echo ok"],
        ["bash", "scripts/kubectl-free.sh"],
        ["git", "rev-parse", "HEAD"],
        ["sops", "-d", "secrets/staging.enc.yaml"],
        ["docker", "run", "--rm", "timberio/vector"],
        ["python3", "-c", "print(1)"],
        "echo kubectl-free",
    ],
)
def test_a_local_command_is_allowed(args) -> None:
    assert denied(args) is None


def test_a_shell_true_sequence_is_read_as_a_script() -> None:
    assert denied(["kubectl get pods"], shell=True) == "kubectl get"
    assert denied(["kubectl kustomize infra/k8s/overlays/prod"], shell=True) is None


def test_the_answer_names_the_client_and_its_subcommand() -> None:
    assert denied(["sudo", "kubectl", "-n", "kubelab", "delete", "secret", "x"]) == "kubectl delete"


def _child_pytest(tmp_path: Path, body: str) -> subprocess.CompletedProcess:
    """Run a throwaway test file under this repository's conftest, in a child pytest.

    The probes that opt in really do spawn their client, so the child's PATH
    starts with stubs: a probe must never reach the workstation's cluster.
    """
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for client in ("kubectl", "ssh"):
        (stubs / client).write_text("#!/bin/sh\nexit 0\n")
        (stubs / client).chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "KUBELAB_HOST_CLIENT_REPORT"}
    env["PATH"] = f"{stubs}{os.pathsep}{env.get('PATH', '')}"
    target = REPO_ROOT / "tests" / f"test_zz_barrier_probe_{tmp_path.name}.py"
    target.write_text(textwrap.dedent(body))
    try:
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-cov", str(target)],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        target.unlink()


PROBE = """
    import subprocess
    import pytest

    def _spawn():
        try:
            subprocess.run(["kubectl", "get", "pods"], capture_output=True)
        except OSError:
            pass  # what the toolkit's own wrappers do with a missing binary
"""


def test_a_unit_test_that_reaches_kubectl_fails_naming_the_command_and_the_opt_in(tmp_path) -> None:
    proc = _child_pytest(tmp_path, PROBE + "\n    def test_unmocked():\n        _spawn()\n")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "kubectl get" in proc.stdout
    assert "allow_host_clients" in proc.stdout


def test_a_refusal_the_code_under_test_swallows_still_fails_the_test(tmp_path) -> None:
    body = """
    import subprocess

    def test_swallowed():
        try:
            subprocess.run(["ssh", "host", "true"])
        except BaseException:
            pass
    """
    proc = _child_pytest(tmp_path, body)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "caught by the code under test" in proc.stdout


def test_a_module_scoped_fixture_is_held_to_the_same_rule(tmp_path) -> None:
    body = PROBE + textwrap.dedent(
        """
        @pytest.fixture(scope="module")
        def cluster():
            _spawn()

        def test_uses_it(cluster):
            pass
        """
    ).replace("\n", "\n    ")
    proc = _child_pytest(tmp_path, body)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "kubectl get" in proc.stdout


@pytest.mark.parametrize(
    "decoration",
    [
        '@pytest.mark.allow_host_clients(reason="talks to a throwaway cluster")',
        "@pytest.mark.integration",
    ],
)
def test_a_test_that_opts_in_may_spawn_a_client(tmp_path, decoration) -> None:
    proc = _child_pytest(tmp_path, PROBE + f"\n    {decoration}\n    def test_opted_in():\n        _spawn()\n")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_an_opt_in_without_a_reason_is_refused(tmp_path) -> None:
    body = PROBE + "\n    @pytest.mark.allow_host_clients\n    def test_t():\n        _spawn()\n"
    proc = _child_pytest(tmp_path, body)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "reason" in proc.stdout


@pytest.mark.parametrize(
    ("relative", "allowed"),
    [("e2e/test_x.py", True), ("infra/test_x.py", True), ("test_x.py", False), ("unit/e2e_like.py", False)],
)
def test_the_e2e_and_infra_suites_are_exempt_by_directory(relative, allowed) -> None:
    from types import SimpleNamespace

    from tests.conftest import _TESTS_DIR, _host_clients_allowed

    item = SimpleNamespace(path=_TESTS_DIR / relative, get_closest_marker=lambda name: None)
    assert _host_clients_allowed(item) is allowed


def test_a_nested_in_process_run_leaves_the_outer_test_guarded() -> None:
    from tests import conftest

    before = conftest._current_item
    outer, inner = object(), object()
    outer_run = conftest.pytest_runtest_protocol(outer)
    next(outer_run)
    inner_run = conftest.pytest_runtest_protocol(inner)
    next(inner_run)
    inner_run.close()
    assert conftest._current_item is outer
    outer_run.close()
    assert conftest._current_item is before
