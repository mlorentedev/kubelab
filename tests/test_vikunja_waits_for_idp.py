"""OPS-032 AC3 (#1783): Vikunja discovers its IdP once, at start, and keeps the failure.

Measured three times: staging 2026-09-22 and 2026-09-26 (DNS), prod 2026-09-29
(Traefik and Authelia still starting: `connection refused`, then `403`). Each
time Vikunja gave up after 3 attempts and served `openid_connect.providers: []`
until someone restarted it, so the login page offered only the local form.

The image has no shell, so no probe can read `/api/v1/info`'s body. The pod
instead waits, before Vikunja starts, until the discovery document is served,
from the same ConfigMap key Vikunja reads. A pod waiting there is visibly not
ready, rather than ready and without SSO.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
AUTHURL = "VIKUNJA_AUTH_OPENID_PROVIDERS_AUTHELIA_AUTHURL"


def _render(overlay: str) -> list[dict]:
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not on PATH: cannot render the overlay (a skip is CANNOT CHECK, not OK)")
    out = subprocess.run(
        ["kubectl", "kustomize", str(REPO / "infra/k8s/overlays" / overlay)], capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    return [doc for doc in yaml.safe_load_all(out.stdout) if doc]


def _vikunja_pod(docs: list[dict]) -> dict:
    for doc in docs:
        if doc.get("kind") == "Deployment" and doc["metadata"]["name"] == "vikunja":
            return doc["spec"]["template"]["spec"]
    raise AssertionError("no vikunja Deployment in the render")


def _config_refs(container: dict) -> set[str]:
    return {e["configMapRef"]["name"] for e in container.get("envFrom", []) if "configMapRef" in e}


@pytest.mark.parametrize("overlay", ["staging", "prod"])
def test_vikunja_starts_only_after_its_idp_answers(overlay: str) -> None:
    docs = _render(overlay)
    pod = _vikunja_pod(docs)
    waits = [c for c in pod.get("initContainers", []) if c["name"] == "wait-for-idp"]
    assert waits, "no init container waits for the IdP's discovery document"
    script = " ".join(waits[0]["command"])
    # Parsed, not just read: a `>-` turned into `|` keeps every substring below
    # and leaves `| grep` at the start of a line, which sh rejects.
    command = waits[0]["command"]
    assert command[:2] == ["sh", "-c"], command
    parsed = subprocess.run(["sh", "-n", "-c", command[2]], capture_output=True, text=True)
    assert parsed.returncode == 0, parsed.stderr
    assert f"${{{AUTHURL}}}/.well-known/openid-configuration" in script
    # Authelia answers 200 on any path, so only the document's content proves
    # discovery works.
    assert '"authorization_endpoint"' in script
    # The busybox image's own TLS cannot complete a handshake with prod Traefik
    # (alert 47). Alpine's busybox wget hands TLS to `ssl_client` (OpenSSL 3).
    assert not waits[0]["image"].startswith("busybox")
    # Pinned to the image the wait was measured with: the one prod Postgres runs,
    # so the cluster already holds it. Any other image (no wget, no ssl_client)
    # could wait forever on a healthy IdP while every assertion above passes.
    [postgres] = [
        d["spec"]["template"]["spec"]["containers"][0]["image"]
        for d in docs
        if d.get("kind") == "Deployment" and d["metadata"]["name"] == "postgres"
    ]
    assert waits[0]["image"] == postgres, (waits[0]["image"], postgres)
    # The URL comes from Vikunja's own ConfigMap, so the wait and the app can
    # never check two different IdPs. An `env:` entry wins over `envFrom`, so
    # neither container may set the key directly.
    [app] = [c for c in pod["containers"] if c["name"] == "vikunja"]
    refs = _config_refs(waits[0])
    assert refs and refs == _config_refs(app)
    for container in (waits[0], app):
        assert AUTHURL not in {e["name"] for e in container.get("env", [])}, container["name"]
    # And the key is there: an empty URL would leave the pod in Init forever,
    # which is worse than the failure this wait replaces.
    configmaps = {d["metadata"]["name"]: d.get("data", {}) for d in docs if d.get("kind") == "ConfigMap"}
    urls = [configmaps[r].get(AUTHURL, "") for r in refs]
    assert any(u.startswith("https://") for u in urls), f"{AUTHURL} is missing or not https in {sorted(refs)}"


def _generator_env_files() -> list[Path]:
    files = []
    for kust in (REPO / "infra/k8s").rglob("kustomization.yaml"):
        doc = yaml.safe_load(kust.read_text()) or {}
        for gen in doc.get("configMapGenerator", []):
            # `env:` (singular) is still accepted by kustomize.
            files += [kust.parent / f for f in [*gen.get("envs", []), *([gen["env"]] if gen.get("env") else [])]]
    return files


def test_generator_env_values_carry_no_literal_quotes() -> None:
    """Kustomize keeps quotes in an env file as part of the value, unlike a shell.

    `NAME="KubeLab IDP"` put the quotes on Vikunja's login button.
    """
    files = _generator_env_files()
    # Pinned to the file the bug shipped in, so a walk that misses it fails here.
    assert REPO / "infra/k8s/base/services/vikunja-config/vikunja.env" in files, "the walk misses vikunja.env"
    quoted = []
    for path in files:
        for n, line in enumerate(path.read_text().splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            value = line.partition("=")[2]
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                quoted.append(f"{path.relative_to(REPO)}:{n}")
    assert not quoted, quoted
