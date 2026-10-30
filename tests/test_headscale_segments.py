"""Tenant segments on the shared Headscale (VPN-ACL-014).

Rule 1 granted the existing users a wildcard destination. A tenant node under any
identity was then either inside rule 1 or reachable by it, and Headscale makes both
peers visible when a grant exists in either direction. So the tenant saw every
private peer. Measured through the audit identity on 2026-10-30.

Every segment here is synthetic: real tenants are declared in SOPS, never in this
repository.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from jinja2 import Environment

from toolkit.scripts.render_headscale_policy import EXAMPLE_SEGMENT, render_policy

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "infra/ansible/roles/headscale"
DEFAULTS: dict[str, Any] = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
TASKS: list[dict[str, Any]] = yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8"))
SEGMENT = {
    "owner": "tenant-a",
    "hosts_tag": "tag:tenant-a-hosts",
    "clients_tag": "tag:tenant-a-clients",
    "ports": [22, 3389],
}


def _load(text: str) -> dict[str, Any]:
    no_comments = re.sub(r"//[^\n]*", "", text)
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", no_comments))


def _policy(segments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return _load(render_policy(segments=segments))


def _endpoint(alias: str) -> str:
    """`tag:x:22` -> `tag:x`, `kubelab@:*` -> `kubelab@`."""
    return alias.rsplit(":", 1)[0]


# --- rule 1 keeps every existing flow, without a wildcard -------------------------


@pytest.mark.parametrize("segments", [None, [SEGMENT]])
def test_no_rule_grants_a_wildcard(segments: list[dict[str, Any]] | None) -> None:
    for rule in _policy(segments)["acls"]:
        assert "*" not in rule["src"], rule
        assert not any(_endpoint(d) == "*" for d in rule["dst"]), rule


def test_rule_one_reaches_every_identity_the_policy_knows_except_tenants() -> None:
    """Equivalence with the old wildcard, for every node that exists: each one is owned
    by a user rule 1 names, or carries a tag tagOwners declares, and the only advertised
    subnet is lan-rpi4 (measured 2026-10-30: 14 nodes, users kubelab and manu, tag:hermes)."""
    policy = _policy()
    rule_one = policy["acls"][0]
    known = set(rule_one["src"]) | {o for owners in policy["tagOwners"].values() for o in owners}
    known |= set(policy["tagOwners"]) | {"lan-rpi4"}

    assert {"kubelab@", "manu@", "work@"} == set(rule_one["src"])
    assert {_endpoint(d) for d in rule_one["dst"]} == known
    assert all(d.endswith(":*") for d in rule_one["dst"]), "rule 1 kept every port before; it must still"


# --- a declared segment is isolated ------------------------------------------------


def test_no_private_rule_names_a_segment_tag() -> None:
    tags = {SEGMENT["hosts_tag"], SEGMENT["clients_tag"]}
    private = [r for r in _policy([SEGMENT])["acls"] if not tags & set(r["src"])]

    assert private, "the private rules disappeared"
    for rule in private:
        assert not tags & {_endpoint(d) for d in rule["dst"]}, rule


def test_segment_hosts_originate_nothing_and_clients_reach_only_the_declared_ports() -> None:
    acls = _policy([SEGMENT])["acls"]

    assert not [r for r in acls if SEGMENT["hosts_tag"] in r["src"]], "segment hosts must originate nothing"
    client_dst = [d for r in acls if SEGMENT["clients_tag"] in r["src"] for d in r["dst"]]
    assert client_dst == [f"{SEGMENT['hosts_tag']}:{p}" for p in SEGMENT["ports"]]
    assert not [r for r in acls if SEGMENT["clients_tag"] in {_endpoint(d) for d in r["dst"]}], (
        "nothing may reach a segment client: two clients would see each other"
    )


def test_segment_tags_are_owned_only_by_the_segment_owner() -> None:
    owners = _policy([SEGMENT])["tagOwners"]

    assert owners[SEGMENT["hosts_tag"]] == owners[SEGMENT["clients_tag"]] == [f"{SEGMENT['owner']}@"]


def test_no_segment_renders_no_tenant_tag() -> None:
    assert set(_policy()["tagOwners"]) == {"tag:hermes"}


def test_the_example_segment_the_ci_check_renders_is_a_valid_segment() -> None:
    assert not _failed_checks(EXAMPLE_SEGMENT)


# --- the deploy refuses a malformed segment --------------------------------------


def _assert_task(name: str) -> dict[str, Any]:
    return next(t for t in TASKS if t.get("name") == name)


def _failed_checks(segment: dict[str, Any], segments: list[dict[str, Any]] | None = None) -> list[str]:
    """The role's own assert expressions, evaluated by Jinja as Ansible evaluates them."""
    env = Environment()
    variables = {**DEFAULTS, "item": segment, "headscale_policy_segments": segments or [segment]}
    per_item = _assert_task("Refuse a malformed tenant segment")["assert"]["that"]
    whole = _assert_task("Refuse tenant segments that share a tag")["assert"]["that"]
    return [expr for expr in [*per_item, *whole] if not env.compile_expression(expr)(**variables)]


