"""Per-node R2 credentials and restic passwords (BACKUP-057 PR 3, Q1).

Each `backup.sources` node gets an Object Read & Write token scoped to its own
bucket, `kubelab-backup-<node>`, and a restic password of its own. The watcher
gets one Object Read token naming every node bucket and nothing else. Tokens are
minted through the Cloudflare API and their S3 pairs go straight into SOPS: no
state file, so no second copy of the secret (Q1 rejected the Terraform route
for exactly that reason).

The S3 pair a token yields is its id (Access Key ID) and the SHA-256 of its
value (Secret Access Key). The value is returned once, used in memory and never
printed.

A minted token is verified by consequence before anything is stored: it must
list every bucket it was minted for, and get AccessDenied on one it must not
reach. One that fails either is revoked, and nothing is written.

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

# The credential that mints. Creating an account token needs "Account API
# Tokens: Edit", which a token holding it can use to create a token with ANY
# permission, so it is a token of its own rather than a widened
# `cloudflare.r2_admin_token` (operator decision, 2026-10-03).
MINTER_KEY = "cloudflare.r2_token_minter"

# The env whose merged config the mint reads, and the only --env it accepts.
SECRETS_ENV = "prod"

WRITE_GROUP = "Workers R2 Storage Bucket Item Write"
READ_GROUP = "Workers R2 Storage Bucket Item Read"
WATCHER_TOKEN_NAME = "kubelab-backup-watcher"
# The node buckets set no jurisdiction (infra/terraform/r2/main.tf).
JURISDICTION = "default"
RESTIC_PASSWORD_BYTES = 48

_TIMEOUT = 30
# A new token can take a moment to reach R2; the readable-bucket check retries.
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


WATCHER_ACCESS_KEY_PATH = "backup.r2.watcher.access_key_id"
WATCHER_SECRET_KEY_PATH = "backup.r2.watcher.secret_access_key"


def sops_file_for(path: str) -> str:
    """The SOPS file a minted key is written to.

    A node's write pair is used by that node only, so it lives in prod. The
    restic passwords and the watcher pair are also read by the watcher, which
    runs in staging, so they live in common (operator decision, 2026-10-03).
    """
    if path.startswith("backup.r2.nodes."):
        return "prod"
    if path.startswith(("backup.nodes.", "backup.r2.watcher.")):
        return "common"
    raise ValueError(f"{path!r} is not a key this module mints")


def bucket_resource(account_id: str, bucket: str) -> str:
    return f"com.cloudflare.edge.r2.bucket.{account_id}_{JURISDICTION}_{bucket}"


def _token_body(name: str, buckets: list[str], *, account_id: str, group_id: str) -> dict[str, Any]:
    return {
        "name": name,
        "policies": [
            {
                "effect": "allow",
                "resources": {bucket_resource(account_id, b): "*" for b in buckets},
                "permission_groups": [{"id": group_id}],
            }
        ],
    }


def token_request(node: str, *, account_id: str, write_group_id: str) -> dict[str, Any]:
    """The token policy for one node: Object Read & Write on its bucket, nothing else."""
    bucket = node_bucket(node)
    return _token_body(bucket, [bucket], account_id=account_id, group_id=write_group_id)


def watcher_token_request(nodes: list[str], *, account_id: str, read_group_id: str) -> dict[str, Any]:
    """The watcher's policy: Object Read on every node bucket, nothing else."""
    buckets = [node_bucket(n) for n in sorted(nodes)]
    return _token_body(WATCHER_TOKEN_NAME, buckets, account_id=account_id, group_id=read_group_id)


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


def _list(run: RunFn, endpoint: str, bucket: str, env: dict[str, str]) -> tuple[int, str]:
    argv = ["aws", "--endpoint-url", endpoint, "s3api", "list-objects-v2", "--bucket", bucket, "--max-keys", "1"]
    rc, _, err = run(argv, env)
    return rc, err


def _scope_error(
    label: str,
    endpoint: str,
    readable: list[str],
    refused: str,
    env: dict[str, str],
    run: RunFn,
    sleep: Callable[[float], None],
) -> Optional[str]:
    """Why the pair fails the by-consequence check, or None when it passes."""
    for bucket in readable:
        for attempt in range(_SCOPE_ATTEMPTS):
            if _list(run, endpoint, bucket, env)[0] == 0:
                break
            if attempt + 1 < _SCOPE_ATTEMPTS:
                sleep(_SCOPE_DELAY_S)
        else:
            return f"the token minted for {label} cannot list {bucket}, which it was minted for"
    rc, err = _list(run, endpoint, refused, env)
    if rc == 0:
        return f"the token minted for {label} can list {refused}, which it must not reach"
    # Only a refusal proves the scope. A missing bucket or a network error also
    # fails the listing, and would pass a check that looked at the exit code alone.
    if "AccessDenied" not in err:
        return f"listing {refused} failed without AccessDenied, so the scope of {label}'s token is unproven"
    return None


