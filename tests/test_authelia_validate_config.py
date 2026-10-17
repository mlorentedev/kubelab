"""AUTH-015 (#2059): Authelia's own schema judges the rendered config before Argo CD syncs it.

`tests/test_oidc_clients.py` compares the committed files with the SSOT, but nothing
asked Authelia whether it would START with them. A malformed `configuration.yml` or
generated `oidc-clients.yml` therefore surfaced as a crash-looping pod after Argo CD
had synced it to prod (`selfHeal: true`), which takes SSO down for every dependent app.

This runs the image the Deployment pins (read from the rendered overlay, so it cannot
drift from what ships) through `authelia validate-config`, with the files the cluster
mounts and dummy secret files for every `_FILE` variable the Deployment declares.

The negative control proves the gate discriminates: one client whose redirect URI is not
a URI must make the same invocation fail. Without it a green run could mean a validator
that accepts anything (measured 2026-10-03: it does reject this, #2058).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

REPO = Path(__file__).resolve().parent.parent
OVERLAYS = ("staging", "prod")


def _render(overlay: str) -> list[dict[str, Any]]:
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not on PATH: cannot render the overlay (a skip is CANNOT CHECK, not OK)")
    out = subprocess.run(
        ["kubectl", "kustomize", str(REPO / "infra/k8s/overlays" / overlay)], capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    return [d for d in yaml.safe_load_all(out.stdout) if d]


def _authelia(docs: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, Any]]:
    """The mounted config files and the Authelia container, as the overlay emits them."""
    config = next(d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"].startswith("authelia-config"))
    deployment = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "authelia")
    container = next(c for c in deployment["spec"]["template"]["spec"]["containers"] if c["name"] == "authelia")
    return config["data"], container


def _require_docker() -> None:
    if shutil.which("docker") is None:
        # The only proof Authelia would start: in CI a missing docker is a failure,
        # or a runner-image change would turn this gate into a quiet skip.
        if os.environ.get("CI"):
            pytest.fail("docker not on PATH in CI: the Authelia config went unvalidated")
        pytest.skip("docker not on PATH: cannot run Authelia (a skip is CANNOT CHECK, not OK)")


def _dummy_secrets(secrets_dir: Path, container: dict[str, Any]) -> list[str]:
    """One file per `_FILE` variable the Deployment declares; returns the `-e` flags.

    The values are throwaway. The OIDC issuer key has to be a real RSA key, because
    Authelia parses it; everything else is only required to exist.
    """
    flags: list[str] = []
    for env in container["env"]:
        name, value = env["name"], env.get("value", "")
        if name == "X_AUTHELIA_CONFIG":
            flags += ["-e", f"{name}={value}"]
        elif name.endswith("_FILE"):
            target = secrets_dir / Path(value).name
            if name.endswith("ISSUER_PRIVATE_KEY_FILE"):
                key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
                target.write_bytes(
                    key.private_bytes(
                        serialization.Encoding.PEM,
                        serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption(),
                    )
                )
            else:
                target.write_text(f"dummy-{target.name}-" + "x" * 40, encoding="utf-8")
            flags += ["-e", f"{name}={value}"]
    return flags


def _validate(root: Path, config: dict[str, str], container: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    config_dir = root / "config"
    secrets_dir = root / "secrets"
    # The two directories the Deployment mounts from a ConfigMap and a Secret must exist
    # for Authelia to accept `server.asset_path` and the file user backend.
    for sub in ("assets", "users"):
        (config_dir / sub).mkdir(parents=True, exist_ok=True)
    secrets_dir.mkdir(parents=True, exist_ok=True)
    for filename, text in config.items():
        (config_dir / filename).write_text(text, encoding="utf-8")
    flags = _dummy_secrets(secrets_dir, container)
    return subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            *flags,
            "-v",
            f"{config_dir}:/config:ro",
            "-v",
            f"{secrets_dir}:/run/secrets:ro",
            container["image"],
            "authelia",
            "validate-config",
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )


def _break_one_client(files: dict[str, str]) -> dict[str, str]:
    """The negative control: the first client's redirect URI stops being a URI."""
    broken = dict(files)
    document = yaml.safe_load(broken["oidc-clients.yml"])
    client = document["identity_providers"]["oidc"]["clients"][0]
    client["redirect_uris"] = ["not a uri"]
    broken["oidc-clients.yml"] = yaml.safe_dump(document)
    return broken


