"""Retire an R2 S3 pair: revoke its token, prove it is gone, then forget the pair.

An R2 pair's Access Key ID is the id of the Cloudflare token behind it, and that
id is stored nowhere but SOPS. So the order is the whole contract: unsetting the
keys first leaves a live token that nobody can name any more, which is the one
outcome this exists to prevent. Revocation goes through the minter, the same
credential and endpoint `backup_node_credentials` revokes with.

Only a pair that SECRET_CATALOG no longer owns may be retired: a catalogued key
is one something still reads, and revoking it is an outage, not a cleanup.

Nothing here prints a value or a token id. The token's name, which Cloudflare
returns and is not a secret, is what the operator sees.
"""

from __future__ import annotations

from typing import Optional, Protocol

from toolkit.core.logging import logger
from toolkit.features.backup_node_credentials import MINTER_KEY, SECRETS_ENV, HttpFn, MintError, cloudflare_http

# The SOPS files a pair can live in, read file by file: a copy in one file that
# the merged view hides behind another would survive an unset of the visible one.
SOPS_FILES = ("common", "staging", "prod")


class RevokeError(RuntimeError):
    """A retirement did not complete. The message never contains a value or a token id."""


class PairStore(Protocol):
    def files_holding(self, path: str) -> list[str]: ...

    def show(self, env: str, path: str) -> Optional[str]: ...

    def unset(self, env: str, path: str) -> bool: ...


def pair_paths(prefix: str) -> tuple[str, str]:
    """The pair's two key paths. A prefix ending in `_` is joined as is, any other with a dot.

    Both spellings exist: `backup.r2.access_key_id` (prefix `backup.r2`) and
    `backup.r2.readonly_access_key_id` (prefix `backup.r2.readonly_`).
    """
    sep = "" if prefix.endswith(("_", ".")) else "."
    return f"{prefix}{sep}access_key_id", f"{prefix}{sep}secret_access_key"


def _token_name(http: HttpFn, account_id: str, token_id: str) -> Optional[str]:
    """The token's name, or None when the account has no token with that id."""
    try:
        result = http("GET", f"/accounts/{account_id}/tokens/{token_id}", None) or {}
    except MintError as exc:
        if exc.status == 404:
            return None
        raise RevokeError(f"reading the token failed with HTTP {exc.status}") from None
    return str(result.get("name") or "(unnamed)")


def revoke_pair(
    prefix: str,
    *,
    account_id: str,
    http: HttpFn,
    store: PairStore,
    catalog: frozenset[str],
    apply: bool = False,
    forget: bool = False,
) -> str:
    """Retire `<prefix>.access_key_id` / `.secret_access_key`. Returns absent/planned/revoked/forgotten.

    `forget` unsets a pair whose token the account no longer has (revoked by an
    earlier run that failed before its unset, or in the dashboard). It never
    skips revoking a token that still exists.
    """
    access, secret = pair_paths(prefix)
    owned = sorted({access, secret} & catalog)
    if owned:
        raise RevokeError(
            f"{', '.join(owned)} is in SECRET_CATALOG, so something still reads it. "
            "Remove the consumer and its entry first."
        )

    holding = {path: store.files_holding(path) for path in (access, secret)}
    if not holding[access] and not holding[secret]:
        return "absent"
    if not holding[access]:
        raise RevokeError(
            f"{secret} is in SOPS without {access}: the token id is gone, so it cannot be revoked from here. "
            f"Find the token in the Cloudflare dashboard, revoke it there, then unset {secret}."
        )

    ids = {store.show(env, access) for env in holding[access]}
    if len(ids) != 1 or not next(iter(ids)):
        raise RevokeError(f"{access} differs between {', '.join(holding[access])}; refusing to pick one")
    token_id = str(ids.pop())

    name = _token_name(http, account_id, token_id)
    if name is None and not forget:
        raise RevokeError(
            f"the account has no token with the id in {access}: it was revoked already, or it is a user token "
            "this endpoint cannot see. Nothing was unset. Confirm in the dashboard that it is gone, then pass --forget."
        )

    where = ", ".join(sorted({env for envs in holding.values() for env in envs}))
    if not apply:
        action = f"revoke token {name!r} and unset" if name else "unset (token already gone)"
        logger.info(f"{prefix}: would {action} both keys from {where}. Pass --apply to do it.")
        return "planned"

    if name is not None:
        try:
            http("DELETE", f"/accounts/{account_id}/tokens/{token_id}", None)
        except MintError as exc:
            raise RevokeError(f"revoking token {name!r} failed with HTTP {exc.status}; nothing was unset") from None
        # By consequence: the account must no longer know the id. Until then the
        # id is the only handle on a live token, so it stays in SOPS.
        if _token_name(http, account_id, token_id) is not None:
            raise RevokeError(f"token {name!r} still exists after DELETE; nothing was unset")
        logger.success(f"{prefix}: token {name!r} revoked")

    for path, envs in holding.items():
        for env in envs:
            if not store.unset(env, path):
                raise RevokeError(f"unset of {path} from {env}.enc.yaml failed; rerun with --forget to finish")
    left = [path for path in (access, secret) if store.files_holding(path)]
    if left:
        raise RevokeError(f"{', '.join(left)} is still in SOPS after its unset")
    logger.success(f"{prefix}: both keys unset from {where}")
    return "revoked" if name is not None else "forgotten"


class SopsPairStore:
    """Reads and unsets one key in one SOPS file at a time, through SecretsManager."""

    def __init__(self) -> None:
        from toolkit.features.secrets_manager import SecretsManager

        self._sm = SecretsManager()

    def files_holding(self, path: str) -> list[str]:
        return [env for env in SOPS_FILES if self._sm.show_secret(env, path)]

    def show(self, env: str, path: str) -> Optional[str]:
        return self._sm.show_secret(env, path)

    def unset(self, env: str, path: str) -> bool:
        return self._sm.unset_secret(env, path)


def revoke_pair_cmd(prefix: str, *, apply: bool, forget: bool) -> bool:
    """The CLI entry point: real SOPS, the real minter, the real catalog. True iff it completed."""
    from toolkit.features.configuration import ConfigurationManager
    from toolkit.features.secrets_manager import SECRET_CATALOG

    cm = ConfigurationManager(SECRETS_ENV)
    account_id = str(((cm.get_merged_config().get("backup") or {}).get("r2") or {}).get("account_id") or "")
    minter = cm.get_secret_by_path(MINTER_KEY)
    if not account_id or not minter:
        logger.error(f"backup.r2.account_id and {MINTER_KEY} are both needed to revoke a token")
        return False
    try:
        outcome = revoke_pair(
            prefix,
            account_id=account_id,
            http=cloudflare_http(str(minter)),
            store=SopsPairStore(),
            catalog=frozenset(s.key_path for s in SECRET_CATALOG),
            apply=apply,
            forget=forget,
        )
    except RevokeError as exc:
        logger.error(f"{prefix}: {exc}")
        return False
    if outcome == "absent":
        access, secret = pair_paths(prefix)
        logger.success(f"neither {access} nor {secret} is in any SOPS file; nothing to do")
    return True
