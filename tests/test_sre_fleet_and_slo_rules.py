"""Tests for OBS-015 SRE fleet capacity watchers, multi-burn-rate SLOs, and security alerts."""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
GRAFANA_ALERTING_DIR = REPO_ROOT / "infra" / "k8s" / "base" / "services" / "grafana-alerting"
SERVICES_DIR = REPO_ROOT / "infra" / "k8s" / "base" / "services"


def test_disk_watcher_manifest() -> None:
    """Verify disk-watcher.yaml defines valid ServiceAccount, RBAC, and CronJob."""
    manifest_path = SERVICES_DIR / "disk-watcher.yaml"
    assert manifest_path.is_file(), f"{manifest_path} must exist"

    docs = list(yaml.safe_load_all(manifest_path.read_text(encoding="utf-8")))
    kinds = {doc.get("kind"): doc for doc in docs if doc}

    assert "ServiceAccount" in kinds
    assert kinds["ServiceAccount"]["metadata"]["name"] == "disk-watcher"

    assert "Role" in kinds
    role = kinds["Role"]
    rules = role.get("rules", [])
    assert any("persistentvolumeclaims" in r.get("resources", []) for r in rules)
    assert not any("pods" in r.get("resources", []) for r in rules)

    assert "CronJob" in kinds
    cronjob = kinds["CronJob"]
    assert cronjob["metadata"]["name"] == "disk-watcher"
    assert cronjob["spec"]["schedule"] == "*/15 * * * *"
    template_spec = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    assert template_spec["serviceAccountName"] == "disk-watcher"
    assert template_spec["automountServiceAccountToken"] is True


def test_disk_rules_structure_and_syntax() -> None:
    """Verify disk-rules.yaml contains valid PVC and disk saturation rules."""
    rules_path = GRAFANA_ALERTING_DIR / "disk-rules.yaml"
    assert rules_path.is_file(), f"{rules_path} must exist"

    data = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    assert data.get("apiVersion") == 1
    groups = data.get("groups", [])
    assert len(groups) >= 1
    assert groups[0]["name"] == "storage"

    rules = groups[0]["rules"]
    uids = {r["uid"] for r in rules}
    assert "obs015-pvc-unbound-failure" in uids
    assert "obs015-disk-root-saturation" in uids

    # #1668: the PVC rule lets a vanished claim resolve; watcher silence is its own rule.
    pvc_rule = next(r for r in rules if r["uid"] == "obs015-pvc-unbound-failure")
    assert pvc_rule.get("noDataState") == "OK"
    silent_rule = next(r for r in rules if r["uid"] == "obs042-disk-watcher-silent")
    assert silent_rule.get("noDataState") == "Alerting"


def test_slo_rules_structure_and_syntax() -> None:
    """Verify slo-rules.yaml contains multi-burn-rate SLO alert rules."""
    slo_path = GRAFANA_ALERTING_DIR / "slo-rules.yaml"
    assert slo_path.is_file(), f"{slo_path} must exist"

    data = yaml.safe_load(slo_path.read_text(encoding="utf-8"))
    assert data.get("apiVersion") == 1
    groups = data.get("groups", [])
    assert len(groups) >= 1
    assert groups[0]["name"] == "slo-multi-burn-rate"

    rules = groups[0]["rules"]
    uids = {r["uid"] for r in rules}
    assert "obs015-slo-fast-burn-rate" in uids
    assert "obs015-slo-medium-burn-rate" in uids


def _slo_query(uid: str) -> str:
    data = yaml.safe_load((GRAFANA_ALERTING_DIR / "slo-rules.yaml").read_text(encoding="utf-8"))
    rule = next(r for r in data["groups"][0]["rules"] if r["uid"] == uid)
    return next(d["model"]["expr"] for d in rule["data"] if d["refId"] == "A")


