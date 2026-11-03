"""The product documents token: scoped to its bucket, proven, stored, never kept twice (STOR-002).

Driven with a fake Cloudflare API, a fake aws CLI and a fake SOPS store, the
shape of tests/test_terraform_state_bootstrap.py.
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from toolkit.features import backup_node_credentials as bnc
from toolkit.features import r2_documents_token as rdt
from toolkit.features.secrets_manager import SECRET_CATALOG

ACCOUNT = "acct"
REFUSED = "kubelab-backups"


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Optional[dict]]] = []

    def __call__(self, method: str, path: str, body: Optional[dict[str, Any]] = None) -> Any:
        self.calls.append((method, path, body))
        if path.endswith("/permission_groups"):
            return [{"name": bnc.WRITE_GROUP, "id": "g-write"}, {"name": bnc.READ_GROUP, "id": "g-read"}]
        if method == "POST" and path.endswith("/tokens"):
            return {"id": f"tok-{len(self.calls)}", "value": "token-value"}
        return None

    def created(self) -> list[dict]:
        return [b for m, p, b in self.calls if m == "POST" and p.endswith("/tokens") and b]

    def deleted(self) -> list[str]:
        return [p.rsplit("/", 1)[1] for m, p, _ in self.calls if m == "DELETE"]


class FakeStore:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})
        self.writes: list[dict[str, str]] = []

    def show(self, path: str) -> Optional[str]:
        return self.values.get(path)

    def write(self, data: dict[str, str]) -> bool:
        self.writes.append(dict(data))
        self.values.update(data)
        return True


def _scoped(argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
    bucket = argv[argv.index("--bucket") + 1]
    return (0, "", "") if bucket == rdt.DOCUMENTS_BUCKET else (254, "", "An error occurred (AccessDenied)")


def _mint(api: FakeApi, store: FakeStore, run=_scoped, rotate: bool = False) -> str:
    return rdt.mint(
        account_id=ACCOUNT,
        endpoint="https://r2.example",
        refused_bucket=REFUSED,
        http=api,
        store=store,
        run=run,
        rotate=rotate,
        sleep=lambda _: None,
    )


def test_the_token_is_object_read_write_on_the_documents_bucket_alone() -> None:
    api = FakeApi()
    assert _mint(api, FakeStore()) == "minted"
    (body,) = api.created()
    (policy,) = body["policies"]
    assert policy["permission_groups"] == [{"id": "g-write"}]
    assert list(policy["resources"]) == [bnc.bucket_resource(ACCOUNT, rdt.DOCUMENTS_BUCKET)]


def test_the_pair_is_stored_under_its_catalogued_keys_as_id_and_sha256() -> None:
    store = FakeStore()
    _mint(FakeApi(), store)
    (written,) = store.writes
    assert set(written) == {rdt.ACCESS_KEY_PATH, rdt.SECRET_KEY_PATH}
    assert written[rdt.SECRET_KEY_PATH] != "token-value"
    assert len(written[rdt.SECRET_KEY_PATH]) == 64


def test_an_existing_pair_is_kept_and_nothing_is_minted() -> None:
    api = FakeApi()
    store = FakeStore({rdt.ACCESS_KEY_PATH: "old", rdt.SECRET_KEY_PATH: "s"})
    assert _mint(api, store) == "kept"
    assert api.created() == [] and store.writes == []


def test_rotate_stores_the_new_pair_then_revokes_the_old_token() -> None:
    api = FakeApi()
    store = FakeStore({rdt.ACCESS_KEY_PATH: "old", rdt.SECRET_KEY_PATH: "s"})
    assert _mint(api, store, rotate=True) == "rotated"
    assert api.deleted() == ["old"]
    assert store.values[rdt.ACCESS_KEY_PATH] != "old"


def test_a_token_that_reaches_the_refused_bucket_is_revoked_and_nothing_is_stored() -> None:
    api, store = FakeApi(), FakeStore()
    with pytest.raises(bnc.MintError, match="must not reach"):
        _mint(api, store, run=lambda argv, env: (0, "", ""))
    assert store.writes == []
    assert len(api.deleted()) == 1


@pytest.mark.parametrize("path", [rdt.ACCESS_KEY_PATH, rdt.SECRET_KEY_PATH])
def test_both_halves_are_catalogued_for_prod_only(path: str) -> None:
    """Production only (#2535): staging needs no evidence store."""
    (spec,) = [s for s in SECRET_CATALOG if s.key_path == path]
    assert spec.envs == ("prod",)
