"""#2377 part 2: Authelia reads the OIDC signing key through `jwks`, not `issuer_private_key`.

`issuer_private_key` is deprecated since 4.38. It was kept because a `_FILE` env var
cannot fill an array element (lesson-096). Authelia's template filter can: the key is
read from the mounted Secret by `{{ secret "<path>" }}` in a file of its own, so the
line that is not YAML until Authelia renders it stays out of `configuration.yml`, which
a dozen tests load as YAML.

`test_authelia_validate_config.py` proves Authelia starts with what this renders. These
tests pin what it cannot see: the kid clients cached, the file reaching prod, and the
path matching a key the Secret actually carries.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
OVERLAYS = ("staging", "prod")
JWKS_FILE = "oidc-jwks.yml"
SECRET_REF = re.compile(r'\{\{\s*secret\s+"([^"]+)"')


def _authelia(overlay: str) -> tuple[dict[str, str], dict[str, str]]:
    """The authelia-config data and the container's env, as the overlay emits them."""
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not on PATH: cannot render the overlay (a skip is CANNOT CHECK, not OK)")
    out = subprocess.run(
        ["kubectl", "kustomize", str(REPO / "infra/k8s/overlays" / overlay)], capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    docs: list[dict[str, Any]] = [d for d in yaml.safe_load_all(out.stdout) if d]
    config = next(d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"].startswith("authelia-config"))
    deployment = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "authelia")
    container = next(c for c in deployment["spec"]["template"]["spec"]["containers"] if c["name"] == "authelia")
    return config["data"], {e["name"]: e.get("value", "") for e in container["env"]}


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_the_key_file_ships_and_is_loaded(overlay: str) -> None:
    files, env = _authelia(overlay)
    assert JWKS_FILE in files, f"{overlay}: {JWKS_FILE} is not in authelia-config"
    loaded = [Path(p).name for p in env["X_AUTHELIA_CONFIG"].split(",")]
    # Every file the ConfigMap carries is loaded, so a file that ships is never ignored.
    assert sorted(loaded) == sorted(files), (
        f"{overlay}: X_AUTHELIA_CONFIG loads {loaded}, the ConfigMap has {sorted(files)}"
    )
    assert env.get("X_AUTHELIA_CONFIG_FILTERS") == "template", f"{overlay}: the secret template is never rendered"


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_the_deprecated_key_is_gone(overlay: str) -> None:
    files, env = _authelia(overlay)
    assert not [n for n in env if "ISSUER_PRIVATE_KEY" in n], f"{overlay}: still injects issuer_private_key"
    assert "issuer_private_key" not in files["configuration.yml"]


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_the_kid_stays_derived(overlay: str) -> None:
    """No key_id: Authelia derives the kid from the key, as it did for issuer_private_key.

    Measured 2026-10-20 before the change: staging served `7886a2-rs256`, prod `c91fc0-rs256`,
    both the derived form. A pinned key_id would hand every client a kid it never cached.
    """
    files, _ = _authelia(overlay)
    text = files[JWKS_FILE]
    assert not re.search(r"^\s*(- )?key_id:", text, re.MULTILINE), f"{overlay}: a key_id would change the kid clients cached"
    assert len(re.findall(r"^\s*- key:", text, re.MULTILINE)) == 1, f"{overlay}: expected exactly one signing key"


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_the_template_reads_a_key_the_secret_carries(overlay: str) -> None:
    files, _ = _authelia(overlay)
    paths = SECRET_REF.findall(files[JWKS_FILE])
    assert len(paths) == 1, f"{overlay}: expected one secret reference, found {paths}"
    directory, name = paths[0].rsplit("/", 1)
    assert directory == "/run/secrets", f"{overlay}: {paths[0]} is not under the Secret mount"
    secret_keys = (REPO / "toolkit/features/k8s_secrets.py").read_text()
    assert f'"{name}":' in secret_keys, f"{overlay}: the authelia-secrets Secret has no key {name!r}"
