"""Eligibility preflight for the Headscale v0.28 -> v0.29 upgrade (VPN-ACL-006, AC1).

Every case here is synthetic. The preflight decides from facts it is handed and
runs nothing, so a refusal can never be preceded by a mutation: the last test
proves it by making any process spawn fail the run.
"""

from __future__ import annotations

import ast
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

import toolkit.features.headscale_upgrade as preflight
from tests.test_headscale_nodes import _LIVE_PAYLOAD
from toolkit.features.headscale_upgrade import Facts, evaluate, parse_node_states

NOW = datetime(2026, 10, 30, tzinfo=timezone.utc)
PAST = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp())
FUTURE = int(datetime(2027, 1, 1, tzinfo=timezone.utc).timestamp())
DIGEST = "sha256:" + "a" * 64
TARGET = f"headscale/headscale:v0.29.6@{DIGEST}"


def _node(name: str, given: str | None = None, online: bool = True, expiry: int | None = None) -> dict[str, Any]:
    node: dict[str, Any] = {"id": "1", "name": name, "given_name": given or name}
    if online:
        node["online"] = True  # proto3 JSON omits a false boolean: absent means offline
    if expiry is not None:
        node["expiry"] = {"seconds": str(expiry)}
    return node


def _facts(**overrides: Any) -> Facts:
    base: dict[str, Any] = {
        "current_image": "headscale/headscale:v0.28.0",
        "target_image": TARGET,
        "registry_index": {DIGEST: {"linux/amd64", "linux/arm64"}},
        "nodes": parse_node_states(json.dumps([_node("vps"), _node("gcp1", expiry=FUTURE)])),
        "required": {"vps": "1.96.4", "gcp1": "1.80.0"},
        "approved": True,
    }
    base.update(overrides)
    return Facts(**base)


def _codes(facts: Facts) -> set[str]:
    return {refusal.code for refusal in evaluate(facts, now=NOW).refusals}


def test_eligibility_passes_when_every_fact_is_safe() -> None:
    verdict = evaluate(_facts(), now=NOW)

    assert verdict.eligible, verdict.refusals
    assert verdict.refusals == ()


@pytest.mark.parametrize("version", [None, "", "unknown", "1.78.1", "1.79.99"])
def test_eligibility_refuses_an_unknown_or_too_old_client(version: str | None) -> None:
    """v0.29.3 rejects `/key` below 1.80.0, so an old client is cut off, not degraded."""
    assert "client-version" in _codes(_facts(required={"vps": "1.96.4", "gcp1": version}))


def test_eligibility_accepts_a_client_version_with_a_build_suffix() -> None:
    assert _codes(_facts(required={"vps": "1.96.4-t1234abcd", "gcp1": "1.80.0"})) == set()


def test_eligibility_refuses_a_required_node_headscale_does_not_know() -> None:
    assert "node-missing" in _codes(_facts(required={"vps": "1.96.4", "ace1": "1.90.0"}))


@pytest.mark.parametrize(
    "target",
    [
        "headscale/headscale:v0.29.6",  # tag only: mutable, nothing verified
        "headscale/headscale:v0.29.6@sha256:" + "b" * 64,  # digest the registry did not list
    ],
)
def test_eligibility_refuses_an_unverified_image_pin(target: str) -> None:
    assert "image-unverified" in _codes(_facts(target_image=target))


def test_eligibility_refuses_a_pin_without_an_arm64_image() -> None:
    """The VPS is ARM: a release checksum or an amd64-only index is not evidence."""
    assert "image-unverified" in _codes(_facts(registry_index={DIGEST: {"linux/amd64"}}))


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("v0.27.1", "v0.29.6"),  # skips a minor: upstream requires adjacent upgrades
        ("v0.28.0", "v0.30.0"),
        ("v0.29.6", "v0.28.0"),  # minor downgrade: blocked upstream
        ("v0.28.0", "v0.28.0"),  # not an upgrade
        ("v0.28.0", "v0.29.0"),  # loses the user of nodes with tags='null', fixed in v0.29.1
        ("latest", "v0.29.6"),
    ],
)
def test_eligibility_refuses_an_unsupported_transition(current: str, target: str) -> None:
    facts = _facts(
        current_image=f"headscale/headscale:{current}", target_image=f"headscale/headscale:{target}@{DIGEST}"
    )

    assert "transition" in _codes(facts)


def test_eligibility_refuses_without_production_approval() -> None:
    assert "approval" in _codes(_facts(approved=False))


