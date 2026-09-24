"""#1804: a Secret `apply-secrets` changed is followed by a restart of whatever reads it.

Measured 2026-09-24: `apply-secrets ENV=staging` added `manu` to `authelia-users`,
the file in the pod held `manu` a moment later, and Authelia kept answering
`user not found` for three minutes, until a manual restart. Its users-file watch
filters on the file name, and a Secret volume update never touches that name.
Env-var consumers have the same property by construction.

Consumers are derived from pod templates, so these tests feed real-shaped
workload JSON rather than a list of names.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from toolkit.features import k8s_secrets
from toolkit.features.k8s_secrets import SecretMapping, _apply_single_secret
from toolkit.features.secret_consumers import consumers, restart_consumers, secret_refs


def _workload(kind: str, name: str, pod_spec: dict) -> dict:
    return {"kind": kind, "metadata": {"name": name}, "spec": {"template": {"spec": pod_spec}}}


AUTHELIA = _workload(
    "Deployment",
    "authelia",
    {
        "containers": [{"name": "authelia"}],
        "volumes": [{"name": "users", "secret": {"secretName": "authelia-users"}}],
    },
)
GRAFANA = _workload(
    "Deployment",
    "grafana",
    {"containers": [{"name": "grafana", "env": [{"name": "U", "valueFrom": {"secretKeyRef": {"name": "grafana-admin"}}}]}]},
)
N8N = _workload("StatefulSet", "n8n", {"containers": [{"name": "n8n", "envFrom": [{"secretRef": {"name": "n8n-secrets"}}]}]})
MIGRATOR = _workload(
    "Deployment",
    "api",
    {
        "initContainers": [{"name": "migrate", "envFrom": [{"secretRef": {"name": "api-secrets"}}]}],
        "containers": [{"name": "api"}],
        "volumes": [{"name": "p", "projected": {"sources": [{"secret": {"name": "api-tls"}}, {"configMap": {"name": "x"}}]}}],
    },
)


class TestConsumersAreDerived:
    def test_every_way_a_pod_reads_a_secret_counts(self) -> None:
        assert secret_refs(AUTHELIA["spec"]["template"]["spec"]) == {"authelia-users"}
        assert secret_refs(GRAFANA["spec"]["template"]["spec"]) == {"grafana-admin"}
        assert secret_refs(N8N["spec"]["template"]["spec"]) == {"n8n-secrets"}
        assert secret_refs(MIGRATOR["spec"]["template"]["spec"]) == {"api-secrets", "api-tls"}

    def test_only_the_readers_of_a_changed_secret_are_selected(self) -> None:
        workloads = [AUTHELIA, GRAFANA, N8N, MIGRATOR]
        assert consumers(workloads, {"authelia-users"}) == ["deployment/authelia"]
        assert consumers(workloads, {"n8n-secrets", "api-tls"}) == ["deployment/api", "statefulset/n8n"]
        assert consumers(workloads, {"nothing-reads-this"}) == []


class FakeKubectl:
    """Answers `get` with the workloads above and records every other call."""

    def __init__(self, workloads: list[dict], fail: str = "") -> None:
        self.workloads, self.fail, self.calls = workloads, fail, []

    def __call__(self, argv, **_kwargs):
        verb = argv[argv.index("-n") + 2]
        self.calls.append(argv[argv.index("-n") + 2 :])
        if verb == "get":
            return SimpleNamespace(returncode=0, stdout=json.dumps({"items": self.workloads}), stderr="")
        if self.fail and self.fail in argv:
            return SimpleNamespace(returncode=1, stdout="", stderr=f"{self.fail} failed")
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def _kubectl(namespace: str) -> list[str]:
    return ["kubectl", "-n", namespace]


class TestRestartConsumers:
    def test_a_changed_secret_restarts_its_reader_and_waits_for_it(self) -> None:
        run = FakeKubectl([AUTHELIA, GRAFANA])
        assert restart_consumers({("kubelab", "authelia-users")}, _kubectl, run=run) is True
        assert ["rollout", "restart", "deployment/authelia"] in run.calls
        assert any(c[:3] == ["rollout", "status", "deployment/authelia"] for c in run.calls)
        assert not any("deployment/grafana" in c for c in run.calls), "a workload that does not read it was restarted"

    @pytest.mark.parametrize("step", ["restart", "status"])
    def test_a_failed_restart_is_a_failed_apply(self, step: str) -> None:
        """Applied but not in use is the defect; it must not report success."""
        run = FakeKubectl([AUTHELIA], fail=step)
        assert restart_consumers({("kubelab", "authelia-users")}, _kubectl, run=run) is False

    def test_a_secret_nobody_reads_restarts_nothing(self) -> None:
        run = FakeKubectl([GRAFANA])
        assert restart_consumers({("kubelab", "authelia-users")}, _kubectl, run=run) is True
        assert [c for c in run.calls if c[0] != "get"] == []


class TestOnlyAChangedSecretCounts:
    @pytest.mark.parametrize(
        ("stdout", "counted"),
        [
            ("secret/authelia-users configured", True),
            ("secret/authelia-users created", True),
            ("secret/authelia-users unchanged", False),
        ],
    )
    def test_kubectl_verdict_decides(self, mocker, stdout: str, counted: bool) -> None:
        """`unchanged` must not count, or every re-run would bounce every service."""
        run = mocker.patch("toolkit.features.k8s_secrets.subprocess.run")
        run.return_value = mocker.Mock(stdout=stdout, returncode=0)
        changed: set[tuple[str, str]] = set()

        ok = _apply_single_secret(
            SecretMapping(name="authelia-users", keys={}),
            {},
            {"users_database.yml": "users: {}"},
            dry_run=False,
            env="staging",
            changed=changed,
        )

        assert ok is True
        assert (("kubelab", "authelia-users") in changed) is counted


def test_apply_secrets_restarts_the_consumers_of_what_it_changed(monkeypatch) -> None:
    """The wiring: without step 5 the Secret changes and nothing re-reads it."""

    class CM:
        def get_env_vars(self):
            return {"X": "1"}

        def get_merged_config(self):
            return {"apps": {"auth": {"identities": {"superadmin": "manu"}}, "services": {"security": {"authelia": {}}}}}

    monkeypatch.setattr(k8s_secrets, "ConfigurationManager", lambda *a, **k: CM())
    monkeypatch.setattr(
        k8s_secrets,
        "_build_dynamic_literals",
        lambda cm: {"grafana-admin": {"admin-user": "manu"}, "minio-secrets": {"MINIO_ROOT_USER": "manu"}},
    )
    monkeypatch.setattr(k8s_secrets, "SECRET_DEFINITIONS", [SecretMapping(name="authelia-users", keys={})])

    def apply(mapping, *a, changed=None, namespace="kubelab", **k):
        changed.add((namespace, mapping.name))
        return True

    monkeypatch.setattr(k8s_secrets, "_apply_single_secret", apply)
    restarted: list[set] = []
    monkeypatch.setattr(k8s_secrets, "restart_consumers", lambda changed, **k: restarted.append(set(changed)) or True)

    assert k8s_secrets.apply_secrets("staging", Path("/nonexistent")) is True
    assert restarted == [{("kubelab", "authelia-users")}]
