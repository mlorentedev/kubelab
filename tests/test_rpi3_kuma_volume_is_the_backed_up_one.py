"""Uptime Kuma runs on the volume the backup declares live (#1092).

The Compose template named `uptime-kuma_uptime_kuma_data` from #141, an orphan
frozen since 2026-03-28, while the container ran on `uptime_kuma_data`. Nothing
noticed while rpi3 went unprovisioned. The first provision since (2026-10-02)
recreated Kuma on the orphan, so the external monitor came up on six-month-old
data. The volume name now comes from `backup.sources.rpi3.uptime_kuma.volume`,
the one declaration that was right.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / "infra/ansible/roles/rpi3_services/templates/compose.yml.j2"
PLAYBOOK = REPO / "infra/ansible/playbooks/provision-rpi3.yml"
COMMON = REPO / "infra/config/values/common.yaml"


def _role_vars() -> dict:
    for play in yaml.safe_load(PLAYBOOK.read_text()):
        for role in play.get("roles") or []:
            if isinstance(role, dict) and role.get("role", "").endswith("rpi3_services"):
                return role.get("vars") or {}
    raise AssertionError("rpi3_services is not in provision-rpi3.yml")


def test_the_volume_name_is_rendered_from_the_backup_ssot() -> None:
    assert _role_vars()["uptime_kuma_volume"] == "{{ config.backup.sources.rpi3.uptime_kuma.volume }}"
    assert "name: {{ uptime_kuma_volume }}" in TEMPLATE.read_text()


def test_no_volume_name_is_hardcoded_in_the_template() -> None:
    assert "uptime-kuma_uptime_kuma_data" not in TEMPLATE.read_text()


def test_the_ssot_names_the_live_volume() -> None:
    common = yaml.safe_load(COMMON.read_text())
    assert common["backup"]["sources"]["rpi3"]["uptime_kuma"]["volume"] == "uptime_kuma_data"
