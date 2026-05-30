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

import httpx

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

    # Check if auth source exists
    auth_id = None
    result = gitea_cmd(["gitea", "admin", "auth", "list"], env)
    if result.returncode == 0 and "authelia" in result.stdout.lower():
        for line in result.stdout.strip().split("\n"):
            if "authelia" in line.lower():
                auth_id = line.split()[0]
                break

    oauth_args = [
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
    ]

    if auth_id:
        # Update existing source (preserves linked user accounts)
        result = gitea_cmd(
            ["gitea", "admin", "auth", "update-oauth", "--id", auth_id, *oauth_args],
            env,
        )
        action = f"Updated existing auth source (ID={auth_id})"
    else:
        # Create new source
        result = gitea_cmd(
            ["gitea", "admin", "auth", "add-oauth", *oauth_args],
            env,
        )
        action = "Created new Authelia OIDC provider"

    if result.returncode != 0:
        print(f"ERROR: {action.split()[0]} failed: {result.stderr}")
        sys.exit(1)

    print(action)

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


# Verdicts returned by classify_token_response (OIDC-DRIFT-001).
VERIFY_PASS = "pass"  # client authentication succeeded (secret matches the hash)
VERIFY_FAIL = "fail"  # invalid_client — secret<->hash drift or stale Gitea OAuth source
VERIFY_INCONCLUSIVE = "inconclusive"  # could not reach/parse the endpoint — do not gate on this


# RFC 6749 §5.2 token-endpoint error codes. `invalid_client` denotes failed CLIENT
# authentication; the rest are raised only AFTER the client has authenticated.
_OAUTH2_TOKEN_ERRORS = frozenset(
    {
        "invalid_request",
        "invalid_client",
        "invalid_grant",
        "unauthorized_client",
        "unsupported_grant_type",
        "invalid_scope",
    }
)


def classify_token_response(status_code: int, body: dict[str, object]) -> str:
    """Classify an OAuth2 token-endpoint response into a drift verdict.

    OIDC-DRIFT-001: the only thing we can assert without enabling a grant is whether
    the *client authenticated* — i.e. whether the plaintext secret we hold matches the
    argon2 hash Authelia stores. Three outcomes, because a JSON body is not proof that
    we even reached the token endpoint (an ingress/proxy/Authelia 404/403/502 can be
    JSON too):

      - `access_token` present -> the client authenticated AND the grant ran -> PASS.
      - an OAuth2 error code present (RFC 6749 §5.2):
          * `invalid_client` -> the secret did NOT match -> FAIL (the drift / stale
            Gitea source the incident was about).
          * any other §5.2 code -> client auth already PASSED, we tripped on the grant
            -> PASS (drift not present).
      - anything else (no access_token, no recognized OAuth2 error) -> we did not get a
        real token-endpoint response -> INCONCLUSIVE. Never report PASS for a body we
        cannot interpret — that would be the same silent-success this check exists to kill.

    The machine-readable `error` field is authoritative; the HTTP status (400 vs 401 for
    invalid_client) varies across implementations and is not relied upon here.
    """
    if body.get("access_token"):
        return VERIFY_PASS

    error = str(body.get("error", "")).strip().lower()
    if error in _OAUTH2_TOKEN_ERRORS:
        return VERIFY_FAIL if error == "invalid_client" else VERIFY_PASS

    return VERIFY_INCONCLUSIVE


def verify_token_endpoint(config: dict[str, str], env: str) -> str:
    """Probe Authelia's token endpoint with the Gitea client credentials.

    Returns a VERIFY_* verdict. Network/parse failures map to VERIFY_INCONCLUSIVE so a
    transient outage never reports a false drift. Hits the EXTERNAL issuer URL because
    Authelia's OIDC issuer is request-dependent (CLAUDE.md gotcha), and posts the
    secret in the body to match Gitea's `client_secret_post` auth method.
    """
    token_url = f"{config['authelia_url']}/api/oidc/token"
    try:
        resp = httpx.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": "gitea",
                "client_secret": config["oidc_client_secret"],
            },
            headers={"Accept": "application/json"},
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        print(f"WARNING: token endpoint unreachable ({exc}) — skipping drift verification")
        return VERIFY_INCONCLUSIVE

    try:
        body = resp.json()
    except ValueError:
        print(f"WARNING: token endpoint returned non-JSON (HTTP {resp.status_code}) — skipping verification")
        return VERIFY_INCONCLUSIVE

    verdict = classify_token_response(resp.status_code, body)
    if verdict == VERIFY_FAIL:
        err = body.get("error_description") or body.get("error") or "client authentication failed"
        print(f"FAIL: OIDC token round-trip rejected the Gitea client secret: {err}")
    elif verdict == VERIFY_INCONCLUSIVE:
        print(
            f"WARNING: token endpoint returned an unrecognized JSON response (HTTP {resp.status_code}) "
            "— not a token-endpoint round-trip; skipping verification"
        )
    else:
        print("✓ Token endpoint round-trip succeeded (Gitea client secret matches Authelia)")
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure OIDC providers")
    parser.add_argument("--env", "-e", required=True, help="Target environment")
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip the post-update token round-trip verification (OIDC-DRIFT-001)",
    )
    args = parser.parse_args()

    config = get_config(args.env)
    if not config["oidc_client_secret"]:
        print("ERROR: Gitea oidc_client_secret not found in SOPS")
        return 1

    configure_gitea_oidc(config, args.env)

    if args.skip_verify:
        return 0

    verdict = verify_token_endpoint(config, args.env)
    if verdict == VERIFY_FAIL:
        return 2  # drift confirmed: secret<->hash mismatch or stale Gitea source
    return 0


if __name__ == "__main__":
    sys.exit(main())
