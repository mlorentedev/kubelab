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

#: Grafana's env moved out of the manifest and into a `configMapGenerator`
#: source on #1446, so that editing a value rolls the pod instead of updating a
#: ConfigMap nothing re-reads. The assertion below follows the value; what it
#: guards is unchanged.
GRAFANA_ENV = REPO_ROOT / "infra/k8s/base/services/grafana-config/grafana.env"


def _load_docs() -> list[dict]:
    with open(GRAFANA_MANIFEST) as f:
        return [d for d in yaml.safe_load_all(f) if d]


def _load_env() -> dict[str, str]:
    """Parse the generator's env file the way kustomize does: `KEY=value`, rest
    of the line verbatim, `#` lines and blanks skipped."""
    env: dict[str, str] = {}
    for line in GRAFANA_ENV.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        env[key.strip()] = value
    return env


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
        assert _load_env()["GF_AUTH_PROXY_AUTO_SIGN_UP"] == "false"

    def test_grafana_config_is_generated_so_a_change_rolls_the_pod(self) -> None:
        """A plain ConfigMap here is a silent no-op, not a visible failure.

        Env vars are injected once at container start and Grafana re-reads
        none of them, so an unhashed `grafana-config` would change, Argo CD
        would report Synced/Healthy, and the running pod would keep the old
        value indefinitely. Guards both halves of the arrangement: the
        manifest must NOT declare the object, and the generator must not
        disable the name-suffix hash that makes an edit roll the Deployment.
        """
        names = [d.get("metadata", {}).get("name") for d in _load_docs() if d.get("kind") == "ConfigMap"]
        assert "grafana-config" not in names, "declaring it here bypasses the generator, and the hash with it"

        kustomization = yaml.safe_load((REPO_ROOT / "infra/k8s/base/kustomization.yaml").read_text())
        (generator,) = [g for g in kustomization["configMapGenerator"] if g["name"] == "grafana-config"]
        assert generator["envs"] == ["services/grafana-config/grafana.env"]
        assert not generator.get("options", {}).get("disableNameSuffixHash", False)
