"""SEC-004: the K3s `rate-limit` Middleware must not drift from its SSOT.

`infra/k8s/base/edge/rate-limit.yaml` is a static manifest (no generator
templates Middleware *values* in this codebase — `secure-headers.yaml` is the
existing precedent), so its numbers are only as trustworthy as this test makes
them. Reads the manifest file directly, mirroring
`tests/test_spoke_rbac_covers_manifests.py`'s no-kubectl, CI-friendly pattern.
"""

from __future__ import annotations

import pathlib

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "infra/k8s/base/edge/rate-limit.yaml"
COMMON_YAML = REPO_ROOT / "infra/config/values/common.yaml"


def _load_manifest() -> dict:
    docs = list(yaml.safe_load_all(MANIFEST.read_text(encoding="utf-8")))
    middlewares = [d for d in docs if d and d.get("kind") == "Middleware"]
    assert len(middlewares) == 1, (
        f"Expected exactly one Middleware doc in {MANIFEST}, found {len(middlewares)}"
    )
    return middlewares[0]


def _load_common_rate_limit() -> dict:
    config = yaml.safe_load(COMMON_YAML.read_text(encoding="utf-8"))
    edge = config["edge"]["traefik"]
    return {
        "average": edge["rate_limit_k3s_average"],
        "burst": edge["rate_limit_k3s_burst"],
        "period": edge["rate_limit_k3s_period"],
    }


class TestRateLimitMiddlewareMatchesSSOT:
    def test_manifest_exists_and_is_named_rate_limit(self) -> None:
        assert MANIFEST.exists(), f"Missing {MANIFEST}"
        doc = _load_manifest()
        assert doc["metadata"]["name"] == "rate-limit"
        assert doc["metadata"]["namespace"] == "kubelab"

    def test_values_match_common_yaml_no_hardcoded_duplicate(self) -> None:
        doc = _load_manifest()
        rate_limit = doc["spec"]["rateLimit"]
        expected = _load_common_rate_limit()
        assert rate_limit["average"] == expected["average"]
        assert rate_limit["burst"] == expected["burst"]
        assert rate_limit["period"] == expected["period"]

    def test_source_criterion_is_explicit_not_default(self) -> None:
        """Default client-IP keying would happen to look global only because
        klipper-lb masquerades every client to an internal pod-CIDR address
        (#1067) — that's global by accident, not by design. See proposal.md
        Risks: this must survive #1067 being fixed without silently changing
        the rate limit's behavior."""
        doc = _load_manifest()
        rate_limit = doc["spec"]["rateLimit"]
        assert "sourceCriterion" in rate_limit, (
            "sourceCriterion must be explicit — relying on Traefik's default "
            "client-IP keying is an accident of klipper-lb's masquerade bug, not "
            "a deliberate design"
        )
        assert "requestHost" in rate_limit["sourceCriterion"]

    def test_registered_in_base_kustomization(self) -> None:
        kustomization = REPO_ROOT / "infra/k8s/base/kustomization.yaml"
        content = kustomization.read_text(encoding="utf-8")
        assert "edge/rate-limit.yaml" in content, (
            "rate-limit.yaml must be registered in base/kustomization.yaml resources:"
        )
