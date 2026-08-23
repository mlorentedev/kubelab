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


def test_security_rules_structure_and_syntax() -> None:
    """Verify security-rules.yaml contains CrowdSec perimeter defense rules."""
    sec_path = GRAFANA_ALERTING_DIR / "security-rules.yaml"
    assert sec_path.is_file(), f"{sec_path} must exist"

    data = yaml.safe_load(sec_path.read_text(encoding="utf-8"))
    assert data.get("apiVersion") == 1
    groups = data.get("groups", [])
    assert len(groups) >= 1
    assert groups[0]["name"] == "security"

    rules = groups[0]["rules"]
    uids = {r["uid"] for r in rules}
    assert "obs015-crowdsec-ban-surge" in uids