@pytest.mark.integration
@pytest.mark.parametrize("overlay", OVERLAYS)
def test_authelia_accepts_the_rendered_config(overlay: str, docker_mount_dir: Path) -> None:
    _require_docker()
    files, container = _authelia(_render(overlay))
    done = _validate(docker_mount_dir, files, container)
    assert done.returncode == 0, f"authelia validate-config rejected the {overlay} overlay:\n{done.stdout}{done.stderr}"


@pytest.mark.integration
@pytest.mark.parametrize("overlay", OVERLAYS)
def test_authelia_rejects_a_broken_client(overlay: str, docker_mount_dir: Path) -> None:
    """Without this a green run proves nothing: it could be a validator that accepts anything."""
    _require_docker()
    files, container = _authelia(_render(overlay))
    done = _validate(docker_mount_dir, _break_one_client(files), container)
    assert done.returncode != 0, f"the {overlay} negative control passed validation:\n{done.stdout}{done.stderr}"
    assert "redirect" in (done.stdout + done.stderr).lower(), "it failed, but not on the client we broke"


def test_the_validated_image_is_the_pinned_one() -> None:
    """The image comes from the rendered Deployment, so the SSOT pin is what gets validated."""
    pin = next(
        i
        for i in yaml.safe_load((REPO / "infra/k8s/base/kustomization.yaml").read_text())["images"]
        if i["name"] == "authelia/authelia"
    )
    for overlay in OVERLAYS:
        _, container = _authelia(_render(overlay))
        assert container["image"] == f"authelia/authelia:{pin['newTag']}"


# #2377: validate-config exits 0 on a deprecated key and only warns, so nothing noticed them
# until a release dropped one. Each remaining key names the ticket that removes it.
DEPRECATED_KEY = re.compile(r"configuration key '([^']+)' is deprecated")
TOLERATED_DEPRECATIONS = {
    # `_FILE` env vars cannot fill an array element, so moving to `jwks` needs a file path
    # for the key first (lesson-096). #2377 part 2.
    "identity_providers.oidc.issuer_private_key",
}


@pytest.mark.integration
@pytest.mark.parametrize("overlay", OVERLAYS)
def test_the_rendered_config_uses_no_new_deprecated_key(overlay: str, docker_mount_dir: Path) -> None:
    _require_docker()
    files, container = _authelia(_render(overlay))
    done = _validate(docker_mount_dir, files, container)
    text = done.stdout + done.stderr
    parsed = DEPRECATED_KEY.findall(text)
    # Guard the guard: a pattern that matches nothing would pass every config. Every
    # line that mentions a deprecation must be one it parsed, and a key the config
    # still uses must be seen.
    assert text.lower().count("deprecat") == len(parsed), f"unparsed deprecation output:\n{text}"
    if "issuer_private_key" in files["configuration.yml"]:
        assert "identity_providers.oidc.issuer_private_key" in parsed, f"pattern missed a live warning:\n{text}"
    deprecated = set(parsed)
    assert deprecated <= TOLERATED_DEPRECATIONS, f"{overlay} uses deprecated keys: {sorted(deprecated - TOLERATED_DEPRECATIONS)}"


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_passkeys_keep_preferred_user_verification(overlay: str) -> None:
    """The #2377 rename moved the setting; it must not change what passkeys ask for."""
    files, _ = _authelia(_render(overlay))
    webauthn = yaml.safe_load(files["configuration.yml"])["webauthn"]
    assert "user_verification" not in webauthn
    assert webauthn["selection_criteria"]["user_verification"] == "preferred"
