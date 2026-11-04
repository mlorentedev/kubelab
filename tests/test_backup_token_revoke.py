"""BACKUP-057 PR 5: retiring an R2 pair revokes its token before forgetting its id.

The token id is the pair's Access Key ID and lives only in SOPS. Unsetting the
keys first would leave a live token nobody can name, so the order is the
contract: revoke, prove it is gone, then unset.
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from toolkit.features.backup_node_credentials import MintError
from toolkit.features.backup_token_revoke import RevokeError, pair_paths, revoke_pair

PREFIX = "backup.r2.readonly_"
ACCESS = "backup.r2.readonly_access_key_id"
SECRET = "backup.r2.readonly_secret_access_key"
ACCOUNT = "acct"


class FakeStore:
    def __init__(self, files: dict[str, dict[str, str]], fail_unset: bool = False) -> None:
        self.files = files
        self.fail_unset = fail_unset
        self.unset_calls: list[tuple[str, str]] = []

    def files_holding(self, path: str) -> list[str]:
        return sorted(env for env, keys in self.files.items() if path in keys)

    def show(self, env: str, path: str) -> Optional[str]:
        return self.files.get(env, {}).get(path)

    def unset(self, env: str, path: str) -> bool:
        self.unset_calls.append((env, path))
        if self.fail_unset:
            return False
        self.files[env].pop(path, None)
        return True


class FakeCloudflare:
    def __init__(self, tokens: dict[str, str]) -> None:
        self.tokens = dict(tokens)  # id -> name
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method: str, path: str, body: Optional[dict[str, Any]] = None) -> Any:
        self.calls.append((method, path))
        token_id = path.rsplit("/", 1)[-1]
        if token_id not in self.tokens:
            raise MintError(f"{method} {path} returned HTTP 404", status=404)
        if method == "GET":
            return {"id": token_id, "name": self.tokens[token_id]}
        if method == "DELETE":
            del self.tokens[token_id]
            return {"id": token_id}
        raise AssertionError(method)


def _store() -> FakeStore:
    return FakeStore({"common": {ACCESS: "tok-1", SECRET: "s"}, "prod": {}})


def _run(store: FakeStore, cf: FakeCloudflare, **kw: Any) -> str:
    return revoke_pair(PREFIX, account_id=ACCOUNT, http=cf, store=store, catalog=frozenset(), **kw)


def test_without_apply_nothing_is_revoked_or_unset() -> None:
    store, cf = _store(), FakeCloudflare({"tok-1": "kubelab-backups-readonly"})
    assert _run(store, cf) == "planned"
    assert [m for m, _ in cf.calls] == ["GET"]
    assert store.unset_calls == []


def test_apply_revokes_then_proves_it_gone_then_unsets_both_keys() -> None:
    store, cf = _store(), FakeCloudflare({"tok-1": "kubelab-backups-readonly"})
    assert _run(store, cf, apply=True) == "revoked"
    assert [m for m, _ in cf.calls] == ["GET", "DELETE", "GET"]
    assert store.files["common"] == {}


def test_a_pair_still_in_the_catalog_is_refused_before_any_call() -> None:
    store, cf = _store(), FakeCloudflare({"tok-1": "x"})
    with pytest.raises(RevokeError, match="SECRET_CATALOG"):
        revoke_pair(PREFIX, account_id=ACCOUNT, http=cf, store=store, catalog=frozenset({ACCESS}), apply=True)
    assert cf.calls == [] and store.unset_calls == []


def test_an_absent_pair_is_a_no_op() -> None:
    store, cf = FakeStore({"common": {}, "prod": {}}), FakeCloudflare({})
    assert _run(store, cf, apply=True) == "absent"
    assert cf.calls == []


def test_a_token_cloudflare_does_not_know_keeps_the_keys() -> None:
    """It may be a user token, which this account endpoint cannot see: the id must survive."""
    store, cf = _store(), FakeCloudflare({})
    with pytest.raises(RevokeError, match="--forget"):
        _run(store, cf, apply=True)
    assert store.unset_calls == []


def test_forget_unsets_a_pair_whose_token_is_already_gone() -> None:
    store, cf = _store(), FakeCloudflare({})
    assert _run(store, cf, apply=True, forget=True) == "forgotten"
    assert [m for m, _ in cf.calls] == ["GET"]
    assert store.files["common"] == {}


def test_forget_never_skips_revoking_a_token_that_still_exists() -> None:
    store, cf = _store(), FakeCloudflare({"tok-1": "x"})
    assert _run(store, cf, apply=True, forget=True) == "revoked"
    assert "tok-1" not in cf.tokens


def test_a_secret_without_its_id_is_refused() -> None:
    store, cf = FakeStore({"common": {SECRET: "s"}}), FakeCloudflare({})
    with pytest.raises(RevokeError, match="dashboard"):
        _run(store, cf, apply=True)
    assert store.unset_calls == []


def test_a_failed_unset_is_reported_not_swallowed() -> None:
    store = FakeStore({"common": {ACCESS: "tok-1", SECRET: "s"}}, fail_unset=True)
    with pytest.raises(RevokeError, match="unset"):
        _run(store, FakeCloudflare({"tok-1": "x"}), apply=True)


def test_keys_in_several_files_are_unset_from_each() -> None:
    store = FakeStore({"common": {ACCESS: "tok-1", SECRET: "s"}, "prod": {ACCESS: "tok-1", SECRET: "s"}})
    assert _run(store, FakeCloudflare({"tok-1": "x"}), apply=True) == "revoked"
    assert store.files == {"common": {}, "prod": {}}


def test_errors_never_carry_the_token_id() -> None:
    store, cf = _store(), FakeCloudflare({})
    with pytest.raises(RevokeError) as exc:
        _run(store, cf, apply=True)
    assert "tok-1" not in str(exc.value)


def test_the_readonly_pair_is_no_longer_catalogued() -> None:
    """The guard is what makes the command safe; this pair passes it only because PR 5 removed its entries."""
    from toolkit.features.secrets_manager import SECRET_CATALOG

    catalogued = {s.key_path for s in SECRET_CATALOG}
    assert ACCESS not in catalogued and SECRET not in catalogued


def test_both_spellings_of_a_pair_resolve_to_the_keys_in_sops() -> None:
    assert pair_paths("backup.r2.readonly_") == (ACCESS, SECRET)
    assert pair_paths("backup.r2") == ("backup.r2.access_key_id", "backup.r2.secret_access_key")


def test_a_prefix_in_the_wrong_spelling_is_refused_not_reported_done() -> None:
    """`backup.r2.readonly` finds nothing; the pair is `backup.r2.readonly_*` and must not stay live silently."""
    store, cf = _store(), FakeCloudflare({"tok-1": "x"})
    with pytest.raises(RevokeError, match="PAIR=backup.r2.readonly_"):
        revoke_pair("backup.r2.readonly", account_id=ACCOUNT, http=cf, store=store, catalog=frozenset(), apply=True)
    assert cf.calls == [] and store.unset_calls == []


class _Unreachable(FakeCloudflare):
    def __init__(self, tokens: dict[str, str], fail_on: str, after: int = 0) -> None:
        super().__init__(tokens)
        self.fail_on, self.after = fail_on, after

    def __call__(self, method: str, path: str, body: Optional[dict[str, Any]] = None) -> Any:
        if method == self.fail_on and sum(m == method for m, _ in self.calls) >= self.after:
            self.calls.append((method, path))
            raise MintError(f"{method} {path} failed: timed out")
        return super().__call__(method, path, body)


def test_an_unreachable_api_on_delete_says_the_revoke_may_have_landed() -> None:
    store = _store()
    with pytest.raises(RevokeError, match="could not be reached.*may have landed") as exc:
        _run(store, _Unreachable({"tok-1": "x"}, "DELETE"), apply=True)
    assert "HTTP None" not in str(exc.value) and store.unset_calls == []


def test_a_failed_check_after_delete_keeps_the_keys_and_says_how_to_finish() -> None:
    store = _store()
    with pytest.raises(RevokeError, match="--forget"):
        _run(store, _Unreachable({"tok-1": "x"}, "GET", after=1), apply=True)
    assert store.unset_calls == []


def test_a_partial_unset_leaves_the_id_so_forget_can_finish() -> None:
    store = FakeStore({"common": {ACCESS: "tok-1", SECRET: "s"}})
    real_unset = store.unset

    def unset_secret_only(env: str, path: str) -> bool:
        return path != ACCESS and real_unset(env, path)

    store.unset = unset_secret_only  # type: ignore[method-assign]
    cf = FakeCloudflare({"tok-1": "x"})
    with pytest.raises(RevokeError, match="--forget"):
        _run(store, cf, apply=True)
    assert store.files["common"] == {ACCESS: "tok-1"}

    store.unset = real_unset  # type: ignore[method-assign]
    assert _run(store, cf, apply=True, forget=True) == "forgotten"
    assert store.files["common"] == {}


def test_an_undecryptable_sops_file_stops_the_run_before_anything_is_read() -> None:
    """`show_secret` reads an unreadable file as a missing key; this store must not."""
    from toolkit.features.backup_token_revoke import SopsPairStore

    def decrypt(env: str) -> Optional[dict[str, Any]]:
        if env == "prod":
            raise RevokeError("prod.enc.yaml exists but sops could not decrypt it")
        return {"backup": {"r2": {"readonly_access_key_id": "tok-1"}}} if env == "common" else None

    with pytest.raises(RevokeError, match="prod.enc.yaml"):
        SopsPairStore(decrypt=decrypt, unset=lambda env, path: True)


def test_the_sops_store_rereads_a_file_after_its_unset() -> None:
    from toolkit.features.backup_token_revoke import SopsPairStore

    files: dict[str, dict[str, Any]] = {"common": {"backup": {"r2": {"readonly_access_key_id": "tok-1"}}}}

    def unset(env: str, path: str) -> bool:
        files[env]["backup"]["r2"].pop(path.rsplit(".", 1)[-1], None)
        return True

    store = SopsPairStore(decrypt=lambda env: files.get(env), unset=unset)
    assert store.files_holding(ACCESS) == ["common"]
    assert store.unset("common", ACCESS)
    assert store.files_holding(ACCESS) == []
