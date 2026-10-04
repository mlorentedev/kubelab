"""Per-node R2 credentials and restic passwords (BACKUP-057 PR 3, Q1).

Each `backup.sources` node gets an Object Read & Write token scoped to its own
bucket, `kubelab-backup-<node>`, and a restic password of its own. The token is
minted through the Cloudflare API and its S3 pair goes straight into SOPS: no
state file, so no second copy of the secret (Q1 rejected the Terraform route
for exactly that reason).

The S3 pair a token yields is its id (Access Key ID) and the SHA-256 of its
value (Secret Access Key). The value is returned once, used in memory and never
printed.

A minted token is verified by consequence before anything is stored: it must
list its own bucket and be refused on another node's. One that fails either is
revoked, and nothing is written.

Nothing reads these keys yet: the consumers switch to them in PR 4.
"""

from __future__ import annotations

import hashlib
import json
import secrets as _secrets
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Optional, Protocol

from toolkit.core.logging import logger
from toolkit.features.r2_tfvars import node_bucket

API = "https://api.cloudflare.com/client/v4"

# The credential that mints. Creating an account token needs the
# "Account API Tokens Write" permission, which a token that holds it can use to
# create a token with ANY permission. Which token carries it is the operator's
# decision (open on the BACKUP-057 PR 3 pull request); this is the one place
# that names it.
MINTER_KEY = "cloudflare.r2_admin_token"

# The SOPS file the node keys are written to (proposal item 1).
SECRETS_ENV = "prod"

WRITE_GROUP = "Workers R2 Storage Bucket Item Write"
# The node buckets set no jurisdiction (infra/terraform/r2/main.tf).
JURISDICTION = "default"
RESTIC_PASSWORD_BYTES = 48

_TIMEOUT = 30
# A new token can take a moment to reach R2; the own-bucket check retries.
_SCOPE_ATTEMPTS = 4
_SCOPE_DELAY_S = 5.0

HttpFn = Callable[[str, str, Optional[dict[str, Any]]], Any]
# (argv, env) -> (returncode, stdout, stderr), the backup_destination seam.
RunFn = Callable[[list[str], dict[str, str]], "tuple[int, str, str]"]


class MintError(RuntimeError):
    """A mint did not complete. The message never contains a secret."""


class Store(Protocol):
    def show(self, path: str) -> Optional[str]: ...

    def write(self, data: dict[str, str]) -> bool: ...


def access_key_path(node: str) -> str:
    return f"backup.r2.nodes.{node}.access_key_id"


def secret_key_path(node: str) -> str:
    return f"backup.r2.nodes.{node}.secret_access_key"


def restic_password_path(node: str) -> str:
    return f"backup.nodes.{node}.restic_password"


def bucket_resource(account_id: str, bucket: str) -> str:
    return f"com.cloudflare.edge.r2.bucket.{account_id}_{JURISDICTION}_{bucket}"


def token_request(node: str, *, account_id: str, write_group_id: str) -> dict[str, Any]:
    """The token policy for one node: Object Read & Write on its bucket, nothing else."""
    bucket = node_bucket(node)
    return {
        "name": bucket,
        "policies": [
            {
                "effect": "allow",
                "resources": {bucket_resource(account_id, bucket): "*"},
                "permission_groups": [{"id": write_group_id}],
            }
        ],
    }


