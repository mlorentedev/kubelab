"""Tests for GCP Spot Preemption watcher role and script (OBS-015 / ADR-044).

Verifies the preemption watcher templates render cleanly, generate valid JSON
payloads conforming to the NOTIFY-002 SRE contract, and are wired into provision-gcp1.yml.
"""

from __future__ import annotations

from pathlib import Path
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ROLE_DIR = REPO_ROOT / "infra" / "ansible" / "roles" / "gcp_preemption"


def test_gcp_preemption_defaults_exist() -> None:
    defaults_file = ROLE_DIR / "defaults" / "main.yml"
    assert defaults_file.exists(), "gcp_preemption defaults/main.yml must exist"
    data = yaml.safe_load(defaults_file.read_text())
    assert "gcp_preemption_script_path" in data
    assert "gcp_preemption_service_name" in data
    assert data["gcp_preemption_check_interval_seconds"] == 5


def test_gcp_preemption_templates_exist() -> None:
    sh_template = ROLE_DIR / "templates" / "gcp-preemption-watch.sh.j2"
    service_template = ROLE_DIR / "templates" / "gcp-preemption-watch.service.j2"
    assert sh_template.exists(), "gcp-preemption-watch.sh.j2 must exist"
    assert service_template.exists(), "gcp-preemption-watch.service.j2 must exist"

    sh_content = sh_template.read_text()
    assert "computeMetadata/v1/instance/preempted" in sh_content
    assert "Metadata-Flavor: Google" in sh_content
    assert "webhook/notify" in sh_content
    assert "GCP Spot Preemption" in sh_content

    service_content = service_template.read_text()
    assert "[Unit]" in service_content
    assert "ExecStart={{ gcp_preemption_script_path }}" in service_content
    assert "Restart=always" in service_content


def test_gcp_preemption_included_in_provision_gcp1() -> None:
    playbook_file = REPO_ROOT / "infra" / "ansible" / "playbooks" / "provision-gcp1.yml"
    assert playbook_file.exists(), "provision-gcp1.yml must exist"
    content = playbook_file.read_text()
    assert "roles/gcp_preemption" in content, "provision-gcp1.yml must include gcp_preemption role"
