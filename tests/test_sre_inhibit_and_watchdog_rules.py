"""Tests for OBS-015 SRE inhibit rules and Watchdog DeadMansSwitch alerting."""

from __future__ import annotations

import pathlib
import yaml
import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
GRAFANA_ALERTING_DIR = REPO_ROOT / "infra" / "k8s" / "base" / "services" / "grafana-alerting"


def test_inhibit_rules_structure_and_syntax() -> None:
    """Verify inhibit-rules.yaml is valid YAML and contains required cascading rules."""
    inhibit_file = GRAFANA_ALERTING_DIR / "inhibit-rules.yaml"
    assert inhibit_file.is_file(), f"{inhibit_file} must exist"

    data = yaml.safe_load(inhibit_file.read_text(encoding="utf-8"))
    assert data.get("apiVersion") == 1, "apiVersion must be 1"
    assert "inhibitRules" in data, "inhibitRules key must be present"

    rules = data["inhibitRules"]
    assert len(rules) >= 4, f"Expected at least 4 inhibit rules, found {len(rules)}"

    # 1. Critical -> Warning/Info suppression
    sev_rule = next(
        (r for r in rules if "severity = critical" in r.get("source_matchers", [])), None
    )
    assert sev_rule is not None, "Rule suppressing warning/info on critical must exist"
    assert "severity =~ warning|info" in sev_rule.get("target_matchers", [])
    assert "alertname" in sev_rule.get("equal", [])
    assert "namespace" in sev_rule.get("equal", [])

    # 2. Node/Host Down suppression
    node_rule = next(
        (r for r in rules if any("NodeNotReady" in m for m in r.get("source_matchers", []))),
        None,
    )
    assert node_rule is not None, "NodeNotReady suppression rule must exist"
    assert "instance" in node_rule.get("equal", [])

    # 3. Traefik/Ingress Down suppression
    edge_rule = next(
        (r for r in rules if any("TraefikDown" in m for m in r.get("source_matchers", []))),
        None,
    )
    assert edge_rule is not None, "TraefikDown suppression rule must exist"
    assert "cluster" in edge_rule.get("equal", [])

    # 4. R2 Backup Failure suppression
    backup_rule = next(
        (r for r in rules if "alertname = R2BackupJobFailed" in r.get("source_matchers", [])),
        None,
    )
    assert backup_rule is not None, "R2BackupJobFailed suppression rule must exist"
    assert "alertname = R2BackupFreshnessStale" in backup_rule.get("target_matchers", [])
    assert "bucket" in backup_rule.get("equal", [])


def test_sre_rules_structure_and_syntax() -> None:
    """Verify sre-rules.yaml contains valid Watchdog and TLS rules."""
    sre_file = GRAFANA_ALERTING_DIR / "sre-rules.yaml"
    assert sre_file.is_file(), f"{sre_file} must exist"

    data = yaml.safe_load(sre_file.read_text(encoding="utf-8"))
    assert data.get("apiVersion") == 1, "apiVersion must be 1"
    assert "groups" in data, "groups key must be present"

    groups = data["groups"]
    assert len(groups) >= 1
    group = groups[0]
    assert group.get("name") == "sre-watchdog"
    assert group.get("folder") == "kubelab"

    rules = group.get("rules", [])
    uids = {r.get("uid") for r in rules}

    # Watchdog DeadMansSwitch assertion
    assert "obs015-deadmansswitch-heartbeat" in uids, "DeadMansSwitch rule must exist"
    watchdog = next(r for r in rules if r.get("uid") == "obs015-deadmansswitch-heartbeat")
    assert watchdog.get("noDataState") == "Alerting", "Watchdog must alert on NoData (DeadMansSwitch)"
    assert watchdog.get("execErrState") == "Alerting"

    # TLS early warning assertion
    assert "obs015-tls-early-warning" in uids, "TLS early warning rule must exist"
    tls_rule = next(r for r in rules if r.get("uid") == "obs015-tls-early-warning")
    assert tls_rule.get("for") == "5m"
    assert "runbook_url" in tls_rule.get("annotations", {})
