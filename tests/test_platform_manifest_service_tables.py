"""`build_service_tables`: the service rows `compute_total_services` counts.

They lived in the Homepage generator until #2416 retired Homepage; the platform
manifest is the consumer that remains.
"""

from __future__ import annotations

from toolkit.features import platform_manifest


class TestBuildServiceTables:
    def test_n8n_version_resolves_from_automation_not_core(self) -> None:
        # Found during TOOL-020 implementation, not in the original ticket:
        # n8n lives at apps.services.automation.n8n in common.yaml, but the
        # lookup read services.core.n8n — always empty, so every regeneration
        # dropped the version and read as SSOT drift on every run (any OS).
        config = {
            "global": {"base_domain": "kubelab.live"},
            "apps": {
                "services": {
                    "automation": {"n8n": {"image": "n8nio/n8n:2.12.3"}},
                },
                "platform": {},
            },
        }
        staging, prod, _shared = platform_manifest.build_service_tables(config)
        n8n_entries = [s for s in staging + prod if s["name"] == "n8n"]
        assert n8n_entries
        assert all(s["version"] == "2.12.3" for s in n8n_entries)

    def test_open_webui_row_is_derived_from_its_ssot_block(self) -> None:
        # AI-009: the link is the public name, the health probe ace2's own
        # address, both from the SSOT, never a literal like Pollex's row.
        webui = {
            "image": "ghcr.io/open-webui/open-webui:v0.11.4",
            "host": "ace2.example.internal",
            "scheme": "http",
            "default_port": 3080,
            "domain": "chat.example.test",
            "health_path": "/health",
        }
        config = {
            "global": {"base_domain": "kubelab.live"},
            "apps": {"services": {"ai": {"open_webui": webui}}, "platform": {}},
        }
        _staging, _prod, shared = platform_manifest.build_service_tables(config)
        row = next(s for s in shared if s["name"] == "Open WebUI")
        assert row["url"] == "https://chat.example.test"
        assert row["health"] == "http://ace2.example.internal:3080/health"
        assert row["version"] == "0.11.4"
        assert row["category"] == "AI"

    def test_no_open_webui_row_without_its_ssot_block(self) -> None:
        config = {"global": {"base_domain": "kubelab.live"}, "apps": {"services": {}, "platform": {}}}
        _staging, _prod, shared = platform_manifest.build_service_tables(config)
        assert not any(s["name"] == "Open WebUI" for s in shared)

    def test_pihole_url_matches_the_apex_ssot_not_the_retired_staging_name(self) -> None:
        # Adversarial review of OPS-022 (#969): the rename moved pihole off
        # base/ and onto pihole.kubelab.live, but this generator hardcoded
        # "pihole.staging.{base}" — unlike its "shared" siblings (Argo CD,
        # Headscale, Uptime Kuma), which all use {base} directly with no env
        # prefix. Both the clickable link AND the live client-side health
        # fetch (custom.js checkHealth(), no-cors mode) pointed at a name
        # that now 404s, and no-cors resolves on any reachable response —
        # so the dashboard would have shown a false "up" dot for a dead link.
        config = {"global": {"base_domain": "kubelab.live"}, "apps": {"services": {}, "platform": {}}}
        _staging, _prod, shared = platform_manifest.build_service_tables(config)
        pihole = next(s for s in shared if s["name"] == "Pi-hole")
        assert pihole["url"] == "https://pihole.kubelab.live"
        assert pihole["health"] == "https://pihole.kubelab.live/admin/"
        assert "staging" not in pihole["url"]
        assert "staging" not in pihole["health"]
