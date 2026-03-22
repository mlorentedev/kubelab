"""Configure OIDC authentication sources on Gitea via CLI.

Uses kubectl exec to run `gitea admin auth` inside the pod.
More robust than HTTP API — no middleware issues, no API version changes.

Usage: python toolkit/scripts/configure_oidc.py --env staging
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.features.configuration import ConfigurationManager  # noqa: E402


def get_config(env: str) -> dict[str, str]:
    """Get OIDC config from merged config + SOPS."""
    cm = ConfigurationManager(env, PROJECT_ROOT)
    config = cm.get_merged_config()
    gitea = config["apps"]["services"]["core"]["gitea"]
    authelia = config["apps"]["services"]["security"]["authelia"]

    return {
        "oidc_client_secret": gitea.get("oidc_client_secret", ""),
        "authelia_url": f"{config.get('protocol', 'https')}://{authelia.get('domain', '')}",
    }


def kubectl_exec(args_list: list[str], env: str) -> subprocess.CompletedProcess[str]:
    """Run a command inside the Gitea pod via kubectl exec."""
    kubeconfig = str(Path.home() / f".kube/kubelab-{env}-config")
    full_cmd = [
        "kubectl",
        "exec",
        "-n",
        "kubelab",
        "deploy/gitea",
        "--kubeconfig",
        kubeconfig,
        "--",
        *args_list,
    ]
    return subprocess.run(full_cmd, capture_output=True, text=True)


def gitea_cmd(gitea_args: list[str], env: str) -> subprocess.CompletedProcess[str]:
    """Run a gitea CLI command as the git user inside the pod."""
    return kubectl_exec(["su", "git", "-c", " ".join(gitea_args)], env)


def configure_gitea_oidc(config: dict[str, str], env: str) -> None:
    """Delete and recreate Authelia OAuth2 provider in Gitea via CLI."""
    discovery_url = f"{config['authelia_url']}/.well-known/openid-configuration"
    secret = config["oidc_client_secret"]

    print(f"Discovery URL: {discovery_url}")

    # Delete existing auth source if present
    result = gitea_cmd(["gitea", "admin", "auth", "list"], env)
    if result.returncode == 0 and "authelia" in result.stdout.lower():
        for line in result.stdout.strip().split("\n"):
            if "authelia" in line.lower():
                auth_id = line.split()[0]
                gitea_cmd(["gitea", "admin", "auth", "delete", "--id", auth_id], env)
                print(f"Deleted existing auth source (ID={auth_id})")
                break

    # Create fresh with current config
    result = gitea_cmd(
        [
            "gitea",
            "admin",
            "auth",
            "add-oauth",
            "--name",
            "authelia",
            "--provider",
            "openidConnect",
            "--key",
            "gitea",
            "--secret",
            f"'{secret}'",
            "--auto-discover-url",
            f"'{discovery_url}'",
            "--scopes",
            "'openid,profile,email,groups'",
        ],
        env,
    )

    if result.returncode != 0:
        print(f"ERROR: Create failed: {result.stderr}")
        sys.exit(1)

    print("Created Authelia OIDC provider in Gitea")

    # Restart Gitea to reload OIDC config from DB (CLI writes to SQLite but web process caches in memory)
    print("Restarting Gitea to reload OIDC config...")
    restart_result = subprocess.run(
        [
            "kubectl",
            "rollout",
            "restart",
            "deploy/gitea",
            "-n",
            "kubelab",
            "--kubeconfig",
            str(Path.home() / f".kube/kubelab-{env}-config"),
        ],
        capture_output=True,
        text=True,
    )
    if restart_result.returncode == 0:
        print("Gitea restarted successfully")
    else:
        print(f"WARNING: Gitea restart failed: {restart_result.stderr}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure OIDC providers")
    parser.add_argument("--env", "-e", required=True, help="Target environment")
    args = parser.parse_args()

    config = get_config(args.env)
    if not config["oidc_client_secret"]:
        print("ERROR: Gitea oidc_client_secret not found in SOPS")
        sys.exit(1)

    configure_gitea_oidc(config, args.env)


if __name__ == "__main__":
    main()
