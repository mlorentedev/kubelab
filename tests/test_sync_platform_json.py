"""Tests for platform_manifest — IDP public platform manifest extraction (ADR-056 / issue #1347).

Verifies that common.yaml SSOT is deterministically projected into the sanitized public
platform.json manifest required by web (/lab and /lab/idp), strictly enforcing Zero-Addressing
doctrine (no LAN IPs, no VPN IPs, no internal hostnames, no private URLs).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.features import platform_manifest


class TestPlatformManifestGeneration:
    def test_manifest_schema_and_counts(self) -> None:
        manifest = platform_manifest.generate_manifest()

        # 1. Top-level keys
        for key in [
            "generated_at",
            "source_commit",
            "cluster",
            "metrics",
            "nodes",
            "services",
            "diagrams",
        ]:
            assert key in manifest, f"Missing top-level key: {key}"

        # 2. Cluster metadata
        cluster = manifest["cluster"]
        assert cluster["name"] == "KubeLab Hybrid Cloud & Edge Platform"
        assert cluster["activeNodes"] == 8
        assert cluster["kubernetesClusters"] == 3
        assert cluster["kubernetesNodes"] == 3
        assert cluster["totalServices"] >= 14

        # 3. Nodes fleet (9 nodes total: 8 active + 1 standby)
        nodes: list[dict[str, Any]] = manifest["nodes"]
        assert len(nodes) == 9
        node_ids = {n["id"] for n in nodes}
        expected_nodes = {
            "vps",
            "gcp1",
            "ace1",
            "ace2",
            "jetson",
            "beelink",
            "rpi4",
            "rpi3",
            "aws1",
        }
        assert node_ids == expected_nodes

        aws1 = next(n for n in nodes if n["id"] == "aws1")
        assert aws1["status"] == "standby"
        assert aws1["runtime"] == "standby"

        vps = next(n for n in nodes if n["id"] == "vps")
        assert vps["status"] == "healthy"
        assert vps["runtime"] == "k3s"

        # 4. Platform services (14 canonical services)
        services: list[dict[str, Any]] = manifest["services"]
        assert len(services) == 14
        service_slugs = {s["slug"] for s in services}
        expected_slugs = {
            "pollex",
            "hive",
            "ollama",
            "kubelab-api",
            "traefik",
            "headscale",
            "authelia",
            "argocd",
            "gitea",
            "grafana",
            "loki",
            "uptime-kuma",
            "minio",
            "coredns",
        }
        assert service_slugs == expected_slugs

        # 5. Architecture diagrams (5 canonical diagrams)
        diagrams: list[dict[str, Any]] = manifest["diagrams"]
        assert len(diagrams) == 5
        diagram_ids = {d["id"] for d in diagrams}
        expected_diagrams = {"topology", "gitops", "security", "ai-mcp", "dns"}
        assert diagram_ids == expected_diagrams

    def test_zero_addressing_sanitization(self) -> None:
        manifest = platform_manifest.generate_manifest()
        serialized = json.dumps(manifest, indent=2)

        # Zero-Addressing (ADR-056 §3): no IP addresses anywhere
        ip_matches = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", serialized)
        assert not ip_matches, f"Detected IP addresses leaked into manifest: {ip_matches}"

        # No internal hostnames or MagicDNS suffixes
        assert ".internal" not in serialized
        assert "100.64." not in serialized
        assert "172.16." not in serialized

        # Private services must not leak URLs
        for service in manifest["services"]:
            if not service.get("isPublic", False):
                assert service.get("url") is None, f"Private service {service['slug']} leaked URL: {service.get('url')}"
                assert service.get("healthEndpoint") is None, f"Private service {service['slug']} leaked healthEndpoint"
            else:
                assert service.get("url") is not None, f"Public service {service['slug']} missing public URL"

    def test_provenance_determinism(self) -> None:
        manifest = platform_manifest.generate_manifest()
        assert re.match(r"^[a-f0-9]{40}$", manifest["source_commit"]), (
            f"Invalid commit sha: {manifest['source_commit']}"
        )
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", manifest["generated_at"]), (
            f"Invalid ISO 8601 date: {manifest['generated_at']}"
        )


class TestPlatformManifestDriftGate:
    def test_drift_gate_detects_mutation(self, tmp_path: Path) -> None:
        target_file = tmp_path / "platform.json"

        # 1. Sync cleanly
        rc = platform_manifest.sync(output_path=target_file, check=False)
        assert rc == 0
        assert target_file.exists()

        # 2. Check passes when unchanged
        rc_check = platform_manifest.sync(output_path=target_file, check=True)
        assert rc_check == 0

        # 3. Check fails when mutated
        data = json.loads(target_file.read_text(encoding="utf-8"))
        data["cluster"]["name"] = "Drifted Cluster Name"
        target_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        rc_drift = platform_manifest.sync(output_path=target_file, check=True)
        assert rc_drift == 1


class TestPlatformManifestEdgeCases:
    def test_missing_config_raises_file_not_found(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.yaml"
        with pytest.raises(FileNotFoundError, match="Configuration file not found"):
            platform_manifest.generate_manifest(config_path=missing)

    def test_provenance_content_hash(self, tmp_path: Path) -> None:
        fake_cfg = tmp_path / "common.yaml"
        fake_cfg.write_text("k3s: {version: 'v1.34.4'}\n", encoding="utf-8")

        source_hash = platform_manifest.compute_source_hash(fake_cfg)
        assert len(source_hash) == 40
        assert re.match(r"^[0-9a-f]{40}$", source_hash)

        ts, sha = platform_manifest._get_provenance(fake_cfg)
        assert sha == source_hash
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", ts)

    def test_zero_addressing_guard_catches_leaked_ip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mutated_services = list(platform_manifest.SERVICE_CATALOG_DEFAULTS)
        mutated_services.append(
            {
                "slug": "leak",
                "name": "Leak",
                "category": "Core Gateway",
                "categoryEs": "Gateway Principal",
                "description": "Leaked IP 192.168.1.50 in description",
                "descriptionEs": "IP filtrada",
                "node": "vps",
                "env": "prod",
                "tech": ["Go"],
                "isPublic": False,
                "status": "operational",
            }
        )
        monkeypatch.setattr(platform_manifest, "SERVICE_CATALOG_DEFAULTS", mutated_services)
        with pytest.raises(ValueError, match="Zero-Addressing violation: IPv4 address detected"):
            platform_manifest.generate_manifest()

    def test_zero_addressing_guard_catches_leaked_ipv6(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for ipv6 in ["fd7a:115c:a1e0::/48", "2001:0db8:85a3:0000:0000:8a2e:0370:7334", "::1"]:
            mutated_services = list(platform_manifest.SERVICE_CATALOG_DEFAULTS)
            mutated_services.append(
                {
                    "slug": "ipv6-leak",
                    "name": "Leak",
                    "category": "Core Gateway",
                    "categoryEs": "Gateway Principal",
                    "description": f"Leaked IPv6 {ipv6} in description",
                    "descriptionEs": "IPv6 filtrada",
                    "node": "vps",
                    "env": "prod",
                    "tech": ["Go"],
                    "isPublic": False,
                    "status": "operational",
                }
            )
            monkeypatch.setattr(platform_manifest, "SERVICE_CATALOG_DEFAULTS", mutated_services)
            with pytest.raises(ValueError, match="Zero-Addressing violation: IPv6 address detected"):
                platform_manifest.generate_manifest()

    def test_zero_addressing_guard_catches_internal_hostname(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mutated_services = list(platform_manifest.SERVICE_CATALOG_DEFAULTS)
        mutated_services.append(
            {
                "slug": "internal-leak",
                "name": "Leak",
                "category": "Core Gateway",
                "categoryEs": "Gateway Principal",
                "description": "Host host.kubelab.internal in description",
                "descriptionEs": "Host filtrado",
                "node": "vps",
                "env": "prod",
                "tech": ["Go"],
                "isPublic": False,
                "status": "operational",
            }
        )
        monkeypatch.setattr(platform_manifest, "SERVICE_CATALOG_DEFAULTS", mutated_services)
        with pytest.raises(ValueError, match="Zero-Addressing violation: internal hostname detected"):
            platform_manifest.generate_manifest()

        # Also test .local
        mutated_services[-1]["description"] = "Host edge.cluster.local"
        with pytest.raises(ValueError, match="Zero-Addressing violation: internal hostname detected"):
            platform_manifest.generate_manifest()

    def test_dynamic_projection_from_mock_config(self, tmp_path: Path) -> None:
        mock_yaml = tmp_path / "mock_common.yaml"
        mock_yaml.write_text(
            """