@pytest.mark.parametrize("uid", ["obs015-slo-fast-burn-rate", "obs015-slo-medium-burn-rate"])
def test_5xx_rules_count_the_parsed_status_not_the_text(uid: str) -> None:
    # #3140: `|~ "\b(500|502|503|504)\b"` counted any line carrying one of those
    # numbers as a word, and read no status at all.
    query = _slo_query(uid)
    assert "| json" in query
    assert re.search(r"DownstreamStatus\s*>=\s*500", query), query
    assert '__error__=""' in query, "a line that is not JSON must not count"
    assert "|~" not in query, "a raw-text match is back"


@pytest.mark.parametrize("uid", ["obs015-slo-fast-burn-rate", "obs015-slo-medium-burn-rate"])
def test_5xx_rules_ignore_the_load_test_route(uid: str) -> None:
    # The load test overloads staging on purpose through its own route; on
    # 2026-11-06 a run at the knee fired both rules.
    from toolkit.features import load_test

    query = _slo_query(uid)
    assert re.search(rf'RouterName\s*!~\s*"[^"]*{re.escape(load_test.ROUTE_NAME)}[^"]*"', query), query


def test_security_rules_stay_retired_until_the_bouncer_can_see_client_ips() -> None:
    """The inverse of what this asserted until 2026-09-01.

    It required `security-rules.yaml` to exist and to contain
    `obs015-crowdsec-ban-surge`. That rule fired continuously from 2026-08-23
    and no ban ever caused it: its LogQL counted log LINES matching
    `(?i)(ban|decision|blocked|remediation)`, and the bouncer's own
    `GET /v1/decisions/stream` poll — every 60s — matches `decision`. Measured
    from Loki's query log: 20 matching lines per 10m window against a `> 5`
    threshold, forever, on an idle CrowdSec.

    Kept as an assertion rather than deleted, because the reason not to re-add
    a *corrected* version is the part worth enforcing. `cscli metrics` reports
    `dropped requests = 0` across seven days while ~4,500 CAPI blocklist
    decisions stand and 13 prod routes carry the bouncer middleware — the
    bouncer compares `10.42.0.x` against public addresses because klipper-lb
    masquerades every source IP (#1067), so it can never match. A fixed query
    would never fire instead of always firing.

    When #1067 lands and the bouncer sees real client IPs, replace this with a
    positive assertion about an alert on `dropped requests`. Re-adding the file
    without doing so should fail here, deliberately.
    """
    # Anchor the negative assertion before making it. `assert not is_file()`
    # passes for every reason a path can be wrong -- a renamed directory, a
    # moved test -- so on its own it is a guard that reports success precisely
    # when it has stopped looking at anything. Proving the directory is there
    # and still holds a sibling makes the absence below mean what it says.
    assert GRAFANA_ALERTING_DIR.is_dir(), (
        f"{GRAFANA_ALERTING_DIR} does not exist, so the assertion below would "
        "pass vacuously. The alerting directory moved; fix this path."
    )
    assert (GRAFANA_ALERTING_DIR / "slo-rules.yaml").is_file(), (
        "a known sibling rule file is missing, so this directory is not the one "
        "this test means; the absence below would prove nothing."
    )

    sec_path = GRAFANA_ALERTING_DIR / "security-rules.yaml"
    assert not sec_path.is_file(), (
        f"{sec_path} is back. Security alerting here needs an enforcement path "
        "that can act: until #1067 gives the CrowdSec bouncer real client IPs, "
        "any rule about bans has no true-positive path. If #1067 has landed, "
        "update this test to assert the new rule instead of removing it."
    )


@pytest.mark.parametrize("uid", ["obs015-slo-fast-burn-rate", "obs015-slo-medium-burn-rate"])
def test_5xx_rules_filter_only_on_fields_the_access_log_keeps(uid: str) -> None:
    # The edge drops every access-log field it does not list; a rule filtering on a
    # dropped field would count zero lines and never fire, with no error.
    from tests.test_traefik_access_log_slow_only import _access

    kept = {name for name, mode in _access()["fields"]["general"]["names"].items() if mode == "keep"}
    used = set(re.findall(r"\|\s*([A-Z][A-Za-z]+)\s*(?:>=|!~|=~|==|!=|>|<)", _slo_query(uid)))
    assert used == {"DownstreamStatus", "RouterName"}, used
    assert used <= kept, used - kept
