"""#2416: Homepage is retired, and everything that served it went with it.

The owner chose option A on 2026-10-17: `home.kubelab.live` goes away entirely, and
public status comes from Uptime Kuma's status page, never from a proxy into the
tailnet. A retirement that leaves one piece behind is how a service comes back
half-alive: a DNS record pointing at a route nobody serves, a monitor paging on
it, an Authelia rule for a host that no longer exists. This test names each piece
once.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "infra/config/values/common.yaml"


def _common() -> dict:
    return yaml.safe_load(COMMON.read_text(encoding="utf-8"))


def test_the_service_is_no_longer_declared() -> None:
    config = _common()
    assert "homepage" not in config["apps"]["services"]["observability"]
    assert "homepage" not in config["apps"]["services"]["security"]["authelia"]["break_glass"]


def test_no_dns_record_points_at_it() -> None:
    records = json.loads((ROOT / "infra/terraform/dns/services.json").read_text(encoding="utf-8"))
    assert not [r for r in records if r["name"] == "home" and r["zone"] == "kubelab"]


def test_no_monitor_probes_it() -> None:
    text = (ROOT / "infra/config/uptime-kuma/monitors.json").read_text(encoding="utf-8")
    assert "home.kubelab.live" not in text
    assert "homepage-cockpit" not in text


def test_authelia_has_no_rule_for_it() -> None:
    text = (ROOT / "infra/k8s/overlays/prod/authelia-config/configuration.yml").read_text(encoding="utf-8")
    assert "home.kubelab.live" not in text


def test_its_manifests_and_generator_are_gone() -> None:
    for path in (
        "infra/k8s/base/services/homepage.yaml",
        "infra/k8s/base/services/homepage-config",
        "infra/k8s/base/services/homepage-templates",
        "toolkit/scripts/sync_homepage_config.py",
    ):
        assert not (ROOT / path).exists(), path


@pytest.mark.parametrize("overlay", ["staging", "prod"])
def test_no_overlay_renders_it(overlay: str) -> None:
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not installed")
    rendered = subprocess.run(
        ["kubectl", "kustomize", str(ROOT / "infra/k8s/overlays" / overlay)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "gethomepage" not in rendered
    assert "home.kubelab.live" not in rendered
    names = [
        doc["metadata"]["name"]
        for doc in yaml.safe_load_all(rendered)
        if doc and doc.get("metadata", {}).get("name", "").startswith("homepage")
    ]
    assert names == []
