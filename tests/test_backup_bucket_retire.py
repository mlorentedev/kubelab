"""Retiring an R2 bucket nothing reads (BACKUP-057 close-out, #1920).

The command deletes data for good, so every test here is about what it refuses
or what it proves before it reports success.
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from toolkit.features import backup_bucket_retire as bbr
from toolkit.features.backup_node_credentials import MintError, node_bucket

ACCOUNT, ENDPOINT, BUCKET = "acct", "https://acct.r2.cloudflarestorage.com", "kubelab-old"
PAIR = ("fixture-access", "fixture-secret")
CONFIG: dict[str, Any] = {
    "backup": {"sources": {"beelink": {}, "rpi3": {}}, "r2": {"account_id": ACCOUNT, "endpoint": ENDPOINT}}
}


def _listing(objects: int, size: int) -> str:
    return f"2026-10-01 00:00:00 1 x\n\nTotal Objects: {objects}\n   Total Size: {size}\n"


class FakeR2:
    """The bucket as both the Cloudflare API and the aws CLI see it."""

    def __init__(self, objects: int = 3, exists: bool = True) -> None:
        self.objects, self.exists = objects, exists
        self.calls: list[tuple[str, ...]] = []
        self.rm_leaves = 0
        self.delete_ignored = False
        self.get_status: Optional[int] = None

    def http(self, method: str, path: str, body: Optional[dict[str, Any]]) -> Any:
        self.calls.append((method, path))
        assert path == f"/accounts/{ACCOUNT}/r2/buckets/{BUCKET}"
        if method == "GET":
            if self.get_status:
                raise MintError("boom", status=self.get_status)
            if not self.exists:
                raise MintError("not found", status=404)
            return {}
        if method == "DELETE":
            assert self.objects == 0, "R2 refuses to delete a bucket that holds an object"
            self.exists = self.delete_ignored
            return {}
        raise AssertionError(method)

    def run(self, argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
        assert env["AWS_ACCESS_KEY_ID"] == PAIR[0]
        self.calls.append(tuple(argv[3:5]))
        if argv[3:5] == ["s3", "ls"]:
            return 0, _listing(self.objects, self.objects * 10), ""
        if argv[3:5] == ["s3", "rm"]:
            self.objects = self.rm_leaves
            return 0, "", ""
        raise AssertionError(argv)


def _retire(r2: FakeR2, bucket: str = BUCKET, config: dict[str, Any] = CONFIG, apply: bool = False) -> str:
    return bbr.retire_bucket(
        bucket, config=config, account_id=ACCOUNT, endpoint=ENDPOINT, pair=PAIR, http=r2.http, run=r2.run, apply=apply
    )


def test_a_dry_run_lists_and_deletes_nothing() -> None:
    r2 = FakeR2()
    assert _retire(r2) == "planned"
    assert ("DELETE", f"/accounts/{ACCOUNT}/r2/buckets/{BUCKET}") not in r2.calls
    assert ("s3", "rm") not in r2.calls


def test_apply_empties_deletes_and_reads_the_404_back() -> None:
    r2 = FakeR2()
    assert _retire(r2, apply=True) == "retired"
    assert r2.calls[-1] == ("GET", f"/accounts/{ACCOUNT}/r2/buckets/{BUCKET}")
    assert not r2.exists


def test_an_absent_bucket_is_nothing_to_do() -> None:
    r2 = FakeR2(exists=False)
    assert _retire(r2, apply=True) == "absent"
    assert r2.calls == [("GET", f"/accounts/{ACCOUNT}/r2/buckets/{BUCKET}")]


def test_an_empty_bucket_is_deleted_without_an_rm() -> None:
    r2 = FakeR2(objects=0)
    assert _retire(r2, apply=True) == "retired"
    assert ("s3", "rm") not in r2.calls


@pytest.mark.parametrize("node", ["beelink", "rpi3"])
def test_a_nodes_bucket_is_refused_before_anything_is_asked(node: str) -> None:
    r2 = FakeR2()
    with pytest.raises(bbr.RetireError, match="backup.sources"):
        _retire(r2, bucket=node_bucket(node), apply=True)
    assert r2.calls == []


@pytest.mark.parametrize(
    "where",
    [
        {"apps": {"x": {"bucket": BUCKET}}},
        {"apps": {"x": {"repo": f"s3:{ENDPOINT}/{BUCKET}/rpi3"}}},
        {"apps": {"x": [f"{BUCKET}"]}},
    ],
)
def test_a_bucket_the_config_still_names_is_refused(where: dict[str, Any]) -> None:
    r2 = FakeR2()
    with pytest.raises(bbr.RetireError, match="config still names"):
        _retire(r2, config={**CONFIG, **where}, apply=True)
    assert r2.calls == []


@pytest.mark.parametrize("other", [f"{BUCKET}-staging", f"x-{BUCKET}", f"{BUCKET}s"])
def test_a_longer_name_that_contains_it_is_not_a_reference(other: str) -> None:
    assert bbr.config_names({"a": other}, BUCKET) is False


def test_objects_left_after_the_rm_keep_the_bucket() -> None:
    r2 = FakeR2()
    r2.rm_leaves = 2
    with pytest.raises(bbr.RetireError, match="still holds 2 objects"):
        _retire(r2, apply=True)
    assert not [c for c in r2.calls if c[0] == "DELETE"]


def test_a_delete_that_did_not_take_is_a_failure() -> None:
    r2 = FakeR2()
    r2.delete_ignored = True
    with pytest.raises(bbr.RetireError, match="still answers"):
        _retire(r2, apply=True)


def test_a_read_that_is_not_a_404_is_not_taken_for_absence() -> None:
    r2 = FakeR2()
    r2.get_status = 403
    with pytest.raises(bbr.RetireError, match="reading"):
        _retire(r2, apply=True)


def test_a_listing_without_totals_is_refused() -> None:
    r2 = FakeR2()
    r2.run = lambda argv, env: (0, "nothing useful\n", "")  # type: ignore[method-assign]
    with pytest.raises(bbr.RetireError, match="no totals"):
        _retire(r2)


def test_the_make_target_reaches_the_command() -> None:
    from pathlib import Path

    makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("\nbackup-retire-bucket:", 1)[1].split("\n\n", 1)[0]
    assert "backup retire-bucket" in recipe
    assert "--bucket" in recipe and "--pair" in recipe
