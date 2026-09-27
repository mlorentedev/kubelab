"""TOOL-080 PR 4, AC1/AC3/AC6: the rendered prod Deployment, Service and IngressRoute.

Rendered rather than read from `infra/k8s/overlays/prod/pr-agent.yaml` directly,
for the reason `test_vikunja_registration_render.py` gives at length: a
Kustomize transform (here, the `pragent/pr-agent` `images:` override) that stops
applying is invisible to a file-reading check.

The `secretKeyRef` assertion is cross-checked against `SECRET_DEFINITIONS`
itself (`toolkit/features/k8s_secrets.py`), not against a second, independently
maintained list of three strings -- the exact gap the Vikunja R2 comment names
("nothing cross-checked the two", `k8s_secrets.py:163`).
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest
import yaml

from toolkit.features.k8s_secrets import SECRET_DEFINITIONS

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
PR_AGENT_MAPPING = next(m for m in SECRET_DEFINITIONS if m.name == "pr-agent-secrets")


def _kustomize(path: str) -> list[dict]:
    if shutil.which("kubectl") is None:
        pytest.skip(
            "CANNOT CHECK: kubectl is not installed, so the rendered output cannot be "
            "produced. This is not a pass -- TOOL-080 AC1 is unverified here."
        )
    result = subprocess.run(
        ["kubectl", "kustomize", str(REPO_ROOT / path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(f"kubectl kustomize {path} failed:\n{result.stderr}")
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _prod_docs() -> list[dict]:
    return _kustomize("infra/k8s/overlays/prod")


def _one(docs: list[dict], kind: str, name: str) -> dict:
    matches = [d for d in docs if d.get("kind") == kind and d.get("metadata", {}).get("name") == name]
    assert len(matches) == 1, f"expected exactly one {kind}/{name} in the prod render, found {len(matches)}"
    return matches[0]


def _container(deployment: dict, name: str) -> dict:
    containers = deployment["spec"]["template"]["spec"]["containers"]
    matches = [c for c in containers if c.get("name") == name]
    assert len(matches) == 1, f"expected exactly one container named {name!r}, found {len(matches)}"
    return matches[0]


class TestDeployment:
    def test_image_matches_common_yaml(self) -> None:
        common = yaml.safe_load((REPO_ROOT / "infra/config/values/common.yaml").read_text())
        expected = common["apps"]["services"]["automation"]["pr_agent"]["image"]

        container = _container(_one(_prod_docs(), "Deployment", "pr-agent"), "pr-agent")

        assert container["image"] == expected, (
            f"rendered image {container['image']!r} does not match common.yaml's "
            f"{expected!r} -- the images: override (sync-k8s-images) is not reaching "
            "this manifest."
        )

    def test_no_secret_key_ref_is_optional(self) -> None:
        """AC3/AC6: every one of the three keys must be present or the pod refuses

        to start -- an `optional: true` here would let it come up half-configured
        and answer webhooks it cannot verify or review anything with.
        """
        container = _container(_one(_prod_docs(), "Deployment", "pr-agent"), "pr-agent")
        secret_env = [e for e in container.get("env", []) if "secretKeyRef" in (e.get("valueFrom") or {})]
        assert secret_env, "the container declares no secretKeyRef env vars at all"
        for entry in secret_env:
            ref = entry["valueFrom"]["secretKeyRef"]
            assert "optional" not in ref, f"{entry['name']} carries optional: {ref.get('optional')}"

    def test_secret_env_matches_the_pr_agent_secrets_mapping(self) -> None:
        """The manifest's three env vars are exactly `pr-agent-secrets`'s keys --

        not a second, hand-maintained list free to drift from it.
        """
        container = _container(_one(_prod_docs(), "Deployment", "pr-agent"), "pr-agent")
        rendered = {
            e["name"]: e["valueFrom"]["secretKeyRef"]
            for e in container.get("env", [])
            if "secretKeyRef" in (e.get("valueFrom") or {})
        }
        assert set(rendered) == set(PR_AGENT_MAPPING.keys)
        for env_name, ref in rendered.items():
            assert ref["name"] == "pr-agent-secrets"
            assert ref["key"] == env_name

    def test_readiness_and_liveness_are_tcp_not_http(self) -> None:
        """`GET /` returns 404 (measured, verification.md) -- an HTTP probe on it

        would CrashLoop a healthy pod.
        """
        container = _container(_one(_prod_docs(), "Deployment", "pr-agent"), "pr-agent")
        for probe_name in ("readinessProbe", "livenessProbe"):
            probe = container.get(probe_name)
            assert probe, f"{probe_name} is not declared"
            assert "httpGet" not in probe, f"{probe_name} uses httpGet, but GET / returns 404"
            assert "tcpSocket" in probe, f"{probe_name} must be a tcpSocket probe"

    def test_hardened_security_context(self) -> None:
        """Measured 2026-09-27 (verification.md): non-root + read-only rootfs

        works ONLY with HOME=/tmp -- without it, importing azure.devops crashes
        on uid 65534's unwritable $HOME.
        """
        deployment = _one(_prod_docs(), "Deployment", "pr-agent")
        pod_spec = deployment["spec"]["template"]["spec"]
        container = _container(deployment, "pr-agent")

        assert pod_spec.get("enableServiceLinks") is False
        pod_sc = pod_spec.get("securityContext") or {}
        container_sc = container.get("securityContext") or {}

        assert pod_sc.get("runAsNonRoot") is True or container_sc.get("runAsNonRoot") is True
        assert container_sc.get("readOnlyRootFilesystem") is True
        assert container_sc.get("allowPrivilegeEscalation") is False
        assert list(container_sc.get("capabilities", {}).get("drop", [])) == ["ALL"]

        env = {e["name"]: e.get("value") for e in container.get("env", []) if "value" in e}
        assert env.get("HOME") == "/tmp", "azure.devops import crashes on uid 65534's default $HOME"

        mounts = {m["mountPath"]: m["name"] for m in container.get("volumeMounts", [])}
        assert "/tmp" in mounts, "readOnlyRootFilesystem with no writable /tmp crashes the same import"
        volumes = {v["name"]: v for v in pod_spec.get("volumes", [])}
        assert "emptyDir" in volumes[mounts["/tmp"]]


class TestService:
    def test_service_targets_port_3000(self) -> None:
        service = _one(_prod_docs(), "Service", "pr-agent")
        ports = service["spec"]["ports"]
        assert any(p.get("port") == 3000 for p in ports)
        assert service["spec"]["type"] == "ClusterIP"


class TestIngressRoute:
    def test_route_matches_host_and_webhook_path_only(self) -> None:
        route = _one(_prod_docs(), "IngressRoute", "pr-agent")
        rules = route["spec"]["routes"]
        assert len(rules) == 1
        assert rules[0]["match"] == "Host(`pr-agent.kubelab.live`) && Path(`/api/v1/gitea_webhooks`)"

    def test_middlewares_are_exactly_the_declared_three_no_authelia(self) -> None:
        """No authelia (proposal, component 6): the HMAC signature is the auth,

        as with n8n's `/webhook/` route.
        """
        route = _one(_prod_docs(), "IngressRoute", "pr-agent")
        names = [m["name"] for m in route["spec"]["routes"][0]["middlewares"]]
        assert names == ["secure-headers", "rate-limit", "crowdsec-bouncer"]

    def test_tls_uses_letsencrypt(self) -> None:
        route = _one(_prod_docs(), "IngressRoute", "pr-agent")
        assert route["spec"]["tls"]["certResolver"] == "letsencrypt"
