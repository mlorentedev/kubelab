"""Each node's token names its own bucket and nothing else (BACKUP-057 AC3).

Distinct key pairs alone cannot show isolation: four pairs minted from one
policy that spans every bucket, or the whole account, would all differ and all
reach every history. So this asserts on the policy each mint requests from the
Cloudflare API: exactly one resource, the node's own bucket, with Object Read &
Write and nothing more.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

from toolkit.features import backup_node_credentials as bnc

REPO = pathlib.Path(__file__).resolve().parent.parent
COMMON = REPO / "infra" / "config" / "values" / "common.yaml"


def _nodes() -> list[str]:
    return sorted(yaml.safe_load(COMMON.read_text(encoding="utf-8"))["backup"]["sources"])


@pytest.mark.parametrize("node", _nodes())
def test_the_requested_policy_names_exactly_the_nodes_own_bucket(node: str) -> None:
    body = bnc.token_request(node, account_id="acct0123", write_group_id="pg-write")
    assert len(body["policies"]) == 1
    policy = body["policies"][0]
    assert policy["effect"] == "allow"
    assert policy["resources"] == {f"com.cloudflare.edge.r2.bucket.acct0123_default_kubelab-backup-{node}": "*"}
    assert policy["permission_groups"] == [{"id": "pg-write"}]


def test_no_two_nodes_request_the_same_resource() -> None:
    resources = [
        next(
            iter(bnc.token_request(node, account_id="acct0123", write_group_id="pg-write")["policies"][0]["resources"])
        )
        for node in _nodes()
    ]
    assert len(resources) == len(set(resources))


def test_an_account_wide_resource_is_never_requested() -> None:
    for node in _nodes():
        resources = bnc.token_request(node, account_id="acct0123", write_group_id="pg-write")["policies"][0][
            "resources"
        ]
        assert not any(key.startswith("com.cloudflare.api.account") for key in resources)
        assert not any(key.endswith("*") or "_*" in key for key in resources)
