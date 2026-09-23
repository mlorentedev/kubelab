"""SSOT-017: resolve the declared OIDC client list for an environment.

`apps.services.security.authelia.oidc_clients` in `common.yaml` is the only place
an OIDC client is declared. This module turns it into the list Authelia registers
for one environment, and it is the one resolver both renderers use — the K8s
client file and the Compose dev config — so neither derives hosts or digest keys
on its own (ADR-040 §1: the provider side is generated, not synchronized).

Resolution needs no SOPS. The `client_secret` digests are attached separately,
from the stored `..._hash` keys, because argon2 is salted: recomputing a digest on
every render would make every render a diff (SSOT-017 proposal, R7).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]

KNOWN_ENVS = ("dev", "staging", "prod")

# No defaults for these, deliberately: token_endpoint_auth_method differs per
# client (argocd is the client_secret_post one), so a default would break exactly
# one client at token exchange and read as that client's bug (proposal R1).
REQUIRED_FIELDS = (
    "client_id",
    "client_name",
    "envs",
    "redirect",
    "scopes",
    "token_endpoint_auth_method",
    "authorization_policy",
    "consent_mode",
)

_AUTHELIA = "apps.services.security.authelia"

# The Authelia config files each K8s environment mounts. Prod replaces the base
# ConfigMap (`behavior: replace`), so the two environments never share a file.
_CONFIG_DIRS = {
    "staging": PROJECT_ROOT / "infra/k8s/base/services/authelia-config",
    "prod": PROJECT_ROOT / "infra/k8s/overlays/prod/authelia-config",
}
CLIENTS_FILE_NAME = "oidc-clients.yml"


class OidcClientError(ValueError):
    """A declared OIDC client cannot be resolved."""


def load_values(env: str, project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """`common.yaml` deep-merged with `<env>.yaml` — plaintext values only, no SOPS."""
    from toolkit.features.configuration import ConfigurationManager

    return ConfigurationManager(env=env, project_root=project_root).get_plaintext_values()


def _lookup(values: dict[str, Any], dotted: str) -> Any:
    node: Any = values
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def declared_clients(values: dict[str, Any]) -> list[dict[str, Any]]:
    return list(_lookup(values, f"{_AUTHELIA}.oidc_clients") or [])


def _validate(client: dict[str, Any]) -> None:
    name = client.get("client_id", "<no client_id>")
    missing = [field for field in REQUIRED_FIELDS if field not in client]
    if missing:
        raise OidcClientError(f"OIDC client '{name}' is missing required field(s): {', '.join(missing)}")
    unknown = [env for env in client["envs"] if env not in KNOWN_ENVS]
    if unknown or not client["envs"]:
        raise OidcClientError(f"OIDC client '{name}' declares invalid envs {client['envs']!r}")


def resolve_clients(values: dict[str, Any], env: str) -> list[dict[str, Any]]:
    """The clients registered in `env`, in Authelia's shape, without `client_secret`."""
    resolved = []
    for client in declared_clients(values):
        _validate(client)
        if env not in client["envs"]:
            continue
        redirect = client["redirect"]
        host = _lookup(values, redirect["domain"])
        if not isinstance(host, str) or not host:
            raise OidcClientError(
                f"OIDC client '{client['client_id']}': redirect domain '{redirect['domain']}' "
                f"resolves to nothing in {env}"
            )
        resolved.append(
            {
                "client_id": client["client_id"],
                "client_name": client["client_name"],
                # Every client here is confidential. A public client would be a
                # deliberate schema change, not a per-client toggle.
                "public": False,
                "authorization_policy": client["authorization_policy"],
                "token_endpoint_auth_method": client["token_endpoint_auth_method"],
                "redirect_uris": [f"https://{host}{redirect['path']}"],
                "scopes": list(client["scopes"]),
                "consent_mode": client["consent_mode"],
            }
        )
    return resolved


def digest_key(client_id: str) -> str:
    """SOPS key of a client's stored secret digest.

    The convention `generator_authelia.py` already used: drop a trailing `-oidc`,
    then `-` becomes `_`. It yields exactly the keys that exist for every
    registered client (`vikunja-oidc` → `..._vikunja_hash`).
    """
    suffix = client_id.removesuffix("-oidc").replace("-", "_")
    return f"{_AUTHELIA}.oidc_client_secret_{suffix}_hash"


def config_files(env: str) -> list[Path]:
    """Every Authelia config file mounted in `env`, in load order."""
    directory = _CONFIG_DIRS[env]
    return [path for path in (directory / "configuration.yml", directory / CLIENTS_FILE_NAME) if path.exists()]


def clients_file(env: str) -> Path:
    return _CONFIG_DIRS[env] / CLIENTS_FILE_NAME


def render_clients(clients: list[dict[str, Any]], digests: dict[str, str]) -> str:
    """The generated `oidc-clients.yml`: the whole `clients` list, digests attached.

    The whole list lives in this one file because Authelia merges config files
    but does not combine lists across them.
    """
    rendered = []
    for client in clients:
        client_id = client["client_id"]
        if not digests.get(client_id):
            raise OidcClientError(f"OIDC client '{client_id}': no stored digest at {digest_key(client_id)}")
        entry = {"client_id": client_id, "client_secret": digests[client_id]}
        entry.update({k: v for k, v in client.items() if k != "client_id"})
        rendered.append(entry)
    header = (
        "# GENERATED by `toolkit sync oidc` from apps.services.security.authelia.oidc_clients\n"
        "# (common.yaml) and the stored SOPS digests. Do not edit: change the SSOT and\n"
        "# regenerate. SSOT-017 / ADR-040 §1.\n"
    )
    body = yaml.safe_dump(
        {"identity_providers": {"oidc": {"clients": rendered}}},
        sort_keys=False,
        default_flow_style=False,
        width=1000,
    )
    return header + "---\n" + body


def build_clients_file(env: str, merged_config: dict[str, Any]) -> str:
    """Render `env`'s client file from a config already merged with its SOPS secrets."""
    clients = resolve_clients(merged_config, env)
    digests = {client["client_id"]: _lookup(merged_config, digest_key(client["client_id"])) for client in clients}
    return render_clients(clients, digests)


def sync_env(env: str, project_root: Path = PROJECT_ROOT) -> int:
    """Regenerate `env`'s `oidc-clients.yml`. The sole writer of the client list (AC3).

    Fails loud on an unresolvable client or a missing digest rather than skipping
    it: a skipped client is a registration silently dropped (lesson-022).
    """
    from toolkit.core.io import write_text_lf
    from toolkit.core.logging import logger
    from toolkit.features.configuration import ConfigurationManager

    if env not in _CONFIG_DIRS:
        logger.info(f"oidc: {env} has no K8s Authelia config; its clients render through the Compose path")
        return 0
    try:
        content = build_clients_file(env, ConfigurationManager(env=env, project_root=project_root).get_merged_config())
    except OidcClientError as exc:
        logger.error(f"oidc: {exc}")
        return 1
    target = clients_file(env)
    if target.exists() and target.read_text(encoding="utf-8") == content:
        logger.info(f"oidc: {target.name} for {env} already current")
        return 0
    write_text_lf(target, content)
    logger.success(f"oidc: regenerated {target}")
    return 0
