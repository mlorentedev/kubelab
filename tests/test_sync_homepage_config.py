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


class TestBuildNodeList:
    def test_gcp_node_is_included_in_node_list(self) -> None:
        config = {
            "networking": {
                "nodes": {
                    "ace1": {
                        "dashboard": {
                            "display_name": "ace1",
                            "order": 1,
                            "icon": "mdi-server",
                            "description": "K3s node",
                            "widget": "glances",
                        },
                        "tailscale_ip": "100.64.0.11",
                    }
                },
                "vps": {
                    "dashboard": {
                        "display_name": "vps",
                        "order": 2,
                        "icon": "mdi-server",
                        "description": "VPS node",
                        "widget": "glances",
                    },
                    "tailscale_ip": "100.64.0.5",
                },
                "gcp": {
                    "dashboard": {
                        "display_name": "gcp1",
                        "order": 6,
                        "icon": "mdi-cloud-outline",
                        "description": "GCP Hub",
                        "widget": "ping",
                        "ping_url": "https://argo.kubelab.live",
                    },
                    "tailscale_dns": "gcp1.kubelab.internal",
                },
            }
        }
        nodes = sync_homepage_config.build_node_list(config)
        node_names = [n[0] for n in nodes]
        assert "gcp1" in node_names
        gcp_tile = next(tile for name, tile in nodes if name == "gcp1")
        assert gcp_tile["ping_url"] == "https://argo.kubelab.live"
        assert gcp_tile["glances"] is False


class TestBuildMermaidDns:
    def test_extra_records_edge_retired_from_dns_diagram(self) -> None:
        config = {"networking": {"vps": {"public_ip": "1.2.3.4"}, "nodes": {"ace1": {"tailscale_ip": "100.64.0.11"}}}}
        diagram = sync_homepage_config.build_mermaid_dns(config)
        assert "extra_records" not in diagram


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
