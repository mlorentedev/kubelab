"""`apply-secrets --dry-run` says what a real run would change, without values (#1810).

Before this, `--dry-run` returned before reaching the cluster: it listed every
Secret and its keys, but not which ones differ from what is live. A real run
applies every Secret of the env at once, so landing one value also landed
whatever another lane had put in SOPS and restarted that lane's consumers.

The preview asks the API server instead (`kubectl apply --dry-run=server`),
which answers `unchanged`/`configured`/`created` per Secret and never echoes a
value, then reports the retired Secrets still present and the workloads a real
run would restart.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from toolkit.features import k8s_secrets
from toolkit.features.k8s_secrets import SecretMapping, _apply_single_secret, delete_retired_secrets
from toolkit.features.secret_consumers import restart_consumers

MISSING_ANNOTATION = (
    "Warning: resource secrets/grafana-admin is missing the "
    "kubectl.kubernetes.io/last-applied-configuration annotation which is required by kubectl apply."
)


@pytest.fixture(autouse=True)
def _kubeconfig(monkeypatch):
    monkeypatch.setattr(k8s_secrets, "_get_kubeconfig", lambda env: f"/kube/{env}")


def _preview(mocker, stdout: str, stderr: str = "") -> tuple[set, object, object]:
    run = mocker.patch("toolkit.features.k8s_secrets.subprocess.run")
    run.return_value = mocker.Mock(stdout=stdout, stderr=stderr, returncode=0)
    log = mocker.patch.object(k8s_secrets, "logger")
    changed: set[tuple[str, str]] = set()
    ok = _apply_single_secret(
        SecretMapping(name="grafana-admin", keys={}),
        {},
        {"admin-user": "breakglass", "admin-password": "s3cr3t-value"},
        dry_run=True,
        env="prod",
        changed=changed,
    )
    assert ok is True
    return changed, run, log


class TestPerSecretVerdict:
    @pytest.mark.parametrize(
        ("stdout", "counted"),
        [
            ("secret/grafana-admin configured (server dry run)", True),
            ("secret/grafana-admin created (server dry run)", True),
            ("secret/grafana-admin unchanged (server dry run)", False),
        ],
    )
    def test_the_server_verdict_decides_what_would_change(self, mocker, stdout: str, counted: bool) -> None:
        changed, _, _ = _preview(mocker, stdout)
        assert (("kubelab", "grafana-admin") in changed) is counted

    def test_the_server_is_asked_and_the_values_go_on_stdin_only(self, mocker) -> None:
        _, run, log = _preview(mocker, "secret/grafana-admin unchanged (server dry run)")
        argv = run.call_args.args[0]
        assert argv[:5] == ["kubectl", "--kubeconfig", "/kube/prod", "-n", "kubelab"]
        assert argv[5:] == ["apply", "--dry-run=server", "-f", "-"]
        assert "s3cr3t-value" not in " ".join(argv)
        logged = " ".join(str(c) for c in log.mock_calls)
        assert "s3cr3t-value" not in logged
        assert "czNjcjN0LXZhbHVl" not in logged, "the base64 of a value is the value"

    def test_a_secret_kubectl_never_applied_is_flagged_as_ambiguous(self, mocker) -> None:
        """Without the annotation, `configured` does not mean the value changed."""
        changed, _, log = _preview(mocker, "secret/grafana-admin configured (server dry run)", MISSING_ANNOTATION)
        assert ("kubelab", "grafana-admin") in changed
        warned = " ".join(str(c.args) for c in log.warning.call_args_list)
        assert "grafana-admin" in warned and "last-applied-configuration" in warned

    def test_a_refused_preview_fails(self, mocker) -> None:
        import subprocess

        run = mocker.patch("toolkit.features.k8s_secrets.subprocess.run")
        run.side_effect = subprocess.CalledProcessError(1, "kubectl", stderr="forbidden")
        mocker.patch.object(k8s_secrets, "logger")
        ok = _apply_single_secret(SecretMapping(name="x", keys={}), {}, {"k": "v"}, dry_run=True, env="prod")
        assert ok is False


class _Get:
    def __init__(self, present: bool, returncode: int = 0) -> None:
        self.present, self.returncode = present, returncode
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        stdout = f"secret/{argv[-4]}" if self.present else ""
        return SimpleNamespace(returncode=self.returncode, stdout=stdout, stderr="boom" if self.returncode else "")


class TestRetiredSecretsPreview:
    @pytest.mark.parametrize("present", [True, False])
    def test_the_preview_reads_and_never_deletes(self, mocker, present: bool) -> None:
        log = mocker.patch.object(k8s_secrets, "logger")
        run = _Get(present)
        assert delete_retired_secrets("prod", dry_run=True, run=run) is True
        assert all("delete" not in argv for argv in run.calls)
        for (namespace, name), argv in zip(k8s_secrets.RETIRED_SECRETS, run.calls, strict=True):
            assert argv[5:] == ["get", "secret", name, "--ignore-not-found", "-o", "name"]
        said = " ".join(str(c) for c in log.mock_calls)
        assert ("would delete" in said) is present
        assert ("already absent" in said) is not present

    def test_a_preview_that_cannot_read_fails(self, mocker) -> None:
        mocker.patch.object(k8s_secrets, "logger")
        assert delete_retired_secrets("prod", dry_run=True, run=_Get(False, returncode=1)) is False


def _workload(kind: str, name: str, secret: str) -> dict:
    spec = {"containers": [{"name": name}], "volumes": [{"name": "s", "secret": {"secretName": secret}}]}
    return {"kind": kind, "metadata": {"name": name}, "spec": {"template": {"spec": spec}}}


class _Cluster:
    def __init__(self, by_namespace: dict[str, list[dict]]) -> None:
        self.by_namespace = by_namespace
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        namespace = argv[argv.index("-n") + 1]
        self.calls.append(argv[argv.index("-n") + 2 :])
        if argv[argv.index("-n") + 2] == "get":
            return SimpleNamespace(returncode=0, stdout=json.dumps({"items": self.by_namespace[namespace]}), stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def _kubectl(namespace: str) -> list[str]:
    return ["kubectl", "-n", namespace]


TRAEFIK = {"kube-system": [_workload("Deployment", "traefik", "crowdsec-bouncer-traefik")]}


class TestRestartPreview:
    def test_the_preview_names_the_targets_and_restarts_nothing(self, mocker) -> None:
        log = mocker.patch("toolkit.features.secret_consumers.logger")
        run = _Cluster({"kubelab": [_workload("Deployment", "grafana", "grafana-admin")]})
        assert restart_consumers({("kubelab", "grafana-admin")}, _kubectl, run=run, dry_run=True) is True
        assert [c for c in run.calls if c[0] != "get"] == []
        assert "deployment/grafana" in " ".join(str(c) for c in log.mock_calls)

    @pytest.mark.parametrize("dry_run", [True, False])
    def test_restarting_the_ingress_is_said_before_it_happens(self, mocker, dry_run: bool) -> None:
        """Traefik is the only ingress: its restart bounces every route (#1810 gap 2)."""
        log = mocker.patch("toolkit.features.secret_consumers.logger")
        order: list[str] = []
        log.warning.side_effect = lambda *a, **k: order.append("warning")
        run = _Cluster(TRAEFIK)

        def recording(argv, **kwargs):
            if "restart" in argv:
                order.append("restart")
            return run(argv, **kwargs)

        restart_consumers({("kube-system", "crowdsec-bouncer-traefik")}, _kubectl, run=recording, dry_run=dry_run)

        warned = " ".join(str(c.args) for c in log.warning.call_args_list)
        assert "kube-system/deployment/traefik" in warned
        assert order[0] == "warning"
        assert ("restart" in order) is not dry_run


def test_apply_secrets_dry_run_previews_the_restarts(monkeypatch) -> None:
    """The wiring: the preview must reach the restart step, in preview mode."""

    class CM:
        def get_env_vars(self):
            return {"X": "1"}

    monkeypatch.setattr(k8s_secrets, "ConfigurationManager", lambda *a, **k: CM())
    monkeypatch.setattr(k8s_secrets, "_build_dynamic_literals", lambda cm: {"grafana-admin": {"admin-user": "bg"}})
    monkeypatch.setattr(k8s_secrets, "SECRET_DEFINITIONS", [SecretMapping(name="grafana-admin", keys={})])

    def apply(mapping, *a, changed=None, namespace="kubelab", **k):
        changed.add((namespace, mapping.name))
        return True

    monkeypatch.setattr(k8s_secrets, "_apply_single_secret", apply)
    monkeypatch.setattr(k8s_secrets, "delete_retired_secrets", lambda env, dry_run: True)
    seen: list[dict] = []
    monkeypatch.setattr(k8s_secrets, "restart_consumers", lambda changed, **k: seen.append(k) or True)

    assert k8s_secrets.apply_secrets("prod", None, dry_run=True) is True
    assert len(seen) == 1 and seen[0]["dry_run"] is True
