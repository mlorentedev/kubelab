"""Per-node R2 credentials and restic passwords (BACKUP-057 PR 3, AC1).

What this file pins:

- the catalog declares a key pair and a restic password for every
  `backup.sources` node, and no two nodes share a SOPS path, so a node added to
  the SSOT is audited from the start;
- `mint-node-tokens` writes the S3 pair a minted token yields (the token id, and
  the SHA-256 of its value) and never prints either;
- it is idempotent: an existing pair is kept unless `--rotate` is given, and a
  rotation revokes the token it replaces;
- a minted token that cannot list its own bucket, or that can list another
  node's, is revoked and nothing is written;
- a restic password is generated when absent and never replaced, `--rotate` or
  not: replacing it locks the node out of its own repository.
"""

from __future__ import annotations

import hashlib
import pathlib
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest
import yaml

from toolkit.features import backup_node_credentials as bnc
from toolkit.features.secrets_manager import SECRET_CATALOG

REPO = pathlib.Path(__file__).resolve().parent.parent
COMMON = REPO / "infra" / "config" / "values" / "common.yaml"

ACCOUNT = "acct0123"
ENDPOINT = "https://acct0123.r2.cloudflarestorage.com"
WRITE_GROUP_ID = "pg-write"
READ_GROUP_ID = "pg-read"


def _nodes() -> list[str]:
    return sorted(yaml.safe_load(COMMON.read_text(encoding="utf-8"))["backup"]["sources"])


def _node_paths(node: str) -> set[str]:
    return {bnc.access_key_path(node), bnc.secret_key_path(node), bnc.restic_password_path(node)}


class FakeHttp:
    """The Cloudflare API, recording every call. Token values are unique per mint."""

    def __init__(self, groups: Optional[list[dict[str, str]]] = None) -> None:
        self.calls: list[tuple[str, str, Optional[dict[str, Any]]]] = []
        self.groups = (
            groups
            if groups is not None
            else [
                {"id": WRITE_GROUP_ID, "name": bnc.WRITE_GROUP},
                {"id": READ_GROUP_ID, "name": "Workers R2 Storage Bucket Item Read"},
            ]
        )
        self.minted = 0

    def __call__(self, method: str, path: str, body: Optional[dict[str, Any]] = None) -> Any:
        self.calls.append((method, path, body))
        if method == "GET" and path.endswith("/tokens/permission_groups"):
            return self.groups
        if method == "POST" and path.endswith("/tokens"):
            self.minted += 1
            return {"id": f"tok-{self.minted}", "value": f"VALUE-{self.minted}-do-not-print"}
        if method == "DELETE":
            return {"id": path.rsplit("/", 1)[-1]}
        raise AssertionError(f"unexpected call {method} {path}")

    def posts(self) -> list[dict[str, Any]]:
        return [body for method, _, body in self.calls if method == "POST" and body is not None]

    def deletes(self) -> list[str]:
        return [path.rsplit("/", 1)[-1] for method, path, _ in self.calls if method == "DELETE"]


class FakeStore:
    """SOPS, as a dict. `writes` records each batch so a test can count decrypts."""

    def __init__(self, values: Optional[dict[str, str]] = None, fail_writes: bool = False) -> None:
        self.values = dict(values or {})
        self.writes: list[dict[str, str]] = []
        self.fail_writes = fail_writes

    def show(self, path: str) -> Optional[str]:
        return self.values.get(path)

    def write(self, data: dict[str, str]) -> bool:
        if self.fail_writes:
            return False
        self.writes.append(dict(data))
        self.values.update(data)
        return True


