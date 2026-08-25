"""Guards for reclaiming a hub's name after a preemption (#1369).

The bug these descend from was not in the logic that deletes a node — it was in
the QUESTION asked before deleting one. `cloud-init.yml` asks Headscale for a
node that is `.online == false`, an offline node omits the field entirely, and
`null == false` is false, so the query returns nothing and says so cheerfully:
`no stale Headscale node to recycle`, printed in production while the stale node
sat in the same response.

So the first test here is about a MISSING KEY, and it is the load-bearing one.
"""

from __future__ import annotations

import json

import pytest

from toolkit.features.headscale_nodes import (
    HeadscaleUnavailableError,
    Node,
    RecycleRefused,
    parse_nodes,
    plan_recycle,
    rename_node,
)


def _node(id_: int, given: str, online: bool = False, addr: str = "100.64.0.1") -> Node:
    return Node(id=id_, given_name=given, online=online, address=addr)


# The shape headscale really returns, captured from the live VPS on 2026-08-24.
# The offline node HAS NO `online` KEY. That is the whole finding, so it is
# fixtured verbatim rather than paraphrased into `"online": false`.
_LIVE_PAYLOAD = json.dumps(
    [
        {
            "id": 39,
            "name": "gcp1",
            "given_name": "gcp1",
            "ip_addresses": ["100.64.0.13", "fd7a:115c:a1e0::d"],
        },
        {
            "id": 40,
            "name": "gcp1",
            "given_name": "gcp1-mj5bsge9",
            "online": True,
            "ip_addresses": ["100.64.0.14", "fd7a:115c:a1e0::e"],
        },
    ]
)


def test_an_offline_node_omits_the_online_field_and_still_parses_as_offline() -> None:
    """proto3 JSON drops false booleans. Reading `online` as absent-means-offline
    is what makes the stale record findable at all."""
    nodes = {n.id: n for n in parse_nodes(_LIVE_PAYLOAD)}

    assert nodes[39].online is False, "a node with no `online` key is offline, not unknown and not online"
    assert nodes[40].online is True


def test_the_ipv4_address_is_selected_not_the_first_one() -> None:
    """MagicDNS and the EndpointSlice both carry the v4 address; `ip_addresses`
    holds both families and the order is headscale's business, not ours."""
    nodes = {n.id: n for n in parse_nodes(_LIVE_PAYLOAD)}

    assert nodes[39].address == "100.64.0.13"
    assert nodes[40].address == "100.64.0.14"


def test_the_live_incident_produces_the_expected_plan() -> None:
    plan = plan_recycle(parse_nodes(_LIVE_PAYLOAD), "gcp1")

    assert plan.stale.id == 39, "the dead record holding the name is the one deleted"
    assert plan.live.id == 40, "the suffixed survivor is the one renamed"
    assert plan.canonical == "gcp1"


def test_it_refuses_when_the_name_holder_is_online() -> None:
    """The dangerous case: a healthy node owns the name and something else is
    suffixed. Deleting here would take down the thing that works."""
    nodes = [_node(1, "gcp1", online=True), _node(2, "gcp1-abc123", online=True)]

    with pytest.raises(RecycleRefused, match="ONLINE"):
        plan_recycle(nodes, "gcp1")


def test_it_refuses_a_node_that_merely_died() -> None:
    """An offline node with no replacement is an outage to investigate, not a
    name collision to clean up. Deleting it would erase the evidence."""
    with pytest.raises(RecycleRefused, match="simply died"):
        plan_recycle([_node(1, "gcp1")], "gcp1")


def test_it_refuses_to_choose_between_two_candidates() -> None:
    nodes = [_node(1, "gcp1"), _node(2, "gcp1-abc123", online=True), _node(3, "gcp1-def456", online=True)]

    with pytest.raises(RecycleRefused, match="Refusing to guess"):
        plan_recycle(nodes, "gcp1")


def test_it_refuses_when_the_replacement_is_also_offline() -> None:
    """Renaming a dead node onto the canonical name moves the outage instead of
    ending it, and it looks like a fix."""
    nodes = [_node(1, "gcp1"), _node(2, "gcp1-abc123", online=False)]

    with pytest.raises(RecycleRefused, match="offline too"):
        plan_recycle(nodes, "gcp1")


def test_a_hyphenated_neighbour_is_not_a_candidate() -> None:
    """`gcp1-hub-backup` starts with the canonical name and is not a headscale
    suffix — the pattern is anchored at both ends for exactly this."""
    nodes = [_node(1, "gcp1"), _node(2, "gcp1-hub-backup", online=True)]

    with pytest.raises(RecycleRefused, match="NO suffixed replacement"):
        plan_recycle(nodes, "gcp1")


def test_an_unrelated_node_is_never_touched() -> None:
    nodes = [_node(1, "gcp1"), _node(2, "gcp1-abc123", online=True), _node(3, "vps", online=True)]

    plan = plan_recycle(nodes, "gcp1")

    assert plan.stale.id == 1 and plan.live.id == 2


def test_a_rename_target_must_look_like_a_node_name() -> None:
    """The name is interpolated into a command that runs on the VPS."""
    with pytest.raises(RecycleRefused, match="not a plausible node name"):
        rename_node("deployer@vps", 1, "gcp1; rm -rf /")


def test_a_non_json_answer_is_an_error_not_an_empty_mesh() -> None:
    with pytest.raises(HeadscaleUnavailableError):
        parse_nodes("Error: connection refused")
