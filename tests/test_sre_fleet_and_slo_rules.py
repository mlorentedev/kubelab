"""Tests for OBS-015 SRE fleet capacity watchers, multi-burn-rate SLOs, and security alerts."""

from __future__ import annotations

import pathlib
import yaml
import pytest

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

    pvc_rule = next(r for r in rules if r["uid"] == "obs015-pvc-unbound-failure")
    assert pvc_rule.get("noDataState") == "Alerting"


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
