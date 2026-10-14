"""The state bucket, its history lock and its token are made once and kept (TF-007).

Driven with a fake Cloudflare API and a fake aws CLI: what is asserted is which
calls are made, in what order, and that a second run makes none that write.
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from toolkit.features import backup_node_credentials as bnc
from toolkit.features import terraform_state_bootstrap as tsb

ACCOUNT = "acct"
BUCKET = "kubelab-tfstate"
RULE = tsb.lock_rule("history/", 365)


class FakeApi:
    def __init__(self, buckets: list[str] | None = None, rules: list[dict] | None = None) -> None:
        self.buckets = list(buckets or [])
        self.rules = list(rules or [])
        self.calls: list[tuple[str, str, Optional[dict]]] = []

    def __call__(self, method: str, path: str, body: Optional[dict[str, Any]] = None) -> Any:
        self.calls.append((method, path, body))
        if path.endswith("/lock"):
            if method == "PUT":
                self.rules = list((body or {})["rules"])
                return None
            return {"rules": self.rules}
        if "/r2/buckets" in path:
            if method == "POST":
                self.buckets.append((body or {})["name"])
                return None
            return {"buckets": [{"name": b} for b in self.buckets]}
        if path.endswith("/permission_groups"):
            return [{"name": bnc.WRITE_GROUP, "id": "g-write"}]
        if method == "POST" and path.endswith("/tokens"):
            return {"id": "tok-1", "value": "token-value"}
        return None

    def writes(self) -> list[tuple[str, str]]:
        return [(m, p) for m, p, _ in self.calls if m != "GET"]


def test_a_missing_bucket_is_created_and_an_existing_one_kept() -> None:
    api = FakeApi()
    assert tsb.ensure_bucket(api, ACCOUNT, BUCKET) == "created"
    assert tsb.ensure_bucket(api, ACCOUNT, BUCKET) == "kept"
    assert api.writes() == [("POST", f"/accounts/{ACCOUNT}/r2/buckets")]


def test_a_bucket_whose_name_only_contains_ours_is_not_ours() -> None:
    api = FakeApi(buckets=["kubelab-tfstate-scratch"])
    assert tsb.ensure_bucket(api, ACCOUNT, BUCKET) == "created"


def test_the_lock_rule_retains_history_for_the_declared_days() -> None:
    assert RULE == {
        "id": "terraform-state-history",
        "enabled": True,
        "prefix": "history/",
        "condition": {"type": "Age", "maxAgeSeconds": 365 * 86400},
    }


def test_the_lock_rule_is_set_once_then_kept() -> None:
    api = FakeApi()
    assert tsb.ensure_lock(api, ACCOUNT, BUCKET, RULE) == "set"
    assert tsb.ensure_lock(api, ACCOUNT, BUCKET, RULE) == "kept"
    assert [m for m, _ in api.writes()] == ["PUT"]


def test_extra_fields_the_api_returns_do_not_make_the_rule_differ() -> None:
    """A GET that echoes more than was PUT must not cause a PUT on every run."""
    api = FakeApi(rules=[{**RULE, "condition": {**RULE["condition"], "extra": 1}, "createdAt": "x"}])
    assert tsb.ensure_lock(api, ACCOUNT, BUCKET, RULE) == "kept"
    assert api.writes() == []


def test_a_drifted_rule_is_replaced_and_other_rules_are_kept() -> None:
    other = {"id": "someone-else", "enabled": True, "prefix": "x/", "condition": {"type": "Indefinite"}}
    api = FakeApi(rules=[other, {**RULE, "condition": {"type": "Age", "maxAgeSeconds": 60}}])
    assert tsb.ensure_lock(api, ACCOUNT, BUCKET, RULE) == "set"
    assert api.rules == [other, RULE]


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


def _run_scoped(argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
    """The state bucket lists; any other bucket is refused."""
    bucket = argv[argv.index("--bucket") + 1]
    return (0, "", "") if bucket == BUCKET else (254, "", "An error occurred (AccessDenied)")


def _mint(api: FakeApi, store: FakeStore, run=_run_scoped, rotate: bool = False) -> str:
    return tsb.mint_state_token(
        account_id=ACCOUNT,
        endpoint="https://r2.example",
        bucket=BUCKET,
        refused_bucket="kubelab-backups",
        http=api,
        store=store,
        run=run,
        rotate=rotate,
        sleep=lambda _: None,
    )


def test_the_token_reaches_the_state_bucket_only_and_is_stored_as_its_pair() -> None:
    api, store = FakeApi(), FakeStore()
    assert _mint(api, store) == "minted"
    [(_, _, body)] = [c for c in api.calls if c[0] == "POST" and c[1].endswith("/tokens")]
    [policy] = body["policies"]
    assert list(policy["resources"]) == [bnc.bucket_resource(ACCOUNT, BUCKET)]
    assert policy["permission_groups"] == [{"id": "g-write"}]
    assert store.writes == [{tsb.ACCESS_KEY_PATH: "tok-1", tsb.SECRET_KEY_PATH: store.values[tsb.SECRET_KEY_PATH]}]


def test_a_token_that_reaches_the_backups_is_revoked_and_nothing_stored() -> None:
    api, store = FakeApi(), FakeStore()
    with pytest.raises(bnc.MintError, match="must not reach"):
        _mint(api, store, run=lambda argv, env: (0, "", ""))
    assert store.writes == []
    assert ("DELETE", f"/accounts/{ACCOUNT}/tokens/tok-1") in api.writes()


def test_a_stored_pair_is_kept_unless_rotating() -> None:
    api = FakeApi()
    store = FakeStore({tsb.ACCESS_KEY_PATH: "old", tsb.SECRET_KEY_PATH: "s"})
    assert _mint(api, store) == "kept"
    assert api.calls == []
    assert _mint(api, store, rotate=True) == "rotated"
    assert ("DELETE", f"/accounts/{ACCOUNT}/tokens/old") in api.writes()


def test_the_pair_goes_to_the_file_the_runner_reads(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """The runner merges common.enc.yaml; a pair in prod.enc.yaml would be invisible to it."""
    seen: dict[str, Any] = {}

    class Cm:
        def batch_update_secrets(self, data: dict[str, str], secret_file_path: Any) -> bool:
            seen.update(data=data, file=secret_file_path)
            return True

    store = tsb.CommonStore.__new__(tsb.CommonStore)
    store._cm, store._dir = Cm(), tmp_path  # type: ignore[assignment]
    assert store.write({tsb.ACCESS_KEY_PATH: "k"})
    assert seen["file"] == tmp_path / "common.enc.yaml"


def test_the_r2_run_seam_drops_the_shells_aws_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    """A session token sent with an R2 pair makes R2 refuse it, which reads as a wrong key."""
    from toolkit.features import backup_destination

    captured: dict[str, Any] = {}

    class Proc:
        returncode, stdout, stderr = 0, "", ""

    def fake_run(argv: list[str], **kwargs: Any) -> Proc:
        captured.update(kwargs["env"])
        return Proc()

    monkeypatch.setenv("AWS_SESSION_TOKEN", "stale")
    monkeypatch.setenv("AWS_PROFILE", "someone-else")
    monkeypatch.setattr(backup_destination.subprocess, "run", fake_run)
    backup_destination._default_run(["aws", "s3api", "list-buckets"], {"AWS_ACCESS_KEY_ID": "k"})
    assert captured["AWS_ACCESS_KEY_ID"] == "k"
    assert "AWS_SESSION_TOKEN" not in captured and "AWS_PROFILE" not in captured
