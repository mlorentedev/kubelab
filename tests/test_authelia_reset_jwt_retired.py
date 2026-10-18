"""#900: the password-reset JWT secret is retired with the flow it signed.

#1593 disabled self-service password reset (`password_reset.disable: true`), and
Authelia asks for `identity_validation.reset_password.jwt_secret` only while the
flow is enabled. A secret that nothing reads but that `credentials generate`
still seeds, the catalog still audits and every env's SOPS still carries is
debt, so #900 required it to go in the same change as the flow.

Every check here reads committed files or the rendered overlays. SOPS key names
are plaintext, so the vault check needs no decryption.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from toolkit.features.credentials import IMMUTABLE_SECRETS
from toolkit.features.k8s_secrets import SECRET_DEFINITIONS
from toolkit.features.secrets_manager import SECRET_CATALOG

ROOT = Path(__file__).resolve().parents[1]
KEY = "jwt_secret_reset_password"
KEY_PATH = f"apps.services.security.authelia.{KEY}"
ENV_VAR = "AUTHELIA_IDENTITY_VALIDATION_RESET_PASSWORD_JWT_SECRET_FILE"
TEMPLATE = ROOT / "infra/config/authelia/templates/configuration.yml.j2"


def test_the_catalog_no_longer_registers_the_secret() -> None:
    assert KEY_PATH not in {spec.key_path for spec in SECRET_CATALOG}


def test_credentials_generate_no_longer_preserves_it() -> None:
    assert KEY_PATH not in IMMUTABLE_SECRETS


def test_no_k8s_secret_carries_it() -> None:
    sources = {var for mapping in SECRET_DEFINITIONS for var in mapping.keys.values()}
    assert "APPS_SERVICES_SECURITY_AUTHELIA_JWT_SECRET_RESET_PASSWORD" not in sources


@pytest.mark.parametrize("env", ["dev", "staging", "prod"])
def test_no_env_vault_holds_the_key(env: str) -> None:
    vault = yaml.safe_load((ROOT / f"infra/config/secrets/{env}.enc.yaml").read_text())
    authelia = vault.get("apps", {}).get("services", {}).get("security", {}).get("authelia", {})
    assert KEY not in authelia


@pytest.mark.parametrize("overlay", ["staging", "prod"])
def test_the_rendered_authelia_reads_no_reset_jwt(overlay: str) -> None:
    if shutil.which("kubectl") is None:
        pytest.skip(f"kubectl not on PATH: the {overlay} Authelia manifests were NOT checked")
    rendered = subprocess.run(
        ["kubectl", "kustomize", str(ROOT / f"infra/k8s/overlays/{overlay}")],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert ENV_VAR not in rendered


def test_the_dev_template_disables_reset_and_signs_nothing_for_it() -> None:
    text = TEMPLATE.read_text()
    assert "RESET_PASSWORD" not in text
    assert "password_reset:\n    disable: true" in text
