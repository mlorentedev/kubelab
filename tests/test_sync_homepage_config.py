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
