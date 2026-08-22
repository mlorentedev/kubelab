"""A recreated node presents a new host key, and SSH refuses it by default.

The MIG replaces the hub's VM on every preemption. The MagicDNS name stays
`gcp1.kubelab.internal`, so ssh finds the previous machine's key in known_hosts
and aborts:

    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!

`accept-new` -- what the generated inventory uses -- accepts UNKNOWN hosts and
still refuses CHANGED ones, which is the correct default and exactly wrong here.

None of this is new: `docs/runbooks/ssh-keys.md` documents the warning and the
`ssh-keygen -R` remedy. It documents it as a MANUAL step after reflashing a
node -- a rare, attended event. A MIG makes it routine and unattended, so the
remedy has to move from the runbook into the path.

Scoped, not blanket. Purging a host key removes real protection, so it happens
only for nodes whose MACHINE is expected to be replaced. The SSOT already marks
those: a node with `tailscale_dns` but no `tailscale_ip` is one whose address --
and therefore whose instance -- rotates by design. `networking.gcp` says so in a
comment; every stable node records an IP.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
PLAYBOOK = REPO / "infra/ansible/playbooks/wait-node-ready.yml"
COMMON = REPO / "infra/config/values/common.yaml"


@pytest.fixture(scope="module")
def plays() -> list[dict]:
    return yaml.safe_load(PLAYBOOK.read_text())


def _code(path: Path) -> str:
    """The playbook with comment lines removed.

    Ordering assertions must not read the header. This playbook's own header
    lists its steps -- "1. sshd answers -- wait_for_connection" -- so a naive
    `text.find("wait_for_connection")` matches line 7 and reports that the purge
    runs too late when it does not.

    THIRD OCCURRENCE OF THIS IN ONE SESSION, and the second while writing a
    guard against the same class (lesson-363). A text scan matching the prose
    that documents the thing is apparently the default mistake, not an unlucky
    one; strip comments before asserting on order, always.
    """
    return "\n".join(line for line in path.read_text().splitlines() if not line.lstrip().startswith("#"))


def _all_tasks(plays: list[dict]) -> list[dict]:
    out: list[dict] = []
    for play in plays:
        for key in ("pre_tasks", "tasks", "post_tasks"):
            out.extend(play.get(key) or [])
    return out


def test_a_stale_host_key_is_purged(plays: list[dict]) -> None:
    """Otherwise the very first `wait_for_connection` aborts, and the MIG's
    self-healing stops at the operator's known_hosts."""
    text = _code(PLAYBOOK)
    assert "known_hosts" in text, (
        "wait-node-ready never clears a stale host key. After a MIG recreate the "
        "first SSH attempt aborts with REMOTE HOST IDENTIFICATION HAS CHANGED."
    )


def test_the_purge_runs_before_the_connection_wait(plays: list[dict]) -> None:
    """Clearing it afterwards is the same as not clearing it."""
    text = _code(PLAYBOOK)
    purge = text.find("known_hosts")
    wait = text.find("wait_for_connection")
    assert purge != -1 and wait != -1
    assert purge < wait, "the host key is purged after the connection was already attempted"


def test_the_purge_is_conditional_not_blanket(plays: list[dict]) -> None:
    """A host key is a real protection. Removing it for every node would trade
    a MIG's convenience for the whole fleet's MITM detection."""
    purge = [t for t in _all_tasks(plays) if "known_hosts" in str(t)]
    assert purge, "no purge task found"

    # The CONDITION, not merely a `when:` key. Asserting presence alone let a
    # mutation to `when: true` pass -- found by mutating, not by reading, and a
    # guard that accepts `when: true` guards nothing.
    conditions = [str(task.get("when", "")) for task in purge]
    assert any("_node_address_is_ephemeral" in c for c in conditions), (
        f"the host-key purge is not gated on the ephemeral-address marker: {conditions}. "
        "Only nodes whose machine is replaced by design should have their key discarded; "
        "anything broader trades the fleet's MITM detection for one node's convenience."
    )


def test_only_the_gcp_hub_qualifies_today(plays: list[dict]) -> None:
    """Pins the marker's meaning against the SSOT rather than against a name.

    Every stable node records a `tailscale_ip`; the MIG-backed hub deliberately
    does not, because a recreate rotates it. If that ever stops being true, this
    fails rather than silently widening the purge.
    """
    net = yaml.safe_load(COMMON.read_text())["networking"]
    ephemeral = [
        key
        for key, block in net.items()
        if isinstance(block, dict) and block.get("tailscale_dns") and not block.get("tailscale_ip")
    ]
    assert ephemeral == ["gcp"], f"expected only the GCP hub to have an ephemeral address, got {ephemeral}"
