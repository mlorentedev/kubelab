"""`make backup-isolation-probe` fails on any request R2 accepts that it must refuse (BACKUP-057 AC1, AC3).

Every other check passes against today's shared bucket, so this one has to be
able to fail. R2 is faked by a world of buckets, each reachable by one key pair
and optionally locked. What is asserted is that an accepted request fails the
probe, that a refusal for the wrong reason proves nothing, and that an empty
`data/` prefix is a failure rather than an immutability nobody measured.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Any

import pytest

from toolkit.features import backup_isolation as bi
from toolkit.features.backup_node_credentials import access_key_path, secret_key_path
from toolkit.features.r2_tfvars import node_bucket

REPO = pathlib.Path(__file__).resolve().parents[1]
ENDPOINT = "https://acct.r2.cloudflarestorage.com"
NODES = ["beelink", "rpi3", "rpi4", "vps"]
DENIED = "An error occurred (AccessDenied) when calling the {op} operation: Access Denied"
R = 30 * 86400
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
LOCKED = (
    "An error occurred (ObjectLockedByBucketPolicy) when calling the DeleteObject operation: "
    "The object is locked by the bucket policy."
)


class R2:
    """Buckets, which key ids reach each one, and which are locked. Records every request."""

    def __init__(self) -> None:
        self.objects: dict[str, list[dict[str, str]]] = {
            node_bucket(n): [
                {"Key": f"data/{n}-b", "LastModified": "2026-10-07T03:00:00+00:00"},
                {"Key": f"data/{n}-a", "LastModified": "2026-10-07T04:00:00+00:00"},
                {"Key": f"data/{n}-c", "LastModified": "2026-10-01T00:00:00+00:00"},
            ]
            for n in NODES
        }
        self.reach: dict[str, set[str]] = {node_bucket(n): {f"{n}-id"} for n in NODES}
        self.locked: set[str] = set(self.objects)
        self.requests: list[tuple[str, str, str, str]] = []  # (op, bucket, key, key id)
        self.deleted: list[tuple[str, str]] = []
        self.override: dict[tuple[str, str, str], tuple[int, str, str]] = {}
        # What the lock API reports per bucket: Terraform's four rules, or an exception to raise.
        self.rules: dict[str, Any] = {
            b: [
                {
                    "id": f"retain-{p.strip('/') or p}",
                    "prefix": p,
                    "enabled": True,
                    "condition": {"type": "Age", "maxAgeSeconds": R},
                }
                for p in ("config", "data/", "keys/", "snapshots/")
            ]
            for b in self.objects
        }

    def lock_rules(self, bucket: str) -> list[dict[str, Any]]:
        rules = self.rules[bucket]
        if isinstance(rules, Exception):
            raise rules
        return list(rules)

    def run(self, argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
        assert argv[:3] == ["aws", "--endpoint-url", ENDPOINT]
        op, bucket, key_id = argv[4], argv[argv.index("--bucket") + 1], env["AWS_ACCESS_KEY_ID"]
        key = argv[argv.index("--key") + 1] if "--key" in argv else ""
        self.requests.append((op, bucket, key, key_id))
        if (op, bucket, key_id) in self.override:
            return self.override[(op, bucket, key_id)]
        if key_id not in self.reach[bucket]:
            return 254, "", DENIED.format(op="ListObjectsV2" if op == "list-objects-v2" else "DeleteObject")
        if op == "list-objects-v2":
            contents = self.objects[bucket]
            return 0, json.dumps({"Contents": contents} if contents else {}), ""
        if bucket in self.locked and any(o["Key"] == key for o in self.objects[bucket]):
            return 254, "", LOCKED
        self.deleted.append((bucket, key))
        return 0, "", ""


def _secrets() -> dict[str, str]:
    out: dict[str, str] = {}
    for n in NODES:
        out[access_key_path(n)] = f"{n}-id"
        out[secret_key_path(n)] = f"{n}-key"
    return out


def _probe(r2: R2, declared: list[str] | None = None, secrets: dict[str, str] | None = None) -> bool:
    return bi.probe(
        NODES,
        declared=NODES if declared is None else declared,
        endpoint=ENDPOINT,
        secret=(secrets if secrets is not None else _secrets()).get,
        run=r2.run,
        lock_rules=r2.lock_rules,
        retention_s=R,
        now=NOW,
    )


def _cross(r2: R2, op: str) -> set[tuple[str, str]]:
    owner = {node_bucket(n): f"{n}-id" for n in NODES}
    return {(bucket, key_id) for o, bucket, _k, key_id in r2.requests if o == op and owner[bucket] != key_id}


def test_an_isolated_fleet_passes_and_every_ordered_pair_was_tried_both_ways() -> None:
    r2 = R2()
    assert _probe(r2) is True
    pairs = {(node_bucket(b), f"{a}-id") for a in NODES for b in NODES if a != b}
    assert _cross(r2, "list-objects-v2") == pairs
    assert _cross(r2, "delete-object") == pairs
    assert r2.deleted == []


def test_the_own_delete_targets_the_youngest_pack_not_the_first_key() -> None:
    r2 = R2()
    assert _probe(r2) is True
    own = {(b, k) for o, b, k, kid in r2.requests if o == "delete-object" and kid == f"{b.rsplit('-', 1)[1]}-id"}
    assert own == {(node_bucket(n), f"data/{n}-a") for n in NODES}


def test_a_cross_delete_never_names_an_object_that_exists() -> None:
    # If both the scope and the lock were broken, a probe that deleted a real
    # pack with another node's key would destroy what it set out to protect.
    r2 = R2()
    _probe(r2)
    owner = {node_bucket(n): f"{n}-id" for n in NODES}
    existing = {(b, o["Key"]) for b, objs in r2.objects.items() for o in objs}
    cross = {(b, k) for o, b, k, kid in r2.requests if o == "delete-object" and owner[b] != kid}
    assert cross and not cross & existing


def test_a_key_that_reaches_another_nodes_bucket_fails_it() -> None:
    r2 = R2()
    r2.reach[node_bucket("vps")].add("beelink-id")
    assert _probe(r2) is False


def test_an_accepted_cross_delete_fails_it_though_the_listing_was_refused() -> None:
    r2 = R2()
    r2.override[("delete-object", node_bucket("rpi4"), "rpi3-id")] = (0, "", "")
    assert _probe(r2) is False


def test_a_refusal_that_is_not_access_denied_proves_nothing() -> None:
    # A network error or a missing bucket also fails the request.
    r2 = R2()
    r2.override[("list-objects-v2", node_bucket("rpi4"), "rpi3-id")] = (
        255,
        "",
        "Could not connect to the endpoint URL",
    )
    assert _probe(r2) is False


def test_an_unlocked_bucket_fails_it() -> None:
    r2 = R2()
    r2.locked.discard(node_bucket("rpi3"))
    assert _probe(r2) is False
    assert r2.deleted == [(node_bucket("rpi3"), "data/rpi3-a")]


def _own_deletes(r2: R2, node: str) -> list[tuple[str, str, str, str]]:
    return [r for r in r2.requests if r[0] == "delete-object" and r[1] == node_bucket(node) and r[3] == f"{node}-id"]


def _rule(r2: R2, node: str, prefix: str) -> dict[str, Any]:
    return next(r for r in r2.rules[node_bucket(node)] if r["prefix"] == prefix)


@pytest.mark.parametrize(
    "breakage",
    [
        "no data/ rule",
        "data/ rule disabled",
        "data/ rule shorter than R",
        "data/ rule not by age",
        "lock API unreachable",
    ],
)
def test_a_lock_the_api_cannot_show_fails_it_and_nothing_is_deleted(breakage: str) -> None:
    # The own delete is safe only behind the lock. A probe that tried it with
    # the rule missing would destroy the pack it set out to protect.
    r2 = R2()
    r2.locked.discard(node_bucket("rpi3"))  # what R2 would enforce with the rule gone
    if breakage == "no data/ rule":
        r2.rules[node_bucket("rpi3")] = [r for r in r2.rules[node_bucket("rpi3")] if r["prefix"] != "data/"]
    elif breakage == "data/ rule disabled":
        _rule(r2, "rpi3", "data/")["enabled"] = False
    elif breakage == "data/ rule shorter than R":
        _rule(r2, "rpi3", "data/")["condition"]["maxAgeSeconds"] = R - 1
    elif breakage == "data/ rule not by age":
        _rule(r2, "rpi3", "data/")["condition"] = {"type": "Indefinite"}
    else:
        r2.rules[node_bucket("rpi3")] = RuntimeError("GET /lock failed: timed out")
    assert _probe(r2) is False
    assert _own_deletes(r2, "rpi3") == []
    assert r2.deleted == []


def test_a_newest_pack_near_the_end_of_r_fails_it_and_nothing_is_deleted() -> None:
    # Past R the lock lets the delete through by design, so it would prove
    # nothing and lose the pack.
    r2 = R2()
    r2.objects[node_bucket("vps")] = [{"Key": "data/vps-old", "LastModified": "2026-09-08T11:00:00+00:00"}]
    assert _probe(r2) is False
    assert _own_deletes(r2, "vps") == []


def test_a_newest_pack_well_inside_r_is_tried() -> None:
    r2 = R2()
    r2.objects[node_bucket("vps")] = [{"Key": "data/vps-ok", "LastModified": "2026-09-08T13:00:00Z"}]
    assert _probe(r2) is True
    assert [r[2] for r in _own_deletes(r2, "vps")] == ["data/vps-ok"]


def test_youngest_is_ordered_by_time_not_by_string() -> None:
    # Two spellings of the same instant scheme: a string max would pick the "Z" one.
    r2 = R2()
    r2.objects[node_bucket("rpi4")] = [
        {"Key": "data/rpi4-older", "LastModified": "2026-10-07T03:00:00Z"},
        {"Key": "data/rpi4-newer", "LastModified": "2026-10-07T04:00:00+00:00"},
    ]
    assert _probe(r2) is True
    assert [r[2] for r in _own_deletes(r2, "rpi4")] == ["data/rpi4-newer"]


def test_an_own_delete_refused_for_another_reason_proves_no_lock() -> None:
    r2 = R2()
    r2.override[("delete-object", node_bucket("vps"), "vps-id")] = (254, "", DENIED.format(op="DeleteObject"))
    assert _probe(r2) is False


def test_an_empty_data_prefix_fails_it_and_no_own_delete_is_tried() -> None:
    r2 = R2()
    r2.objects[node_bucket("rpi4")] = []
    assert _probe(r2) is False
    assert not [r for r in r2.requests if r[0] == "delete-object" and r[1:4:2] == (node_bucket("rpi4"), "rpi4-id")]


def test_a_node_still_shipping_to_the_shared_bucket_fails_it() -> None:
    assert _probe(R2(), declared=NODES[:3]) is False


def test_a_node_without_its_pair_in_sops_fails_it() -> None:
    secrets = _secrets()
    del secrets[secret_key_path("rpi3")]
    assert _probe(R2(), secrets=secrets) is False


def test_the_make_target_is_prod_only() -> None:
    recipe = (REPO / "Makefile").read_text().split("\nbackup-isolation-probe:\n", 1)[1].split("\n\n", 1)[0]
    assert '"$(ENV)" = prod' in recipe
    assert "backup isolation-probe --env $(ENV)" in recipe


@pytest.mark.parametrize("node", NODES)
def test_no_secret_reaches_the_output(
    node: str, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    r2 = R2()
    r2.locked.discard(node_bucket(node))
    _probe(r2)
    out = capsys.readouterr()
    assert f"{node}-key" not in caplog.text + out.out + out.err
