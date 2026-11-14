"""RES-HOST-001 slice E: a product that claims `resources:` gets an ingress and an egress NetworkPolicy.

The pair selects the product's Deployment AND its CronJob pods by `app.kubernetes.io/name`, so
the job is as boxed in as the web pod. The egress profiles come from the product's registry
entry and never from its contract (D7), so a product cannot widen its own network. A product
that claims nothing renders neither policy: this is the cluster's first egress restriction and
it stays scoped to the product that asked for resources.

Each test renders the real templates from the context `_build_context` builds.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from tests.test_k8s_generator_contract_resources import _contract, _env, _objects, _one
from toolkit.features import generator_k8s, product_registry
from toolkit.features.generator_k8s import K8sGenerator
from toolkit.features.product_contract import ContractError, validate_contract

NAME = "app.kubernetes.io/name"
PRIVATE_RANGES = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16"]
TRAEFIK = {
    "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
    "podSelector": {"matchLabels": {NAME: "traefik"}},
}

REGISTRY = """\
products:
  api:
    forge: in-tree
  sample:
    repository: personal/sample
    forge: gitea
    receiver: generic
    egress: {egress}
"""


@pytest.fixture
def snapshots(tmp_path: Path) -> Path:
    root = tmp_path / "contracts"
    root.mkdir()
    (root / "sample.yaml").write_text(_contract(), encoding="utf-8", newline="\n")
    return root


@pytest.fixture
def build(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, snapshots: Path):
    """`_build_context("staging")` for `api` (no claims) and `sample` (a volume and a job)."""

    def run(egress: str = "[dns, public-https, notify]") -> dict[str, Any]:
        registry = tmp_path / "products.yaml"
        registry.write_text(REGISTRY.format(egress=egress), encoding="utf-8", newline="\n")
        monkeypatch.setattr(product_registry, "registry_path", lambda: registry)
        product_registry._load.cache_clear()
        monkeypatch.setattr(K8sGenerator, "snapshot_dir", snapshots)
        monkeypatch.setattr(K8sGenerator, "_build_migrations", lambda self, env_vars: {})
        monkeypatch.setattr(K8sGenerator, "_has_secret_vars", lambda self, component: False)
        manager = MagicMock()
        manager.return_value.get_env_vars.return_value = {
            "REGISTRY": "docker.io/mlorentedev",
            **_env("api"),
            **_env("sample"),
        }
        monkeypatch.setattr(generator_k8s, "ConfigurationManager", manager)
        return K8sGenerator()._build_context("staging")

    yield run
    product_registry._load.cache_clear()


def _policies(objects: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {o["metadata"]["name"]: o for o in objects if o["kind"] == "NetworkPolicy"}


def _selects(selector: dict[str, Any], labels: dict[str, str]) -> bool:
    """Kubernetes semantics for a `matchLabels` selector; an empty one selects every pod."""
    return all(labels.get(k) == v for k, v in selector.get("matchLabels", {}).items())


class TestIngress:
    def test_admits_traefik_on_the_container_port_and_no_one_else(self, build, tmp_path: Path) -> None:
        policy = _one(_objects(build(), tmp_path), "NetworkPolicy", "sample-ingress")

        assert policy["metadata"]["namespace"] == "kubelab"
        assert policy["metadata"]["labels"][NAME] == "sample"
        assert policy["spec"]["policyTypes"] == ["Ingress"]
        assert policy["spec"]["ingress"] == [{"from": [TRAEFIK], "ports": [{"protocol": "TCP", "port": 8080}]}]


class TestEgress:
    def _egress(self, build, tmp_path: Path, profiles: str = "[dns, public-https, notify]") -> dict[str, Any]:
        return _one(_objects(build(profiles), tmp_path), "NetworkPolicy", "sample-egress")

    def test_is_an_egress_only_policy_labelled_for_the_product(self, build, tmp_path: Path) -> None:
        policy = self._egress(build, tmp_path)

        assert policy["metadata"]["namespace"] == "kubelab"
        assert policy["metadata"]["labels"][NAME] == "sample"
        assert policy["spec"]["policyTypes"] == ["Egress"]

    def test_dns_is_kube_dns_on_53_over_udp_and_tcp(self, build, tmp_path: Path) -> None:
        (rule,) = self._egress(build, tmp_path, "[dns]")["spec"]["egress"]

        assert rule["to"] == [
            {
                "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
                "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
            }
        ]
        assert rule["ports"] == [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]

    def test_public_https_is_443_to_anywhere_but_the_private_tailnet_and_metadata_ranges(
        self, build, tmp_path: Path
    ) -> None:
        (rule,) = self._egress(build, tmp_path, "[public-https]")["spec"]["egress"]

        assert rule["to"] == [{"ipBlock": {"cidr": "0.0.0.0/0", "except": PRIVATE_RANGES}}]
        assert rule["ports"] == [{"protocol": "TCP", "port": 443}]

    def test_notify_is_the_n8n_pods_on_5678(self, build, tmp_path: Path) -> None:
        (rule,) = self._egress(build, tmp_path, "[notify]")["spec"]["egress"]

        assert rule["to"] == [{"podSelector": {"matchLabels": {NAME: "n8n"}}}]
        assert rule["ports"] == [{"protocol": "TCP", "port": 5678}]

    def test_the_profiles_the_entry_names_are_the_only_rules(self, build, tmp_path: Path) -> None:
        rules = self._egress(build, tmp_path, "[dns, notify]")["spec"]["egress"]

        assert [r["ports"][0]["port"] for r in rules] == [53, 5678]

    def test_an_entry_with_no_profile_denies_all_egress(self, build, tmp_path: Path) -> None:
        """Selected by an Egress policy with no rule: nothing leaves, DNS included."""
        spec = self._egress(build, tmp_path, "[]")["spec"]

        assert spec["policyTypes"] == ["Egress"]
        assert not spec.get("egress")


class TestSelection:
    def test_both_policies_select_the_deployment_and_the_cronjob_pods(self, build, tmp_path: Path) -> None:
        objects = _objects(build(), tmp_path)
        deployment = _one(objects, "Deployment", "sample")["spec"]["template"]["metadata"]["labels"]
        cronjob = _one(objects, "CronJob", "sample-daily")["spec"]["jobTemplate"]["spec"]["template"]["metadata"][
            "labels"
        ]

        for name in ("sample-ingress", "sample-egress"):
            selector = _one(objects, "NetworkPolicy", name)["spec"]["podSelector"]
            assert _selects(selector, deployment), f"{name} misses the Deployment pods"
            assert _selects(selector, cronjob), f"{name} misses the CronJob pods"

    def test_neither_policy_selects_another_app(self, build, tmp_path: Path) -> None:
        objects = _objects(build(), tmp_path)
        api = _one(objects, "Deployment", "api")["spec"]["template"]["metadata"]["labels"]

        for name in ("sample-ingress", "sample-egress"):
            assert not _selects(_one(objects, "NetworkPolicy", name)["spec"]["podSelector"], api)


class TestProductWithoutResources:
    def test_gets_neither_policy(self, build, tmp_path: Path) -> None:
        policies = _policies(_objects(build(), tmp_path))

        assert not [n for n in policies if n.startswith("api-")], sorted(policies)

    def test_a_product_whose_snapshot_claims_nothing_gets_neither_policy(
        self, build, snapshots: Path, tmp_path: Path
    ) -> None:
        head = _contract().split("resources:")[0]
        (snapshots / "sample.yaml").write_text(head, encoding="utf-8", newline="\n")

        policies = _policies(_objects(build(), tmp_path))

        assert not [n for n in policies if n.startswith("sample-")], sorted(policies)


def test_a_contract_cannot_name_egress(tmp_path: Path) -> None:
    """The contract is the product's own word; egress is the operator's, so the closed model refuses it."""
    path = tmp_path / "kubelab.yaml"
    path.write_text(_contract() + "egress: [public-https]\n", encoding="utf-8", newline="\n")

    with pytest.raises(ContractError, match="egress"):
        validate_contract(path)
