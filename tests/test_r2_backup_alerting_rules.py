"""Tests for R2 Backup in-cluster watcher and Grafana alerting rules (OBS-015)."""

from __future__ import annotations

from pathlib import Path
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVICES_DIR = REPO_ROOT / "infra" / "k8s" / "base" / "services"


def test_r2_backup_rules_syntax_and_structure() -> None:
    rules_file = SERVICES_DIR / "grafana-alerting" / "r2-backup-rules.yaml"
    assert rules_file.exists(), "r2-backup-rules.yaml must exist"

    data = yaml.safe_load(rules_file.read_text())
    assert data["apiVersion"] == 1
    assert "groups" in data
    assert len(data["groups"]) > 0

    group = data["groups"][0]
    assert group["name"] == "backup"
    assert len(group["rules"]) > 0

    rule = group["rules"][0]
    assert rule["uid"] == "obs015-r2-backup-health"
    assert rule["noDataState"] == "Alerting", "Loss of watcher logs must alert immediately"
    assert rule["execErrState"] == "Alerting"


def test_r2_backup_watcher_manifest() -> None:
    watcher_file = SERVICES_DIR / "r2-backup-watcher.yaml"
    assert watcher_file.exists(), "r2-backup-watcher.yaml must exist"

    docs = list(yaml.safe_load_all(watcher_file.read_text()))
    kinds = [d["kind"] for d in docs if d and "kind" in d]
    assert "ServiceAccount" in kinds
    assert "CronJob" in kinds

    cronjob = next(d for d in docs if d.get("kind") == "CronJob")
    assert cronjob["metadata"]["name"] == "r2-backup-watcher"
    assert cronjob["spec"]["schedule"] == "0 6 * * *"


def test_kustomization_includes_r2_backup_watcher_and_rules() -> None:
    kustomization_file = REPO_ROOT / "infra" / "k8s" / "base" / "kustomization.yaml"
    content = kustomization_file.read_text()
    assert "services/r2-backup-watcher.yaml" in content
    assert "services/grafana-alerting/r2-backup-rules.yaml" in content
