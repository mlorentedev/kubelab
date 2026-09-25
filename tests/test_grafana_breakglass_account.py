"""Grafana's break-glass account is a local account no SSO login can adopt (#951, option A).

Grafana treats an SSO-linked account as external, and `errOnExternalUser` refuses
every password change on it (13.0.2), so an emergency account that SSO links can
never be rotated again. The break-glass account is therefore row id 1 under a
login and email that no Authelia user has. Four places must name the same
account: the declaration, the Secret that seeds a fresh install's login, the
ConfigMap that seeds its email, and the reconciler that renames an existing row.
These tests fail when any of them names a different one.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
from typing import Any

import pytest
import yaml

from toolkit.features import break_glass as bg
from toolkit.features.grafana_admin_identity import _resolve_declared_account
from toolkit.features.k8s_secrets import _resolve_grafana_admin
from toolkit.features.oidc_clients import load_values

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _grafana_decl() -> dict[str, Any]:
    return bg.declarations(load_values("prod", REPO_ROOT))["grafana"]


def test_the_declared_account_is_local_not_an_identity() -> None:
    """Reverting to `identity: superadmin` would make the operator's own SSO login the
    emergency account, and the first SSO login would make it unrotatable."""
    decl = _grafana_decl()
    assert "identity" not in decl, "Grafana's break-glass account must belong to nobody in Authelia"
    assert decl.get("login") and decl.get("email")


def test_the_seed_and_the_reconciler_name_the_same_account() -> None:
    class PlaintextConfig:
        def get_merged_config(self) -> dict[str, Any]:
            return load_values("prod", REPO_ROOT)

    decl = _grafana_decl()
    assert _resolve_grafana_admin(PlaintextConfig()) == decl["login"]  # type: ignore[arg-type]
    assert _resolve_declared_account(REPO_ROOT) == (decl["login"], decl["email"])


def _rendered_grafana_env(overlay: str) -> dict[str, str]:
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not on PATH: cannot render the overlay (a skip is CANNOT CHECK, not OK)")
    result = subprocess.run(
        ["kubectl", "kustomize", str(REPO_ROOT / "infra/k8s/overlays" / overlay)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    for doc in yaml.safe_load_all(result.stdout):
        name = ((doc or {}).get("metadata") or {}).get("name", "")
        if doc and doc.get("kind") == "ConfigMap" and name.startswith("grafana-config-"):
            return doc["data"]
    raise AssertionError(f"no grafana-config ConfigMap in the {overlay} overlay")


@pytest.mark.parametrize("overlay", ["staging", "prod"])
def test_a_fresh_install_seeds_the_declared_email(overlay: str) -> None:
    """Read from the rendered overlay, not grafana.env: prod patches this ConfigMap by
    name, and a patch that dropped the key would pass any check of the source file."""
    assert _rendered_grafana_env(overlay).get("GF_SECURITY_ADMIN_EMAIL") == _grafana_decl()["email"]
