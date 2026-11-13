"""The delivery watcher's pod shape, as each overlay renders it (GITOPS-003 AC2).

`test_delivery_watcher.py` drives `watch.py` through its environment, so it
cannot see the CronJob that sets that environment. A lost prod patch would leave
prod's watcher reading staging's status: `healthy: 1` while prod sits on an older
revision, and the rule that exists to page on exactly that stays quiet.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
RULES = REPO / "infra/k8s/base/services/grafana-alerting/delivery-rules.yaml"
NAME = "delivery-watcher"
ENVIRONMENTS = ("staging", "prod")


def _kustomize(env: str) -> list[dict]:
    """Render an overlay, or skip loudly: a skip means CANNOT CHECK, never a pass."""
    if shutil.which("kubectl") is None:
        pytest.skip("CANNOT CHECK: kubectl is not installed, so the watcher render is unverified.")
    result = subprocess.run(
        ["kubectl", "kustomize", str(REPO / "infra/k8s/overlays" / env)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(f"kubectl kustomize overlays/{env} failed:\n{result.stderr}")
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


@pytest.fixture(params=ENVIRONMENTS, scope="module")
def rendered(request) -> tuple[str, dict]:
    docs = _kustomize(request.param)
    cronjob = next(d for d in docs if d["kind"] == "CronJob" and d["metadata"]["name"] == NAME)
    return request.param, cronjob


def _env(cronjob: dict) -> dict[str, str]:
    (container,) = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"]
    return {e["name"]: e.get("value") for e in container["env"]}


def test_each_environment_reads_its_own_argo_status(rendered) -> None:
    env, cronjob = rendered
    assert _env(cronjob)["ARGO_ENV"] == env


def test_the_grace_is_the_specs_n(rendered) -> None:
    """N is 10 minutes: merge-to-sync lag was measured at 0 to 6 (proposal Risk 3)."""
    _, cronjob = rendered
    assert _env(cronjob)["GRACE_SECONDS"] == "600"


def test_one_run_prints_one_verdict(rendered) -> None:
    """A retried pod would print a second line, and `last_over_time` keeps the last."""
    _, cronjob = rendered
    job = cronjob["spec"]["jobTemplate"]["spec"]
    assert job["backoffLimit"] == 0
    assert cronjob["spec"]["concurrencyPolicy"] == "Forbid"


def test_the_pod_holds_no_api_token(rendered) -> None:
    """GitHub is its only peer, so a token would only be something to steal."""
    _, cronjob = rendered
    assert cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]["automountServiceAccountToken"] is False


def test_the_rule_window_holds_more_than_one_run(rendered) -> None:
    """The emitter's period must leave margin inside the rule's window (OBS-017).

    One late run must not empty the window and page on a healthy delivery.
    """
    _, cronjob = rendered
    period = re.fullmatch(r"\*/(\d+) \* \* \* \*", cronjob["spec"]["schedule"])
    assert period, cronjob["spec"]["schedule"]
    rules = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    (rule,) = [r for g in rules["groups"] for r in g["rules"] if r["uid"] == "gitops003-argo-delivery"]
    (query,) = [d for d in rule["data"] if d["datasourceUid"] == "loki"]
    windows = [int(m) for m in re.findall(r"\[(\d+)m\]", query["model"]["expr"])]
    assert windows, query["model"]["expr"]
    assert min(windows) >= 2 * int(period.group(1)), windows