def _scope_runner(own_ok: bool = True, other_ok: bool = False, other_error: str = "AccessDenied"):
    """The aws CLI: listing the token's own bucket and another node's."""
    seen: list[list[str]] = []

    def run(argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
        seen.append(argv)
        bucket = argv[argv.index("--bucket") + 1]
        own = bucket == env["_OWN_BUCKET_FOR_TEST"]
        ok = own_ok if own else other_ok
        error = "AccessDenied" if own else other_error
        return (0, "{}", "") if ok else (254, "", f"An error occurred ({error})")

    run.seen = seen  # type: ignore[attr-defined]
    return run


def _mint(node: str, store: FakeStore, http: FakeHttp, run=None, rotate: bool = False) -> str:
    run = run or _scope_runner()

    def run_with_marker(argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
        return run(argv, {**env, "_OWN_BUCKET_FOR_TEST": bnc.node_bucket(node)})

    return bnc.mint_node(
        node,
        account_id=ACCOUNT,
        endpoint=ENDPOINT,
        other_bucket=bnc.node_bucket("othernode"),
        http=http,
        store=store,
        run=run_with_marker,
        rotate=rotate,
        sleep=lambda _s: None,
    )


class TestTheCatalogCoversEveryNode:
    def test_every_backup_source_has_its_pair_and_password_registered(self) -> None:
        registered = {spec.key_path for spec in SECRET_CATALOG}
        for node in _nodes():
            assert _node_paths(node) <= registered, f"{node} is missing from SECRET_CATALOG"

    def test_no_two_nodes_share_a_sops_path(self) -> None:
        nodes = _nodes()
        paths = [path for node in nodes for path in _node_paths(node)]
        assert len(paths) == len(set(paths)) == 3 * len(nodes)

    def test_a_write_pair_is_audited_in_prod_and_a_password_in_both_envs(self) -> None:
        by_path = {spec.key_path: spec for spec in SECRET_CATALOG}
        for node in _nodes():
            assert by_path[bnc.access_key_path(node)].envs == ("prod",)
            assert by_path[bnc.secret_key_path(node)].envs == ("prod",)
            assert by_path[bnc.restic_password_path(node)].envs == ("staging", "prod")

    def test_every_minted_key_lives_where_every_env_auditing_it_can_read_it(self) -> None:
        """Staging decrypts common and staging, never prod. A key staging audits
        that was written to prod.enc.yaml would be missing there, and silently."""
        by_path = {spec.key_path: spec for spec in SECRET_CATALOG}
        paths = [p for node in _nodes() for p in _node_paths(node)]
        paths += [bnc.WATCHER_ACCESS_KEY_PATH, bnc.WATCHER_SECRET_KEY_PATH]
        for path in paths:
            expected = "common" if "staging" in by_path[path].envs else "prod"
            assert bnc.sops_file_for(path) == expected, path

    def test_the_watcher_pair_and_the_minter_are_registered(self) -> None:
        by_path = {spec.key_path: spec for spec in SECRET_CATALOG}
        assert by_path[bnc.WATCHER_ACCESS_KEY_PATH].envs == ("staging", "prod")
        assert by_path[bnc.WATCHER_SECRET_KEY_PATH].envs == ("staging", "prod")
        assert by_path[bnc.MINTER_KEY].envs == ("prod",)

    def test_a_key_this_module_does_not_mint_has_no_file(self) -> None:
        with pytest.raises(ValueError):
            bnc.sops_file_for("backup.restic_password")

    def test_the_catalog_names_no_node_outside_backup_sources(self) -> None:
        declared = {
            spec.key_path.split(".")[-2]
            for spec in SECRET_CATALOG
            if spec.key_path.startswith(("backup.r2.nodes.", "backup.nodes."))
        }
        assert declared == set(_nodes())


class TestMinting:
    def test_an_absent_pair_is_minted_as_token_id_and_sha256_of_its_value(self) -> None:
        store, http = FakeStore(), FakeHttp()
        assert _mint("vps", store, http) == "minted"
        assert store.values[bnc.access_key_path("vps")] == "tok-1"
        assert store.values[bnc.secret_key_path("vps")] == hashlib.sha256(b"VALUE-1-do-not-print").hexdigest()

    def test_the_pair_is_written_in_one_batch(self) -> None:
        store = FakeStore()
        _mint("vps", store, FakeHttp())
        assert store.writes == [
            {
                bnc.access_key_path("vps"): "tok-1",
                bnc.secret_key_path("vps"): hashlib.sha256(b"VALUE-1-do-not-print").hexdigest(),
            }
        ]

    def test_neither_half_reaches_any_output(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """capsys alone cannot see loguru, whose sink holds the original stderr,
        so the logger is replaced with a recorder. Both the success path and a
        refused mint are exercised: an error message is output too."""
        log = MagicMock()
        monkeypatch.setattr(bnc, "logger", log)
        _mint("vps", FakeStore(), FakeHttp())
        with pytest.raises(bnc.MintError) as refused:
            _mint("vps", FakeStore(), FakeHttp(), run=_scope_runner(other_ok=True))
        out = capsys.readouterr()
        for n in (1, 2):
            value = f"VALUE-{n}-do-not-print"
            secret = hashlib.sha256(value.encode()).hexdigest()
            for text in (out.out, out.err, str(log.mock_calls), str(refused.value)):
                assert value not in text
                assert secret not in text

    def test_an_existing_pair_is_kept_and_the_api_is_not_called(self) -> None:
        store = FakeStore({bnc.access_key_path("vps"): "tok-old", bnc.secret_key_path("vps"): "s-old"})
        http = FakeHttp()
        assert _mint("vps", store, http) == "kept"
        assert http.calls == []
        assert store.writes == []

    def test_rotate_mints_a_new_pair_and_revokes_the_old_token(self) -> None:
        store = FakeStore({bnc.access_key_path("vps"): "tok-old", bnc.secret_key_path("vps"): "s-old"})
        http = FakeHttp()
        assert _mint("vps", store, http, rotate=True) == "rotated"
        assert store.values[bnc.access_key_path("vps")] == "tok-1"
        assert http.deletes() == ["tok-old"]

    def test_the_old_token_is_revoked_only_after_the_new_pair_is_written(self) -> None:
        store = FakeStore(
            {bnc.access_key_path("vps"): "tok-old", bnc.secret_key_path("vps"): "s-old"}, fail_writes=True
        )
        http = FakeHttp()
        with pytest.raises(bnc.MintError):
            _mint("vps", store, http, rotate=True)
        assert "tok-old" not in http.deletes()
        assert http.deletes() == ["tok-1"], "the token whose pair was never stored must not be left behind"

    def test_a_missing_permission_group_stops_the_mint(self) -> None:
        http = FakeHttp(groups=[{"id": "x", "name": "Something Else"}])
        with pytest.raises(bnc.MintError, match=bnc.WRITE_GROUP):
            _mint("vps", FakeStore(), http)
        assert http.posts() == []


class TestVerifiedByConsequence:
    def test_a_token_that_cannot_list_its_own_bucket_is_revoked_and_not_stored(self) -> None:
        store, http = FakeStore(), FakeHttp()
        with pytest.raises(bnc.MintError, match="which it was minted for"):
            _mint("vps", store, http, run=_scope_runner(own_ok=False))
        assert store.writes == []
        assert http.deletes() == ["tok-1"]

    def test_a_token_that_can_list_another_nodes_bucket_is_revoked_and_not_stored(self) -> None:
        store, http = FakeStore(), FakeHttp()
        with pytest.raises(bnc.MintError, match="must not reach"):
            _mint("vps", store, http, run=_scope_runner(other_ok=True))
        assert store.writes == []
        assert http.deletes() == ["tok-1"]

    def test_another_bucket_that_fails_without_access_denied_proves_nothing(self) -> None:
        """A missing bucket fails the listing too. Only AccessDenied is a refusal."""
        store, http = FakeStore(), FakeHttp()
        with pytest.raises(bnc.MintError, match="unproven"):
            _mint("vps", store, http, run=_scope_runner(other_error="NoSuchBucket"))
        assert store.writes == []
        assert http.deletes() == ["tok-1"]

    def test_the_check_uses_the_minted_pair(self) -> None:
        envs: list[dict[str, str]] = []

        def run(argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
            envs.append(env)
            own = argv[argv.index("--bucket") + 1] == bnc.node_bucket("vps")
            return (0, "{}", "") if own else (254, "", "AccessDenied")

        _mint("vps", FakeStore(), FakeHttp(), run=run)
        assert envs and all(e["AWS_ACCESS_KEY_ID"] == "tok-1" for e in envs)
        assert all(e["AWS_SECRET_ACCESS_KEY"] == hashlib.sha256(b"VALUE-1-do-not-print").hexdigest() for e in envs)


class TestResticPasswords:
    def test_an_absent_password_is_generated(self) -> None:
        store = FakeStore()
        assert bnc.ensure_restic_password("vps", store) == "generated"
        assert len(store.values[bnc.restic_password_path("vps")]) >= 48

    def test_an_existing_password_is_never_replaced(self) -> None:
        store = FakeStore({bnc.restic_password_path("vps"): "keep-me"})
        assert bnc.ensure_restic_password("vps", store) == "kept"
        assert store.values[bnc.restic_password_path("vps")] == "keep-me"
        assert store.writes == []

    def test_rotate_does_not_reach_the_restic_password(self) -> None:
        """`mint_all(rotate=True)` rotates tokens. It has no path to a password."""
        assert "rotate" not in bnc.ensure_restic_password.__code__.co_varnames


def _watcher_runner(legacy: str, legacy_ok: bool = False, legacy_error: str = "AccessDenied", unreadable: str = ""):
    def run(argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
        bucket = argv[argv.index("--bucket") + 1]
        if bucket == legacy:
            return (0, "{}", "") if legacy_ok else (254, "", f"An error occurred ({legacy_error})")
        if bucket == unreadable:
            return (254, "", "An error occurred (AccessDenied)")
        return (0, "{}", "")

    return run


def _mint_watcher(store: FakeStore, http: FakeHttp, run, rotate: bool = False) -> str:
    return bnc.mint_watcher(
        _nodes(),
        account_id=ACCOUNT,
        endpoint=ENDPOINT,
        legacy_bucket="kubelab-backups",
        http=http,
        store=store,
        run=run,
        rotate=rotate,
        sleep=lambda _s: None,
    )


class TestTheWatcherToken:
    def test_it_is_minted_read_only_on_every_node_bucket(self) -> None:
        store, http = FakeStore(), FakeHttp()
        assert _mint_watcher(store, http, _watcher_runner("kubelab-backups")) == "minted"
        (body,) = http.posts()
        assert body["policies"][0]["permission_groups"] == [{"id": READ_GROUP_ID}]
        assert store.values[bnc.WATCHER_ACCESS_KEY_PATH] == "tok-1"

    def test_a_token_that_reads_the_legacy_bucket_is_revoked(self) -> None:
        store, http = FakeStore(), FakeHttp()
        with pytest.raises(bnc.MintError, match="must not reach"):
            _mint_watcher(store, http, _watcher_runner("kubelab-backups", legacy_ok=True))
        assert store.writes == [] and http.deletes() == ["tok-1"]

    def test_a_token_that_misses_one_node_bucket_is_revoked(self) -> None:
        store, http = FakeStore(), FakeHttp()
        missing = bnc.node_bucket(_nodes()[-1])
        with pytest.raises(bnc.MintError, match=missing):
            _mint_watcher(store, http, _watcher_runner("kubelab-backups", unreadable=missing))
        assert store.writes == [] and http.deletes() == ["tok-1"]

    def test_an_existing_pair_is_kept(self) -> None:
        store = FakeStore({bnc.WATCHER_ACCESS_KEY_PATH: "tok-old", bnc.WATCHER_SECRET_KEY_PATH: "s-old"})
        http = FakeHttp()
        assert _mint_watcher(store, http, _watcher_runner("kubelab-backups")) == "kept"
        assert http.calls == []
