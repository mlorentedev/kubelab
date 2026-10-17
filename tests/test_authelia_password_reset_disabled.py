"""#1593: Authelia's self-service password reset is off in both environments.

The flow served nobody: every identity is an operator or machine account whose hash
lives in SOPS, and the documented reset path is `toolkit credentials hash-password`
plus `make apply-secrets`. Left on (Authelia's default), it was an unauthenticated
mail-send primitive on the public `auth.kubelab.live`, aimed at usernames that are
declared in plaintext in this public repository.

The check reads the EMITTED ConfigMap from `kubectl kustomize`, never the source file
(#1593 AC2): prod's `authelia-config` uses `behavior: replace`, so prod inherits
nothing from the base file, and only the rendered object says what each pod reads.

The live half is `tests/infra/test_authelia_password_reset_closed_live.py`.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OVERLAYS = ("staging", "prod")


def _emitted_configuration(overlay: str) -> dict:
    if shutil.which("kubectl") is None:
        pytest.skip(f"kubectl not on PATH: the {overlay} Authelia config was NOT checked")
    out = subprocess.run(
        ["kubectl", "kustomize", str(PROJECT_ROOT / "infra/k8s/overlays" / overlay)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    maps = [
        d
        for d in yaml.safe_load_all(out)
        if d and d.get("kind") == "ConfigMap" and d["metadata"]["name"].startswith("authelia-config")
    ]
    assert len(maps) == 1, f"expected one authelia-config ConfigMap in {overlay}, found {len(maps)}"
    return yaml.safe_load(maps[0]["data"]["configuration.yml"])


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_password_reset_is_disabled_in_the_emitted_config(overlay: str) -> None:
    backend = _emitted_configuration(overlay)["authentication_backend"]
    reset = backend.get("password_reset") or {}
    assert reset.get("disable") is True, (
        f"{overlay}: authentication_backend.password_reset.disable is {reset.get('disable')!r}. "
        "Authelia's default is false, so an absent key leaves the reset flow open on the portal."
    )
