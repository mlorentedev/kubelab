"""Sync OIDC client_secret hashes from SOPS into Authelia K8s ConfigMap YAMLs.

Reads argon2 hashes from SOPS and replaces placeholder/stale values in:
  - infra/k8s/base/services/authelia.yaml (staging)
  - infra/k8s/overlays/prod/patches.yaml (prod)

This eliminates the manual step of copy-pasting hashes after `toolkit secrets hash`.

Usage: python toolkit/scripts/sync_oidc_hashes.py --env staging
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.features.configuration import ConfigurationManager  # noqa: E402


def _deep_merge(base: dict[str, object], override: dict[str, object]) -> None:
    """Merge override into base recursively (base is mutated)."""
    for key, value in override.items():
        base_val = base.get(key)
        if isinstance(base_val, dict) and isinstance(value, dict):
            _deep_merge(base_val, value)
        elif key not in base:
            base[key] = value


# Map: SOPS key → (OIDC client_id, which files to update)
OIDC_CLIENTS = {
    "apps.services.security.authelia.oidc_client_secret_minio_hash": {
        "client_id": "minio",
        "files": ["base", "prod"],
    },
    "apps.services.security.authelia.oidc_client_secret_grafana_hash": {
        "client_id": "grafana",
        "files": ["base", "prod"],
    },
    "apps.services.security.authelia.oidc_client_secret_gitea_hash": {
        "client_id": "gitea",
        "files": ["base", "prod"],
    },
    "apps.services.security.authelia.oidc_client_secret_argocd_hash": {
        "client_id": "argocd",
        "files": ["base", "prod"],
    },
}

FILE_PATHS = {
    "base": PROJECT_ROOT / "infra/k8s/base/services/authelia.yaml",
    "prod": PROJECT_ROOT / "infra/k8s/overlays/prod/patches.yaml",
}


def resolve_nested(data: dict[str, object], path: str) -> str | None:
    """Resolve dotted path in nested dict."""
    current: object = data
    for key in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return str(current) if isinstance(current, str) else None


def update_client_secret(content: str, client_id: str, new_hash: str) -> str:
    """Replace client_secret value for a specific OIDC client_id in YAML content.

    Matches the pattern:
        client_id: <id>
        ...
        client_secret: '<old_hash>'  # optional comment
    """
    # Find the client block and replace its client_secret
    pattern = re.compile(
        r"(client_id:\s*" + re.escape(client_id) + r"\s*\n"
        r"(?:.*\n)*?"  # non-greedy match of lines between
        r"\s*client_secret:\s*')[^']*('.*)",
        re.MULTILINE,
    )
    match = pattern.search(content)
    if match:
        return content[: match.start()] + match.group(1) + new_hash + match.group(2) + content[match.end() :]
    return content


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync OIDC hashes from SOPS to K8s ConfigMaps")
    parser.add_argument("--env", "-e", required=True, help="Target environment")
    args = parser.parse_args()

    env = args.env

    # Determine which file to update based on environment
    if env == "prod":
        target_key = "prod"
    else:
        target_key = "base"

    cm = ConfigurationManager(env, PROJECT_ROOT)
    try:
        secrets = cm._decrypt_sops(cm.secrets_path / f"{env}.enc.yaml")
    except Exception as e:
        print(f"ERROR: Could not decrypt SOPS for {env}: {e}", file=sys.stderr)
        return 1

    if not secrets:
        print(f"WARNING: No secrets found in {env}.enc.yaml", file=sys.stderr)
        return 0

    # Merge common secrets (hub credentials like Argo CD OIDC live in common)
    try:
        common_secrets = cm._decrypt_sops(cm.secrets_path / "common.enc.yaml")
        if common_secrets:
            _deep_merge(secrets, common_secrets)
    except Exception:
        pass  # common is optional for env-specific runs

    updated = 0
    for sops_path, client_info in OIDC_CLIENTS.items():
        hash_value = resolve_nested(secrets, sops_path)
        if not hash_value or "placeholder" in str(hash_value):
            print(f"SKIP: {sops_path} — not found or still placeholder")
            continue

        if target_key not in client_info["files"]:
            continue

        file_path = FILE_PATHS[target_key]
        content = file_path.read_text()
        client_id = str(client_info["client_id"])
        new_content = update_client_secret(content, client_id, hash_value)

        if new_content != content:
            file_path.write_text(new_content)
            print(f"UPDATED: {client_info['client_id']} hash in {file_path.name}")
            updated += 1
        else:
            print(f"OK: {client_info['client_id']} hash already current in {file_path.name}")

    print(f"\nSynced {updated} OIDC hashes for {env}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