def _mint_token(
    label: str,
    request: Callable[[], dict[str, Any]],
    *,
    paths: tuple[str, str],
    readable: list[str],
    refused: str,
    account_id: str,
    endpoint: str,
    http: HttpFn,
    store: Store,
    run: RunFn,
    rotate: bool,
    sleep: Callable[[float], None],
) -> str:
    """Mint, verify and store one token's pair. Returns kept/minted/rotated."""
    access_path, secret_path = paths
    old_id = store.show(access_path)
    if old_id and store.show(secret_path) and not rotate:
        return "kept"

    result = http("POST", f"/accounts/{account_id}/tokens", request())
    key_id = str(result["id"])
    secret = hashlib.sha256(str(result["value"]).encode()).hexdigest()

    def revoke_new(reason: str) -> MintError:
        http("DELETE", f"/accounts/{account_id}/tokens/{key_id}", None)
        return MintError(f"{reason}; the new token was revoked and nothing was stored")

    problem = _scope_error(label, endpoint, readable, refused, _s3_env(key_id, secret), run, sleep)
    if problem:
        raise revoke_new(problem)
    if not store.write({access_path: key_id, secret_path: secret}):
        raise revoke_new(f"writing {label}'s pair to SOPS failed")

    if rotate and old_id:
        http("DELETE", f"/accounts/{account_id}/tokens/{old_id}", None)
        return "rotated"
    return "minted"


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

    def request() -> dict[str, Any]:
        group = permission_group_id(http, account_id, WRITE_GROUP)
        return token_request(node, account_id=account_id, write_group_id=group)

    return _mint_token(
        node,
        request,
        paths=(access_key_path(node), secret_key_path(node)),
        readable=[node_bucket(node)],
        refused=other_bucket,
        account_id=account_id,
        endpoint=endpoint,
        http=http,
        store=store,
        run=run,
        rotate=rotate,
        sleep=sleep,
    )


def mint_watcher(
    nodes: list[str],
    *,
    account_id: str,
    endpoint: str,
    legacy_bucket: str,
    http: HttpFn,
    store: Store,
    run: RunFn,
    rotate: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Mint the watcher's read pair: every node bucket, refused on the shared legacy bucket."""

    def request() -> dict[str, Any]:
        group = permission_group_id(http, account_id, READ_GROUP)
        return watcher_token_request(nodes, account_id=account_id, read_group_id=group)

    return _mint_token(
        "the watcher",
        request,
        paths=(WATCHER_ACCESS_KEY_PATH, WATCHER_SECRET_KEY_PATH),
        readable=[node_bucket(n) for n in sorted(nodes)],
        refused=legacy_bucket,
        account_id=account_id,
        endpoint=endpoint,
        http=http,
        store=store,
        run=run,
        rotate=rotate,
        sleep=sleep,
    )


def ensure_restic_password(node: str, store: Store) -> str:
    """Generate `node`'s restic password if absent. Never replaces one: that orphans the repository."""
    if store.show(restic_password_path(node)):
        return "kept"
    if not store.write({restic_password_path(node): _secrets.token_urlsafe(RESTIC_PASSWORD_BYTES)}):
        raise MintError(f"writing {node}'s restic password to SOPS failed")
    return "generated"


class SopsStore:
    """The SOPS seam: reads the merged config, writes each key to the file `sops_file_for` names."""

    def __init__(self) -> None:
        from toolkit.config.constants import PATH_STRUCTURES
        from toolkit.features.configuration import ConfigurationManager

        self._cm = ConfigurationManager(SECRETS_ENV)
        self._dir = self._cm.project_root / PATH_STRUCTURES.CONFIG_SECRETS_DIR

    def show(self, path: str) -> Optional[str]:
        value = self._cm.get_secret_by_path(path)
        return str(value) if value else None

    def write(self, data: dict[str, str]) -> bool:
        # One file per write: a batch that landed in one file and failed in the
        # other would read as "nothing stored" while half of it was.
        files = {sops_file_for(path) for path in data}
        if len(files) != 1:
            raise ValueError(f"a write must target one SOPS file, not {sorted(files)}")
        return bool(self._cm.batch_update_secrets(data, secret_file_path=self._dir / f"{files.pop()}.enc.yaml"))


def mint_all(node: Optional[str] = None, rotate: bool = False) -> bool:
    """Mint every node's pair and password and the watcher's pair, or one node's. True iff all completed."""
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

    try:
        account_id, endpoint, legacy = str(r2["account_id"]), str(r2["endpoint"]), str(r2["bucket"])
    except KeyError as exc:
        logger.error(f"backup.r2.{exc.args[0]} is missing from the config SSOT")
        return False

    ok = True
    for name in [node] if node else nodes:
        others = [n for n in nodes if n != name]
        try:
            token = mint_node(
                name,
                account_id=account_id,
                endpoint=endpoint,
                other_bucket=node_bucket(others[0]) if others else legacy,
                http=http,
                store=store,
                run=_default_run,
                rotate=rotate,
            )
            password = ensure_restic_password(name, store)
        except MintError as exc:
            logger.error(f"{name}: {exc}")
            ok = False
            continue
        logger.success(f"{name}: token {token}, restic password {password}")

    if node is None:
        try:
            token = mint_watcher(
                nodes,
                account_id=account_id,
                endpoint=endpoint,
                legacy_bucket=legacy,
                http=http,
                store=store,
                run=_default_run,
                rotate=rotate,
            )
        except MintError as exc:
            logger.error(f"watcher: {exc}")
            return False
        logger.success(f"watcher: token {token}")
    return ok
