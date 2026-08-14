"""Infrastructure: quota-watcher emits the numbers OBS-010's alert rules read.

OBS-010. #918 asked for an early signal on namespace quota utilization, so
growth is visible before admission starts rejecting workloads (IDP-031/#811).
Grafana has no metrics datasource in this repo (ADR-028 is Loki-only) and
standing up Prometheus/kube-state-metrics for one alerting ticket is out of
scope — so a CronJob reads the live ResourceQuota via the in-cluster API and
logs structured JSON that the existing Vector -> Loki pipeline already ships
everywhere else.

These tests cover the emitter half only. The alert rules themselves are
covered by `TestQuotaUtilizationRules` in `test_grafana_alerting.py`, reusing
its `grafana_api` fixture — provisioning-API tests belong together.
"""

from __future__ import annotations

import json
import os
import subprocess
import time

import pytest

pytestmark = pytest.mark.infra

_KUBECONFIG_PATTERN = "~/.kube/kubelab-{env}-config"

#: The Role must grant exactly this — get on resourcequotas, one named
#: object. Anything broader is the over-scope this test exists to catch.
EXPECTED_RULE = {
    "apiGroups": [""],
    "resources": ["resourcequotas"],
    "resourceNames": ["kubelab-quota"],
    "verbs": ["get"],
}

#: Both dimensions the emitter must report on every run.
EXPECTED_DIMENSIONS = {"requests.memory", "limits.memory"}

#: quota-watcher's own declared footprint (quota-watcher.yaml `resources:`), on
#: each dimension. The job this test triggers to exercise the emitter is
#: itself Running and self-counted while the emitter queries the quota — this
#: is the exact, known bound on how much that self-reference can move `used`.
_SELF_FOOTPRINT_MI = {"requests.memory": 32, "limits.memory": 64}

#: How many quota-watcher pods can plausibly be Running at once. Normally 1 (this
#: test's own triggered job), but `concurrencyPolicy: Forbid` on the CronJob only
#: governs jobs the CronJob *controller* schedules — a `kubectl create job
#: --from=cronjob/...` job, like this test's own, is NOT one of those, so it can
#: genuinely overlap with a naturally scheduled tick. Measured 2026-08-14: a bare
#: 1x tolerance flaked for exactly this reason (used_mi exceeded the bound by
#: precisely one more footprint's worth), retried clean seconds later. 2x covers
#: the realistic case; a third concurrent run is not worth chasing.
_MAX_CONCURRENT_RUNS = 2


def _kubeconfig(env: str) -> str:
    return os.path.expanduser(_KUBECONFIG_PATTERN.format(env=env))