project_name: kubelab
k3s:
  version: "v1.34.4+k3s1"
networking:
  vps:
    location: "always-on"
    dashboard:
      display_name: "Mock VPS"
  nodes:
    ace1:
      location: "on-demand"
      retired: true
    custom_node:
      location: "on-demand"
      ansible_groups: ["dev_node"]
      dashboard:
        display_name: "Custom Node"
clusters:
  staging:
    node: "vps"
apps:
  platform:
    api:
      name: "custom-api"
      domain: "api.kubelab.live"
      health_path: "/v2/health"
      enable_auth: false
      auth_level: "bypass"
""",
            encoding="utf-8",
        )

        manifest = platform_manifest.generate_manifest(config_path=mock_yaml)
        cluster = manifest["cluster"]
        # ace1 was retired, custom_node is active, vps is active -> activeNodes=2
        assert cluster["activeNodes"] == 2
        assert cluster["kubernetesClusters"] == 1
        assert cluster["kubernetesNodes"] == 1

        # Check custom_node was projected
        nodes = manifest["nodes"]
        custom = next(n for n in nodes if n["id"] == "custom_node")
        assert custom["name"] == "Custom Node"
        assert custom["runtime"] == "docker"
        assert custom["tier"] == "homelab"

        # Check dynamic sanitization: api has updated healthEndpoint
        services = manifest["services"]
        api = next(s for s in services if s["slug"] == "kubelab-api")
        assert api["healthEndpoint"] == "https://api.kubelab.live/v2/health"

        # Check private services have no URL
        authelia = next(s for s in services if s["slug"] == "authelia")
        assert "url" not in authelia or authelia["url"] is None

    def test_drift_gate_missing_file_returns_error(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist.json"
        rc = platform_manifest.sync(output_path=missing, check=True)
        assert rc == 1

    def test_drift_gate_across_simulated_commit_boundary(self, tmp_path: Path) -> None:
        mock_yaml = tmp_path / "common.yaml"
        mock_yaml.write_text("k3s: {version: 'v1.34.4'}\napps: {}\n", encoding="utf-8")
        target_json = tmp_path / "platform.json"

        # 1. First sync generates manifest
        rc_sync = platform_manifest.sync(output_path=target_json, check=False, config_path=mock_yaml)
        assert rc_sync == 0
        assert target_json.exists()

        initial_content = target_json.read_text(encoding="utf-8")
        initial_data = json.loads(initial_content)
        assert len(initial_data["source_commit"]) == 40

        # 2. Drift check passes before commit
        assert platform_manifest.sync(output_path=target_json, check=True, config_path=mock_yaml) == 0

        # 3. Simulate git commit boundary: files are committed, content of SSOT is unchanged
        # Drift check must STILL pass bit-for-bit (Finding 1 fix)
        assert platform_manifest.sync(output_path=target_json, check=True, config_path=mock_yaml) == 0
        assert target_json.read_text(encoding="utf-8") == initial_content

        # 4. Modify SSOT file
        mock_yaml.write_text("k3s: {version: 'v1.35.0'}\napps: {}\n", encoding="utf-8")

        # 5. Drift check must now fail
        assert platform_manifest.sync(output_path=target_json, check=True, config_path=mock_yaml) == 1

        # 6. Re-sync updates the manifest and drift check passes again
        assert platform_manifest.sync(output_path=target_json, check=False, config_path=mock_yaml) == 0
        assert platform_manifest.sync(output_path=target_json, check=True, config_path=mock_yaml) == 0

    def test_compute_total_services_calculation(self) -> None:
        # Explicit override in config
        override_cfg = {"apps": {"platform": {"total_services": 42}}}
        assert platform_manifest.compute_total_services(override_cfg) == 42

        # Direct calculation from empty config: staging + prod + shared, no offset
        count = platform_manifest.compute_total_services({})
        assert count == 39

    def test_total_services_counts_every_table_and_nothing_else(self) -> None:
        # The manifest publishes the shared services (Gitea, Argo CD, Headscale...)
        # beside the total, so a total that drops them contradicts its own page, and
        # a constant added on top is a number nobody derived.
        from toolkit.scripts.sync_homepage_config import build_service_tables

        config = yaml.safe_load(platform_manifest.COMMON_YAML_PATH.read_text(encoding="utf-8"))
        stg, prd, shared = build_service_tables(config)
        assert platform_manifest.compute_total_services(config) == len(stg) + len(prd) + len(shared)

    def test_dynamic_public_service_from_ssot(self, tmp_path: Path) -> None:
        mock_yaml = tmp_path / "common.yaml"
        mock_yaml.write_text(
            """
