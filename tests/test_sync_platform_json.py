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
                assert (
                    service.get("url") is None
                ), f"Private service {service['slug']} leaked URL: {service.get('url')}"
                assert (
                    service.get("healthEndpoint") is None
                ), f"Private service {service['slug']} leaked healthEndpoint"
            else:
                assert (
                    service.get("url") is not None
                ), f"Public service {service['slug']} missing public URL"

    def test_provenance_determinism(self) -> None:
        manifest = platform_manifest.generate_manifest()
        assert re.match(
            r"^[a-f0-9]{40}$", manifest["source_commit"]
        ), f"Invalid commit sha: {manifest['source_commit']}"
        assert re.match(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", manifest["generated_at"]
        ), f"Invalid ISO 8601 date: {manifest['generated_at']}"


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

    def test_git_failure_falls_back_gracefully(self, monkeypatch, tmp_path: Path) -> None:
        fake_cfg = tmp_path / "common.yaml"
        fake_cfg.write_text("k3s: {version: 'v1.34.4'}\n", encoding="utf-8")

        def mock_check_output(*args: Any, **kwargs: Any) -> str:
            raise RuntimeError("git failed")

        monkeypatch.setattr("subprocess.check_output", mock_check_output)
        ts, sha = platform_manifest._get_commit_provenance(fake_cfg)
        assert sha == "0000000000000000000000000000000000000000"
        assert re.match(r"^\d{4}-\d{2}-\d{2}T", ts)

    def test_zero_addressing_guard_catches_leaked_ip(self, monkeypatch) -> None:
        mutated_services = list(platform_manifest.PLATFORM_SERVICES)
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
        monkeypatch.setattr(platform_manifest, "PLATFORM_SERVICES", mutated_services)
        with pytest.raises(ValueError, match="Zero-Addressing violation: IP address detected"):
            platform_manifest.generate_manifest()

    def test_zero_addressing_guard_catches_internal_hostname(self, monkeypatch) -> None:
        mutated_services = list(platform_manifest.PLATFORM_SERVICES)
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
        monkeypatch.setattr(platform_manifest, "PLATFORM_SERVICES", mutated_services)
        with pytest.raises(ValueError, match="Zero-Addressing violation: internal hostname detected"):
            platform_manifest.generate_manifest()

        # Also test .local
        mutated_services[-1]["description"] = "Host edge.cluster.local"
        with pytest.raises(ValueError, match="Zero-Addressing violation: internal hostname detected"):
            platform_manifest.generate_manifest()

    def test_drift_gate_missing_file_returns_error(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist.json"
        rc = platform_manifest.sync(output_path=missing, check=True)
        assert rc == 1
