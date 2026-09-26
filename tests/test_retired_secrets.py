"""A Secret the toolkit stopped rendering is deleted, not left behind.

`apply-secrets` creates Secrets outside git, so Argo CD never tracks them and
never prunes them. Removing a `SecretMapping` therefore stops the Secret from
being updated, and leaves the last value it held in etcd for good: the shape
TOOL-025 records for Middlewares. OPS-023 hit it with `minio-secrets`, which
held the MinIO root password after MinIO was gone.

`RETIRED_SECRETS` is the declaration of what used to exist. Every apply
deletes those names with `--ignore-not-found`, so it is idempotent and needs no
one to remember a one-off command per environment.
"""

from __future__ import annotations

import subprocess

import pytest

from toolkit.features import k8s_secrets


class _Recorder:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.fail = fail

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if self.fail:
            raise subprocess.CalledProcessError(1, argv, stderr="forbidden")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


@pytest.fixture(autouse=True)
def _kubeconfig(monkeypatch):
    monkeypatch.setattr(k8s_secrets, "_get_kubeconfig", lambda env: f"/kube/{env}")


def test_minio_secrets_is_declared_retired() -> None:
    assert ("kubelab", "minio-secrets") in k8s_secrets.RETIRED_SECRETS


def test_a_retired_secret_is_never_also_rendered() -> None:
    rendered = {(m.namespace, m.name) for m in k8s_secrets.SECRET_DEFINITIONS}
    both = rendered & set(k8s_secrets.RETIRED_SECRETS)
    assert not both, f"{both} would be applied and deleted in the same run"


def test_each_retired_secret_is_deleted_idempotently() -> None:
    run = _Recorder()
    assert k8s_secrets.delete_retired_secrets("staging", dry_run=False, run=run) is True
    assert len(run.calls) == len(k8s_secrets.RETIRED_SECRETS)
    for (namespace, name), argv in zip(k8s_secrets.RETIRED_SECRETS, run.calls, strict=True):
        assert argv[:5] == ["kubectl", "--kubeconfig", "/kube/staging", "-n", namespace]
        assert argv[5:] == ["delete", "secret", name, "--ignore-not-found"]


def test_dry_run_deletes_nothing() -> None:
    run = _Recorder()
    assert k8s_secrets.delete_retired_secrets("prod", dry_run=True, run=run) is True
    assert all("delete" not in argv for argv in run.calls)


def test_a_failed_delete_fails_the_apply() -> None:
    # A delete that did not happen must not read as a clean apply: the value
    # it was meant to remove is still in the cluster.
    assert k8s_secrets.delete_retired_secrets("prod", dry_run=False, run=_Recorder(fail=True)) is False


def test_a_missing_kubectl_fails_the_apply_instead_of_crashing() -> None:
    def no_kubectl(argv, **kwargs):
        raise FileNotFoundError("kubectl")

    assert k8s_secrets.delete_retired_secrets("prod", dry_run=False, run=no_kubectl) is False