apps:
  services:
    custom_cat:
      new_service:
        name: "New Public Tool"
        domain: "tool.kubelab.live"
        health_path: "/health"
        public: true
""",
            encoding="utf-8",
        )
        # Add custom service to catalog defaults for projection
        mutated_catalog = list(platform_manifest.SERVICE_CATALOG_DEFAULTS)
        mutated_catalog.append(
            {
                "slug": "new_service",
                "name": "New Public Tool Default",
                "category": "Core Gateway",
                "categoryEs": "Gateway Principal",
                "description": "Dynamic public tool",
                "descriptionEs": "Herramienta pública dinámica",
                "node": "vps",
                "env": "prod",
                "tech": ["Go"],
                "isPublic": False,  # defaults to private, but SSOT declares public: true
                "status": "operational",
            }
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(platform_manifest, "SERVICE_CATALOG_DEFAULTS", mutated_catalog)
            manifest = platform_manifest.generate_manifest(config_path=mock_yaml)
            new_svc = next(s for s in manifest["services"] if s["slug"] == "new_service")
            assert new_svc["isPublic"] is True
            assert new_svc["url"] == "https://tool.kubelab.live"
            assert new_svc["healthEndpoint"] == "https://tool.kubelab.live/health"

    def test_resolve_node_status_offline(self, tmp_path: Path) -> None:
        mock_yaml = tmp_path / "common.yaml"
        mock_yaml.write_text(
            """