@pytest.mark.parametrize(
    "change",
    [
        {"owner": "kubelab"},  # a private user's untagged nodes would fall into rule 1
        {"owner": "agents"},
        {"owner": ""},
        {"hosts_tag": "tenant-a-hosts"},  # not a tag
        {"clients_tag": "tag:tenant-a-hosts"},  # one tag for both roles
        {"hosts_tag": "tag:hermes"},  # a private tag
        {"ports": []},
        {"ports": [0]},
        {"ports": [70000]},
        {"ports": ["22"]},
        {"ports": [True]},
        {"ports": "22"},
    ],
)
def test_a_malformed_segment_is_refused(change: dict[str, Any]) -> None:
    assert _failed_checks(SEGMENT | change)


def test_two_segments_sharing_a_tag_are_refused() -> None:
    other = SEGMENT | {"owner": "tenant-b", "clients_tag": "tag:tenant-b-clients"}

    assert _failed_checks(SEGMENT, [SEGMENT, other])


def test_a_well_formed_segment_passes() -> None:
    assert not _failed_checks(SEGMENT)


def test_the_validation_runs_before_the_policy_is_rendered() -> None:
    names = [t.get("name") for t in TASKS]

    assert names.index("Refuse a malformed tenant segment") < names.index("Template Headscale ACL policy")


def test_the_segment_label_never_prints_tenant_data() -> None:
    label = _assert_task("Refuse a malformed tenant segment")["loop_control"]["label"]

    assert "item" not in label


# --- a rollback cannot undo the isolation ------------------------------------------


def _rescue() -> list[dict[str, Any]]:
    block = next(t for t in TASKS if t.get("name") == "Verify mesh + auto-revert on probe failure")
    return block["rescue"]


def test_the_wildcard_pattern_tells_old_policies_from_new_ones() -> None:
    pattern = re.compile(DEFAULTS["headscale_policy_wildcard_pattern"])
    old_rule_one = '{ "action": "accept", "src": ["kubelab@"], "dst": ["*:*"] }'
    allow_all = '{ "acls": [ { "action": "accept", "src": ["*"], "dst": ["*:*"] } ] }'

    assert pattern.search(old_rule_one) and pattern.search(allow_all)
    assert not pattern.search(render_policy()) and not pattern.search(render_policy(segments=[SEGMENT]))


def test_a_previous_policy_with_a_wildcard_is_not_restored_while_segments_exist() -> None:
    restore = next(t for t in _rescue() if t.get("name") == "Restore the previous known-good policy")

    assert "hs_prev_safe" in str(restore["when"])
    decide = next(t for t in _rescue() if "hs_prev_safe" in (t.get("set_fact") or {}))
    expr = decide["set_fact"]["hs_prev_safe"]
    assert "headscale_policy_segments" in expr and "headscale_policy_wildcard_pattern" in expr


def test_the_fallback_is_the_segment_free_policy_not_an_allow_all() -> None:
    fallback = next(t for t in _rescue() if (t.get("template") or {}).get("src") == "policy.hujson.j2")

    assert fallback["vars"]["headscale_policy_segments"] == []
    assert "not (hs_prev_safe | bool)" in str(fallback["when"])
    assert not re.search(DEFAULTS["headscale_policy_wildcard_pattern"], yaml.safe_dump(_rescue())), (
        "a rescue task still writes a wildcard grant"
    )


# --- tenant data never lives in this repository ----------------------------------


def test_segments_reach_the_role_only_from_sops() -> None:
    play = (REPO / "infra/ansible/playbooks/deploy-vps.yml").read_text(encoding="utf-8")
    line = next(ln for ln in play.splitlines() if "headscale_policy_segments" in ln)
    expr = line + play.split(line, 1)[1].split("\n", 3)[1]

    assert "secrets" in expr and "config." not in expr
    assert DEFAULTS["headscale_policy_segments"] == []
