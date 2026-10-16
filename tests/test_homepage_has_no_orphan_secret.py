"""Homepage reads no Secret, and the one it used to read is retired (#1761).

`homepage-secrets` mapped three keys to SOPS paths that never existed, so `apply-secrets`
wrote a Secret of empty values and reported success. Two widgets put two of those values
in an `Authorization` header: the GitHub one sent `Bearer ` and was answered 401 by an API
that answers its public endpoint 200 without a header. Nothing failed loudly, which is why
the Secret outlived every review. These tests pin the state after removing it.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from toolkit.features import k8s_secrets

ROOT = Path(__file__).resolve().parents[1]
K8S = ROOT / "infra" / "k8s"
SECRETS = ROOT / "infra" / "config" / "secrets"


def _text_files() -> list[Path]:
    return [p for p in K8S.rglob("*") if p.is_file() and p.suffix in {".yaml", ".yml", ".j2", ".json"}]


def test_no_homepage_variable_is_referenced_anywhere_in_the_manifests_or_templates() -> None:
    offenders = [str(p.relative_to(K8S)) for p in _text_files() if "HOMEPAGE_VAR_" in p.read_text(encoding="utf-8")]
    assert offenders == [], f"a HOMEPAGE_VAR_* reference needs a Secret that resolves, and none exists: {offenders}"


def test_no_manifest_mounts_the_retired_secret() -> None:
    offenders = [str(p.relative_to(K8S)) for p in _text_files() if "homepage-secrets" in p.read_text(encoding="utf-8")]
    assert offenders == [], f"a pod referencing a Secret that apply-secrets deletes does not start: {offenders}"


def test_the_secret_is_no_longer_rendered_and_is_deleted_on_every_apply() -> None:
    assert "homepage-secrets" not in {m.name for m in k8s_secrets.SECRET_DEFINITIONS}
    assert ("kubelab", "homepage-secrets") in k8s_secrets.RETIRED_SECRETS


def test_the_three_revoked_credentials_are_gone_from_every_vault() -> None:
    """#2323: a credential revoked at its provider is dead weight in SOPS, and a live-looking one is a lure.

    Key names are plaintext in SOPS, so this reads the structure without decrypting.
    """
    revoked = {"cloudflare_token", "github_token", "uptimekuma_key"}
    offenders = []
    vaults = sorted(SECRETS.glob("*.enc.yaml"))
    # Positive controls: an absence check is green over an empty sample or a layout it cannot read.
    # The vaults are found, and the walk below resolves a key that is known to exist (the Authelia
    # block, CLAUDE.md), so a renamed directory or a reshaped tree turns this red instead of silent.
    assert vaults, f"no vault found under {SECRETS}"
    reachable = [
        v.name
        for v in vaults
        if (yaml.safe_load(v.read_text(encoding="utf-8")) or {})
        .get("apps", {})
        .get("services", {})
        .get("security", {})
        .get("authelia")
    ]
    assert reachable, "the path walked below reaches no known secret in any vault; the layout changed"
    for vault in vaults:
        data = yaml.safe_load(vault.read_text(encoding="utf-8")) or {}
        homepage = data.get("apps", {}).get("services", {}).get("dashboard", {}).get("homepage", {}) or {}
        offenders += [f"{vault.name}:{key}" for key in revoked & set(homepage)]
    assert offenders == [], f"revoked Homepage credentials still stored: {offenders}"