networking:
  vps:
    location: "always-on"
    status: "offline"
clusters: {}
apps: {}
""",
            encoding="utf-8",
        )
        manifest = platform_manifest.generate_manifest(config_path=mock_yaml)
        vps = next(n for n in manifest["nodes"] if n["id"] == "vps")
        assert vps["status"] == "offline"
        # Offline node must not be counted in activeNodes
        assert manifest["cluster"]["activeNodes"] == 0

    def test_zero_addressing_guard_does_not_falsely_catch_mac_address(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mutated_services = list(platform_manifest.SERVICE_CATALOG_DEFAULTS)
        mutated_services.append(
            {
                "slug": "mac-node",
                "name": "MAC Node",
                "category": "Core Gateway",
                "categoryEs": "Gateway Principal",
                "description": "Hardware MAC interface 00:11:22:33:44:55",
                "descriptionEs": "Interfaz MAC",
                "node": "vps",
                "env": "prod",
                "tech": ["Linux"],
                "isPublic": False,
                "status": "operational",
            }
        )
        monkeypatch.setattr(platform_manifest, "SERVICE_CATALOG_DEFAULTS", mutated_services)
        # Must generate cleanly without raising IPv6 error
        manifest = platform_manifest.generate_manifest()
        mac_svc = next(s for s in manifest["services"] if s["slug"] == "mac-node")
        assert "00:11:22:33:44:55" in mac_svc["description"]

    def test_invalid_yaml_root_raises_value_error(self, tmp_path: Path) -> None:
        invalid_yaml = tmp_path / "invalid.yaml"
        invalid_yaml.write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid configuration format.*expected root mapping/dict"):
            platform_manifest.generate_manifest(config_path=invalid_yaml)

    def test_a_warning_node_stays_active(self) -> None:
        """`warning` is degraded, not down — it must still count toward activeNodes.

        The three non-default statuses fall through one chain, and only the two that
        deactivate a node had coverage. A `warning` that silently became `healthy`
        would be indistinguishable from a healthy node in the published manifest,
        which is the opposite of what declaring it is for.
        """
        status, active = platform_manifest._resolve_node_status({"status": "warning"})
        assert (status, active) == ("warning", True)

    def test_an_unreadable_existing_manifest_does_not_stop_generation(self, tmp_path: Path) -> None:
        """A corrupt target is regenerated, not raised on.

        `_get_provenance` reuses the previous `generated_at` when the source hash is
        unchanged, which is what keeps `--check` idempotent. Reading that file is a
        best-effort optimisation, so a truncated or non-JSON manifest has to fall
        through to a fresh timestamp — otherwise a corrupt artifact makes the drift
        gate unfixable by the very command that would repair it.
        """
        source = tmp_path / "common.yaml"
        source.write_text("project_name: kubelab\n", encoding="utf-8")
        target = tmp_path / "platform.json"
        target.write_text("{ this is not json", encoding="utf-8")

        generated_at, source_hash = platform_manifest._get_provenance(source, target)

        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", generated_at)
        assert source_hash == platform_manifest.compute_source_hash(source)

    def test_a_version_already_prefixed_is_not_prefixed_twice(self, tmp_path: Path) -> None:
        """`K3s K3s v1.34.4` is the bug this branch exists to prevent."""
        mock_yaml = tmp_path / "prefixed.yaml"
        mock_yaml.write_text('k3s:\n  version: "K3s v9.9.9"\n', encoding="utf-8")

        manifest = platform_manifest.generate_manifest(config_path=mock_yaml)

        assert manifest["cluster"]["version"] == "K3s v9.9.9"

    def test_traefik_is_taken_from_edge_when_no_service_block_declares_it(self, tmp_path: Path) -> None:
        """Traefik is declared under `edge`, not under `apps.services`, unlike everything else.

        The fallback exists because of that asymmetry, and an untested fallback is
        one nobody notices has stopped firing.
        """
        mock_yaml = tmp_path / "edge_only.yaml"
        mock_yaml.write_text(
            'edge:\n  traefik:\n    version: "v3.6.2"\n',
            encoding="utf-8",
        )

        blocks = platform_manifest._collect_ssot_services(
            {"edge": {"traefik": {"version": "v3.6.2"}}},
        )

        assert blocks["traefik"] == {"version": "v3.6.2"}

    def test_non_mapping_entries_in_the_services_tree_are_skipped_not_crashed_on(self) -> None:
        """`common.yaml` is hand-edited, so a category or service can be a string or null.

        Each level guards with `isinstance`, and only the happy path had coverage —
        so the guards were present and unproven, which is the shape this repo keeps
        finding. A commented-out service left as a bare key parses as `None`.
        """
        blocks = platform_manifest._collect_ssot_services(
            {
                "apps": {
                    "services": {
                        "core": {"gitea": {"version": "1.24"}, "broken": None},
                        "not_a_category": "just a string",
                    }
                }
            },
        )

        assert blocks["gitea"] == {"version": "1.24"}
        assert "broken" not in blocks
        assert "not_a_category" not in blocks

        # The outermost guard too: `apps.services` itself replaced by a scalar.
        assert platform_manifest._collect_ssot_services({"apps": {"services": "oops"}}) == {}

    def test_sync_catches_validation_error_and_returns_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verify sync() catches ValueError (e.g. Zero-Addressing violation) and returns 1 cleanly."""
        target_file = tmp_path / "platform.json"
        monkeypatch.setattr(
            platform_manifest,
            "generate_manifest",
            lambda **_: (_ for _ in ()).throw(ValueError("Zero-Addressing violation: IPv4 address detected")),
        )
        rc = platform_manifest.sync(output_path=target_file, check=False)
        assert rc == 1

    def test_sync_catches_missing_config_and_returns_failure(self, tmp_path: Path) -> None:
        """Verify sync() catches FileNotFoundError when source configuration does not exist and returns 1 cleanly."""
        target_file = tmp_path / "platform.json"
        missing_cfg = tmp_path / "does_not_exist.yaml"
        rc = platform_manifest.sync(output_path=target_file, check=False, config_path=missing_cfg)
        assert rc == 1