def cloudflare_http(token: str) -> HttpFn:
    """Call the Cloudflare API with `token`. Errors name the call, never the token."""

    def call(method: str, path: str, body: Optional[dict[str, Any]] = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"{API}{path}",
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310 - fixed https host
                payload = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            raise MintError(f"{method} {path} returned HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise MintError(f"{method} {path} failed: {exc}") from None
        if not payload.get("success"):
            codes = [e.get("code") for e in payload.get("errors") or []]
            raise MintError(f"{method} {path} was refused by the API (codes {codes})")
        return payload.get("result")

    return call


def permission_group_id(http: HttpFn, account_id: str, name: str) -> str:
    groups = http("GET", f"/accounts/{account_id}/tokens/permission_groups", None) or []
    for group in groups:
        if group.get("name") == name:
            return str(group["id"])
    raise MintError(f"The permission group {name!r} is not offered to this account; refusing to guess one.")


def _s3_env(key_id: str, secret: str) -> dict[str, str]:
    return {
        "AWS_ACCESS_KEY_ID": key_id,
        "AWS_SECRET_ACCESS_KEY": secret,
        "AWS_DEFAULT_REGION": "auto",
        "AWS_REQUEST_CHECKSUM_CALCULATION": "when_required",
        "AWS_RESPONSE_CHECKSUM_VALIDATION": "when_required",
    }


def _lists(run: RunFn, endpoint: str, bucket: str, env: dict[str, str]) -> bool:
    argv = ["aws", "--endpoint-url", endpoint, "s3api", "list-objects-v2", "--bucket", bucket, "--max-keys", "1"]
    rc, _, _ = run(argv, env)
    return rc == 0


def _scope_error(
    node: str, endpoint: str, other_bucket: str, env: dict[str, str], run: RunFn, sleep: Callable[[float], None]
) -> Optional[str]:
    """Why the pair fails the by-consequence check, or None when it passes."""
    own = node_bucket(node)
    for attempt in range(_SCOPE_ATTEMPTS):
        if _lists(run, endpoint, own, env):
            break
        if attempt + 1 < _SCOPE_ATTEMPTS:
            sleep(_SCOPE_DELAY_S)
    else:
        return f"the token minted for {node} cannot list its own bucket {own}"
    if _lists(run, endpoint, other_bucket, env):
        return f"the token minted for {node} can list another node's bucket {other_bucket}"
    return None


def mint_node(
    node: str,
    *,
    account_id: str,
    endpoint: str,
    other_bucket: str,
    http: HttpFn,
    store: Store,
    run: RunFn,
    rotate: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Mint `node`'s pair if absent, or replace it with `rotate`. Returns kept/minted/rotated."""
    old_id = store.show(access_key_path(node))
    if old_id and store.show(secret_key_path(node)) and not rotate:
        return "kept"

    group = permission_group_id(http, account_id, WRITE_GROUP)
    result = http(
        "POST", f"/accounts/{account_id}/tokens", token_request(node, account_id=account_id, write_group_id=group)
    )
    key_id = str(result["id"])
    secret = hashlib.sha256(str(result["value"]).encode()).hexdigest()

    def revoke_new(reason: str) -> MintError:
        http("DELETE", f"/accounts/{account_id}/tokens/{key_id}", None)
        return MintError(f"{reason}; the new token was revoked and nothing was stored")

    problem = _scope_error(node, endpoint, other_bucket, _s3_env(key_id, secret), run, sleep)
    if problem:
        raise revoke_new(problem)
    if not store.write({access_key_path(node): key_id, secret_key_path(node): secret}):
        raise revoke_new(f"writing {node}'s pair to SOPS failed")

    if rotate and old_id:
        http("DELETE", f"/accounts/{account_id}/tokens/{old_id}", None)
        return "rotated"
    return "minted"


def ensure_restic_password(node: str, store: Store) -> str:
    """Generate `node`'s restic password if absent. Never replaces one: that orphans the repository."""
    if store.show(restic_password_path(node)):
        return "kept"
    if not store.write({restic_password_path(node): _secrets.token_urlsafe(RESTIC_PASSWORD_BYTES)}):
        raise MintError(f"writing {node}'s restic password to SOPS failed")
    return "generated"


class SopsStore:
    """The SOPS seam: reads the merged config, writes one batch to the node secrets file."""

    def __init__(self, env: str = SECRETS_ENV) -> None:
        from toolkit.config.constants import PATH_STRUCTURES
        from toolkit.features.configuration import ConfigurationManager

        self._cm = ConfigurationManager(env)
        self._file = self._cm.project_root / PATH_STRUCTURES.CONFIG_SECRETS_DIR / f"{env}.enc.yaml"

    def show(self, path: str) -> Optional[str]:
        value = self._cm.get_secret_by_path(path)
        return str(value) if value else None

    def write(self, data: dict[str, str]) -> bool:
        return bool(self._cm.batch_update_secrets(data, secret_file_path=self._file))


def mint_all(node: Optional[str] = None, rotate: bool = False) -> bool:
    """Mint every node's pair and password, or one node's. True iff every node completed."""
    from toolkit.features.backup_destination import _default_run

    store = SopsStore()
    config = store._cm.get_merged_config()
    backup = config.get("backup") or {}
    r2 = backup.get("r2") or {}
    nodes = sorted(backup.get("sources") or {})
    if node is not None and node not in nodes:
        logger.error(f"{node!r} is not a backup.sources node ({', '.join(nodes)})")
        return False

    minter = store.show(MINTER_KEY)
    if not minter:
        logger.error(f"{MINTER_KEY} is absent from SOPS; nothing can be minted.")
        return False
    http = cloudflare_http(minter)

    ok = True
    for name in [node] if node else nodes:
        others = [n for n in nodes if n != name] or ["scratch-other"]
        try:
            token = mint_node(
                name,
                account_id=str(r2["account_id"]),
                endpoint=str(r2["endpoint"]),
                other_bucket=node_bucket(others[0]),
                http=http,
                store=store,
                run=_default_run,
                rotate=rotate,
            )
            password = ensure_restic_password(name, store)
        except (MintError, KeyError) as exc:
            logger.error(f"{name}: {exc}")
            ok = False
            continue
        logger.success(f"{name}: token {token}, restic password {password}")
    return ok
