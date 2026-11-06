"""`build_service_tables`: the service rows `compute_total_services` counts.

They lived in the Homepage generator until #2416 retired Homepage; the platform
manifest is the consumer that remains.
"""

from __future__ import annotations

import pytest
import yaml

from toolkit.features import platform_manifest


class TestBuildServiceTables:
    def test_n8n_version_resolves_from_automation_not_core(self) -> None:
        # Found during TOOL-020 implementation, not in the original ticket:
        # n8n lives at apps.services.automation.n8n in common.yaml, but the
        # lookup read services.core.n8n — always empty, so every regeneration
        # dropped the version and read as SSOT drift on every run (any OS).
        config = _minimal_config(services={"automation": {"n8n": {"image": "n8nio/n8n:2.12.3"}}})
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
        config = _minimal_config(services={"ai": {"open_webui": webui}})
        _staging, _prod, shared = platform_manifest.build_service_tables(config)
        row = next(s for s in shared if s["name"] == "Open WebUI")
        assert row["url"] == "https://chat.example.test"
        assert row["health"] == "http://ace2.example.internal:3080/health"
        assert row["version"] == "0.11.4"
        assert row["category"] == "AI"

    def test_no_open_webui_row_without_its_ssot_block(self) -> None:
        config = _minimal_config()
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
        config = _minimal_config()
        _staging, _prod, shared = platform_manifest.build_service_tables(config)
        pihole = next(s for s in shared if s["name"] == "Pi-hole")
        assert pihole["url"] == "https://pihole.kubelab.live"
        assert pihole["health"] == "https://pihole.kubelab.live/admin/"
        assert "staging" not in pihole["url"]
        assert "staging" not in pihole["health"]

    def test_headscale_health_is_its_declared_health_path(self) -> None:
        # #3010: the row hardcoded `/health` beside a `health_path` its siblings read.
        # The path is right (v0.28 answers it, measured 2026-11-06); the literal was not.
        headscale = {"image": "headscale/headscale:v0.28.0", "health_path": "/declared"}
        config = _minimal_config("example.test", services={"core": {"headscale": headscale}})
        _staging, _prod, shared = platform_manifest.build_service_tables(config)
        row = next(s for s in shared if s["name"] == "Headscale")
        assert row["health"] == "https://vpn.example.test/declared"


# Where each row's `health_path` lives in common.yaml (#3181). The manifest reads
# it strictly, so deleting one must fail the render and name the service, never
# fall back to a literal that hides the drift.
_HEALTH_PATH_HOMES = {
    "api": ("platform", "api"),
    "authelia": ("services", "security", "authelia"),
    "crowdsec": ("services", "security", "crowdsec"),
    "n8n": ("services", "automation", "n8n"),
    "grafana": ("services", "observability", "grafana"),
    "loki": ("services", "observability", "loki"),
    "gitea": ("services", "core", "gitea"),
    "headscale": ("services", "core", "headscale"),
}


def _minimal_config(base: str = "kubelab.live", services: dict | None = None) -> dict:
    """The smallest config the tables render: each row's `health_path`, then `services` merged in."""
    apps: dict = {"services": {}, "platform": {}}
    for home in _HEALTH_PATH_HOMES.values():
        node = apps
        for key in home:
            node = node.setdefault(key, {})
        node["health_path"] = "/health"
    for group, blocks in (services or {}).items():
        for name, block in blocks.items():
            apps["services"].setdefault(group, {}).setdefault(name, {}).update(block)
    return {"global": {"base_domain": base}, "apps": apps}


def _real_config() -> dict:
    return yaml.safe_load(platform_manifest.COMMON_YAML_PATH.read_text(encoding="utf-8"))


def _block(config: dict, home: tuple[str, ...]) -> dict:
    node = config["apps"]
    for key in home:
        node = node[key]
    return node


class TestHealthPathIsReadStrictly:
    def test_every_row_reads_the_declared_path(self) -> None:
        config = _real_config()
        for home in _HEALTH_PATH_HOMES.values():
            _block(config, home)["health_path"] = "/declared-" + home[-1]
        staging, prod, shared = platform_manifest.build_service_tables(config)
        healths = [s["health"] for s in staging + prod + shared]
        for home in _HEALTH_PATH_HOMES.values():
            assert any(h.endswith("/declared-" + home[-1]) for h in healths), home[-1]

    def test_no_row_reads_health_path_with_a_default(self) -> None:
        # The map above only covers the rows it names. A row added later with
        # `svc.get("health_path", ...)` would escape both other tests, so the
        # source itself must not contain the fallback shape.
        source = platform_manifest.Path(platform_manifest.__file__).read_text(encoding="utf-8")
        assert '.get("health_path"' not in source

    @pytest.mark.parametrize("service", sorted(_HEALTH_PATH_HOMES))
    def test_a_removed_health_path_fails_and_names_the_service(self, service: str) -> None:
        config = _real_config()
        del _block(config, _HEALTH_PATH_HOMES[service])["health_path"]
        with pytest.raises(KeyError, match=service):
            platform_manifest.build_service_tables(config)