def test_eligibility_refuses_a_required_node_online_with_an_expired_key() -> None:
    """v0.29.4 ends the map session of an expired node, so it would drop at upgrade."""
    nodes = parse_node_states(json.dumps([_node("vps"), _node("gcp1", expiry=PAST)]))

    assert "expired-online" in _codes(_facts(nodes=nodes))


@pytest.mark.parametrize(
    "raw",
    [
        _node("gcp1", online=False, expiry=PAST),  # expired but offline: nothing to drop
        _node("gcp1", expiry=-62135596800),  # 0001-01-01: the pre-v0.29 "no expiry" sentinel
        _node("gcp1"),  # no expiry at all
    ],
)
def test_eligibility_ignores_an_expiry_that_will_not_disconnect_anything(raw: dict[str, Any]) -> None:
    nodes = parse_node_states(json.dumps([_node("vps"), raw]))

    assert "expired-online" not in _codes(_facts(nodes=nodes))


def test_eligibility_refuses_a_required_node_with_the_old_random_suffix() -> None:
    """v0.29.0 renames collisions numerically, so `gcp1-mj5bsge9` changes name at upgrade."""
    nodes = parse_node_states(json.dumps([_node("vps"), _node("gcp1", given="gcp1-mj5bsge9", expiry=FUTURE)]))

    assert "random-suffix" in _codes(_facts(nodes=nodes))


def test_eligibility_reads_the_suffix_from_the_shape_headscale_really_returns() -> None:
    """The payload captured from the live VPS: both records keep `name` as the bare hostname,
    so a suffixed duplicate is found by hostname and reported as a rename, not as missing."""
    codes = _codes(_facts(nodes=parse_node_states(_LIVE_PAYLOAD), required={"gcp1": "1.90.0"}))

    assert codes == {"random-suffix"}


@pytest.mark.parametrize(
    ("raw", "expired"),
    [
        ({"seconds": PAST}, True),  # encoding/json renders int64 as a number
        ({"seconds": str(PAST), "nanos": 1}, True),  # protojson renders it as a string
        ("2026-10-01T00:00:00Z", True),  # protojson renders a Timestamp as RFC 3339
        ("0001-01-01T00:00:00Z", False),  # the zero-time sentinel, as RFC 3339
    ],
)
def test_eligibility_reads_every_expiry_shape_headscale_can_emit(raw: object, expired: bool) -> None:
    node = _node("gcp1") | {"expiry": raw}
    nodes = parse_node_states(json.dumps([_node("vps"), node]))

    assert ("expired-online" in _codes(_facts(nodes=nodes))) is expired


@pytest.mark.parametrize("raw", [{"nanos": 1}, 1700000000, "yesterday", "2026-10-01T00:00:00", []])
def test_eligibility_fails_closed_on_an_expiry_it_cannot_read(raw: object) -> None:
    """An unreadable expiry must not read as 'no expiry': that would pass an expired node silently."""
    with pytest.raises(ValueError, match="expiry"):
        parse_node_states(json.dumps([_node("gcp1") | {"expiry": raw}]))


@pytest.mark.parametrize("given", ["gcp1", "gcp1-hub", "hub-backup1"])
def test_eligibility_does_not_mistake_a_chosen_name_for_a_random_suffix(given: str) -> None:
    nodes = parse_node_states(json.dumps([_node("vps"), _node("gcp1", given=given, expiry=FUTURE)]))

    assert "random-suffix" not in _codes(_facts(nodes=nodes))


def test_eligibility_reports_every_refusal_at_once() -> None:
    """The operator fixes the whole list in one pass instead of one error per run."""
    codes = _codes(_facts(approved=False, target_image="headscale/headscale:v0.29.6", required={"vps": None}))

    assert {"approval", "image-unverified", "client-version"} <= codes


def test_eligibility_runs_no_process_so_a_refusal_mutates_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _spawned(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the preflight spawned a process")

    monkeypatch.setattr(subprocess, "run", _spawned)
    monkeypatch.setattr(subprocess, "Popen", _spawned)

    verdict = evaluate(_facts(approved=False, required={"vps": "1.2.3"}), now=NOW)

    assert not verdict.eligible


def test_eligibility_cannot_reach_a_process_a_file_or_the_network() -> None:
    """Patching `subprocess` misses `os.system`, sockets and HTTP clients. The module
    importing nothing that can reach them is what makes 'refuses before mutating' structural."""
    tree = ast.parse(Path(preflight.__file__).read_text(encoding="utf-8"))
    imported = {
        name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for name in ([a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""])
    }

    assert imported <= {"__future__", "collections", "dataclasses", "datetime", "json", "re"}, imported
