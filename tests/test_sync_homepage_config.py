"""Tests for sync_homepage_config — mermaid.ink retry hardening (TOOL-020).

`toolkit sync all --check` now runs in CI (the new windows-sync-check job),
which is the first time `render_mermaid_svg`'s network call is exercised
under a gate. A single flaky request must not fail the whole sync.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from toolkit.scripts import sync_homepage_config


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


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
        staging, prod, _shared = sync_homepage_config.build_service_tables(config)
        n8n_entries = [s for s in staging + prod if s["name"] == "n8n"]
        assert n8n_entries
        assert all(s["version"] == "2.12.3" for s in n8n_entries)

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
        _staging, _prod, shared = sync_homepage_config.build_service_tables(config)
        pihole = next(s for s in shared if s["name"] == "Pi-hole")
        assert pihole["url"] == "https://pihole.kubelab.live"
        assert pihole["health"] == "https://pihole.kubelab.live/admin/"
        assert "staging" not in pihole["url"]
        assert "staging" not in pihole["health"]


class TestBuildDnsMap:
    def test_no_stale_staging_pihole_row_or_dead_extra_records_row(self) -> None:
        config = {"networking": {"vps": {"public_ip": "1.2.3.4"}, "nodes": {"ace1": {"tailscale_ip": "100.64.0.11"}}}}
        dns_map = sync_homepage_config.build_dns_map(config)
        assert "pihole.staging.kubelab.live" not in dns_map
        assert "extra_records" not in dns_map

    def test_pihole_apex_name_lists_ace1_tailscale_ip(self) -> None:
        config = {"networking": {"vps": {"public_ip": "1.2.3.4"}, "nodes": {"ace1": {"tailscale_ip": "100.64.0.11"}}}}
        dns_map = sync_homepage_config.build_dns_map(config)
        pihole_line = next(line for line in dns_map.splitlines() if line.strip().startswith("pihole.kubelab.live"))
        assert "100.64.0.11" in pihole_line


class TestBuildMermaidDns:
    def test_extra_records_edge_no_longer_names_pihole(self) -> None:
        # pihole never actually used this path (extra_records has never
        # resolved for anything, #964) and definitely doesn't now.
        config = {"networking": {"vps": {"public_ip": "1.2.3.4"}, "nodes": {"ace1": {"tailscale_ip": "100.64.0.11"}}}}
        diagram = sync_homepage_config.build_mermaid_dns(config)
        extra_records_line = next(line for line in diagram.splitlines() if "extra_records" in line)
        assert "pihole" not in extra_records_line


class TestRenderMermaidSvgRetries:
    def test_succeeds_on_first_attempt_without_retrying(self, monkeypatch: object) -> None:
        calls = MagicMock(side_effect=[_FakeResponse(b"<svg>ok</svg>")])
        monkeypatch.setattr(sync_homepage_config, "urlopen", calls)

        result = sync_homepage_config.render_mermaid_svg("graph TD; A-->B", retries=2, backoff_seconds=0)

        assert result == "<svg>ok</svg>"
        assert calls.call_count == 1

    def test_retries_after_transient_failure_then_succeeds(self, monkeypatch: object) -> None:
        calls = MagicMock(side_effect=[OSError("timeout"), _FakeResponse(b"<svg>ok</svg>")])
        monkeypatch.setattr(sync_homepage_config, "urlopen", calls)

        result = sync_homepage_config.render_mermaid_svg("graph TD; A-->B", retries=2, backoff_seconds=0)

        assert result == "<svg>ok</svg>"
        assert calls.call_count == 2

    def test_returns_empty_string_after_exhausting_retries(self, monkeypatch: object) -> None:
        calls = MagicMock(side_effect=OSError("unreachable"))
        monkeypatch.setattr(sync_homepage_config, "urlopen", calls)

        result = sync_homepage_config.render_mermaid_svg("graph TD; A-->B", retries=2, backoff_seconds=0)

        assert result == ""
        assert calls.call_count == 3  # initial + 2 retries
