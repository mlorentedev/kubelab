"""SEC-014: Grafana's auth-proxy header must only be reachable from Traefik.

Static, not live: a live probe (curl from a throwaway pod, from port-forward)
was run by hand against staging when this shipped — see the PR. This guards
the manifest itself, so a future edit that loosens the selector or drops the
policy fails fast, without a cluster.
"""

from __future__ import annotations

import pathlib

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
GRAFANA_MANIFEST = REPO_ROOT / "infra/k8s/base/services/grafana.yaml"


def _load_docs() -> list[dict]:
    with open(GRAFANA_MANIFEST) as f:
        return [d for d in yaml.safe_load_all(f) if d]


def _find(docs: list[dict], kind: str, name: str) -> dict:
    for d in docs:
        if d.get("kind") == kind and d.get("metadata", {}).get("name") == name:
            return d
    raise AssertionError(f"{kind}/{name} not found in {GRAFANA_MANIFEST}")


class TestAuthProxyHeaderIsGatedByNetworkPolicy:
    def test_the_policy_selects_the_grafana_pod(self) -> None:
        policy = _find(_load_docs(), "NetworkPolicy", "grafana-ingress-from-traefik-only")
        assert policy["spec"]["podSelector"]["matchLabels"] == {"app.kubernetes.io/name": "grafana"}
        assert policy["spec"]["policyTypes"] == ["Ingress"]

    def test_the_only_allowed_source_is_traefik_in_kube_system(self) -> None:
        policy = _find(_load_docs(), "NetworkPolicy", "grafana-ingress-from-traefik-only")
        rules = policy["spec"]["ingress"]
        assert len(rules) == 1, "a second rule widens who may present Remote-User"
        (source,) = rules[0]["from"]
        assert source["namespaceSelector"]["matchLabels"] == {"kubernetes.io/metadata.name": "kube-system"}
        assert source["podSelector"]["matchLabels"] == {"app.kubernetes.io/name": "traefik"}

    def test_auto_sign_up_is_off(self) -> None:
        """Auto-provisioning an account for whatever username arrives compounds
        an unrestricted proxy header into an unrestricted *account creator*."""
        config = _find(_load_docs(), "ConfigMap", "grafana-config")
        assert config["data"]["GF_AUTH_PROXY_AUTO_SIGN_UP"] == "false"