def _kubectl(args: str, env: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    """Run kubectl via a fixed argument list — no shell, so `env` cannot execute."""
    return subprocess.run(
        ["kubectl", "--kubeconfig", _kubeconfig(env), *args.split()],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


@pytest.fixture(scope="module")
def require_kubeconfig(env: str) -> None:
    kubeconfig = _kubeconfig(env)
    if not os.path.exists(kubeconfig):
        pytest.skip(f"Kubeconfig not found: {kubeconfig}")
    result = _kubectl("cluster-info", env, timeout=10)
    if result.returncode != 0:
        pytest.skip(f"K3s cluster unreachable: {result.stderr.strip()}")


class TestQuotaWatcherRBAC:
    """The emitter's own ServiceAccount/Role/RoleBinding must exist and stay minimal."""

    def test_serviceaccount_exists(self, require_vpn: None, require_kubeconfig: None, env: str) -> None:
        result = _kubectl("get serviceaccount quota-watcher -n kubelab -o name", env)
        assert result.returncode == 0, (
            f"No ServiceAccount 'quota-watcher' in kubelab ({env}): {result.stderr}"
        )

    def test_role_is_scoped_to_exactly_one_grant(self, require_vpn: None, require_kubeconfig: None, env: str) -> None:
        """A wider grant here is a real privilege-escalation risk, not a style nit."""
        result = _kubectl("get role quota-watcher -n kubelab -o json", env)
        assert result.returncode == 0, f"No Role 'quota-watcher' in kubelab ({env}): {result.stderr}"

        rules = json.loads(result.stdout).get("rules", [])
        assert rules == [EXPECTED_RULE], (
            f"Role 'quota-watcher' in {env} grants {rules!r}, expected exactly "
            f"[{EXPECTED_RULE!r}]. This Role must never be broadened past "
            f"'get' on the single named 'kubelab-quota' object."
        )

    def test_rolebinding_targets_the_serviceaccount(self, require_vpn: None, require_kubeconfig: None, env: str) -> None:
        result = _kubectl("get rolebinding quota-watcher -n kubelab -o json", env)
        assert result.returncode == 0, (
            f"No RoleBinding 'quota-watcher' in kubelab ({env}): {result.stderr}"
        )

        binding = json.loads(result.stdout)
        subjects = binding.get("subjects", [])
        assert any(
            s.get("kind") == "ServiceAccount" and s.get("name") == "quota-watcher" for s in subjects
        ), f"RoleBinding 'quota-watcher' in {env} does not bind the quota-watcher ServiceAccount: {subjects}"
        assert binding.get("roleRef", {}).get("name") == "quota-watcher", (
            f"RoleBinding 'quota-watcher' in {env} references the wrong Role: {binding.get('roleRef')}"
        )


class TestQuotaWatcherEmitter:
    """The CronJob exists and, once run, emits correct structured log lines."""

    def test_cronjob_scheduled_every_five_minutes(self, require_vpn: None, require_kubeconfig: None, env: str) -> None:
        result = _kubectl("get cronjob quota-watcher -n kubelab -o json", env)
        assert result.returncode == 0, f"No CronJob 'quota-watcher' in kubelab ({env}): {result.stderr}"

        spec = json.loads(result.stdout).get("spec", {})
        assert spec.get("schedule") == "*/5 * * * *", (
            f"CronJob 'quota-watcher' in {env} has schedule {spec.get('schedule')!r}, "
            f"expected '*/5 * * * *' — must match the Grafana rules' evaluation interval "
            f"(quota-rules.yaml) or the for: window's two-consecutive-sample assumption breaks."
        )

    def test_run_emits_correct_utilization_per_dimension(self, require_vpn: None, require_kubeconfig: None, env: str) -> None:
        """Trigger one run on demand and check its output against the live ResourceQuota directly.

        Comparing against `kubectl get resourcequota` rather than re-deriving the
        expected percentage is deliberate — a test that re-implements the emitter's
        own math would pass even if both got the unit conversion wrong the same way.
        """
        quota_result = _kubectl("get resourcequota kubelab-quota -n kubelab -o json", env)
        assert quota_result.returncode == 0, f"No ResourceQuota 'kubelab-quota' in {env}: {quota_result.stderr}"
        quota = json.loads(quota_result.stdout)
        hard = quota.get("status", {}).get("hard", {})
        used = quota.get("status", {}).get("used", {})
        assert EXPECTED_DIMENSIONS <= hard.keys(), (
            f"ResourceQuota in {env} does not constrain both expected dimensions: {hard}"
        )

        job_name = f"quota-watcher-test-{int(time.time())}"
        create = _kubectl(
            f"create job {job_name} -n kubelab --from=cronjob/quota-watcher", env
        )
        assert create.returncode == 0, f"Could not trigger quota-watcher in {env}: {create.stderr}"

        try:
            wait = _kubectl(
                f"wait --for=condition=complete job/{job_name} -n kubelab --timeout=60s", env, timeout=70
            )
            assert wait.returncode == 0, f"quota-watcher job did not complete in {env}: {wait.stderr}"

            logs = _kubectl(f"logs job/{job_name} -n kubelab", env)
            assert logs.returncode == 0, f"Could not read quota-watcher logs in {env}: {logs.stderr}"

            lines = [json.loads(line) for line in logs.stdout.strip().splitlines() if line.strip()]
            seen_dimensions = {line.get("dimension") for line in lines}
            assert seen_dimensions == EXPECTED_DIMENSIONS, (
                f"quota-watcher in {env} emitted dimensions {seen_dimensions}, "
                f"expected exactly {EXPECTED_DIMENSIONS}. Lines: {lines}"
            )

            by_dimension = {line["dimension"]: line for line in lines}
            for dim in EXPECTED_DIMENSIONS:
                line = by_dimension[dim]
                assert line["hard_mi"] == _to_mi(hard[dim]), (
                    f"quota-watcher reported hard_mi={line['hard_mi']} for {dim} in {env}, "
                    f"expected {_to_mi(hard[dim])} (from the live ResourceQuota's {hard[dim]!r})."
                )
                # `used` is a moving target, and this test itself moves it: the
                # triggered job's own pod (32Mi request / 64Mi limit, see
                # quota-watcher.yaml) is Running and self-counted at the moment
                # the emitter queries the quota, but the "before" snapshot above
                # was taken before that pod existed. So the emitted value must be
                # AT LEAST the pre-job snapshot, bounded above by known,
                # explained confounds — not an arbitrary tolerance. See
                # _MAX_CONCURRENT_RUNS for why the bound is 2x this job's own
                # footprint, not 1x: measured 2026-08-14, a 1x bound flaked when
                # a naturally scheduled tick overlapped this test's own job.
                max_extra_mi = _SELF_FOOTPRINT_MI[dim] * _MAX_CONCURRENT_RUNS
                expected = _to_mi(used[dim])
                assert expected <= line["used_mi"] <= expected + max_extra_mi, (
                    f"quota-watcher reported used_mi={line['used_mi']} for {dim} in {env}, "
                    f"expected it within [{expected}, {expected + max_extra_mi}] "
                    f"(live ResourceQuota's {used[dim]!r} plus up to "
                    f"{_MAX_CONCURRENT_RUNS} concurrent quota-watcher runs' "
                    f"{_SELF_FOOTPRINT_MI[dim]}Mi footprint each on that dimension)."
                )
        finally:
            _kubectl(f"delete job {job_name} -n kubelab --ignore-not-found", env)


def _to_mi(quantity: str) -> int:
    """Mirror of the emitter's own unit conversion, for independent comparison.

    Deliberately reimplemented rather than imported: the emitter is a shell
    script baked into a manifest, not importable Python, and re-deriving the
    same logic here (from the Kubernetes quantity format, not from reading
    quota-watcher.yaml) is what makes this an independent check rather than a
    tautology.
    """
    if quantity.endswith("Gi"):
        return int(quantity[:-2]) * 1024
    if quantity.endswith("Mi"):
        return int(quantity[:-2])
    if quantity.endswith("Ki"):
        return int(quantity[:-2]) // 1024
    return int(quantity) // 1048576
