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

import re
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


class TestTheConditionEvaluates:
    """Asserting that a `when:` NAMES a variable is not asserting that it fires.

    The first version of this file checked only that the purge task's condition
    mentioned `_node_address_is_ephemeral`. It did. The expression behind that
    name evaluated FALSE for every host, because it read
    `hostvars[inventory_hostname].ansible_host` -- undefined at play-vars scope --
    and `| default('')` turned that into an empty string that matched nothing.

    So the task skipped, silently, on the one run that needed it: measured during
    a real preemption as `skipping: [gcp1]` followed by a ten-minute hang on a
    host key nothing had cleared.

    A guard that reads the shape of a condition and never evaluates it is the
    same defect as a test that agrees with an ADR instead of the API
    (lesson-366) -- and this one was written to prevent that class.
    """

    @staticmethod
    def _evaluate(ansible_host: str) -> bool:
        """Render the play's own expression, the way Ansible would."""
        import re as _re

        from jinja2 import Environment

        plays = yaml.safe_load(PLAYBOOK.read_text())
        expr = next(
            p["vars"]["_node_address_is_ephemeral"]
            for p in plays
            if "_node_address_is_ephemeral" in (p.get("vars") or {})
        )
        env = Environment()
        env.tests["search"] = lambda value, pattern: _re.search(pattern, value) is not None
        env.tests["match"] = lambda value, pattern: _re.match(pattern, value) is not None
        rendered = env.from_string(str(expr)).render(ansible_host=ansible_host).strip()
        return rendered.lower() == "true"

    def test_it_fires_for_a_magicdns_addressed_node(self) -> None:
        """gcp1 -- the whole reason the task exists."""
        assert self._evaluate("gcp1.kubelab.internal") is True

    def test_it_does_not_fire_for_an_ip_addressed_node(self) -> None:
        """Every stable node is addressed by a recorded IP and must keep its
        host-key check; purging theirs would trade the fleet's MITM detection
        for one node's convenience."""
        assert self._evaluate("100.64.0.2") is False
        assert self._evaluate("172.16.1.2") is False

    def test_an_undefined_ansible_host_raises_rather_than_skipping(self) -> None:
        """The exact failure. `| default('')` made an undefined lookup mean
        "not ephemeral", which is indistinguishable from a deliberate decision.
        Absent a host, this must break loudly instead."""
        import jinja2

        with pytest.raises((jinja2.exceptions.UndefinedError, TypeError)):
            import re as _re

            from jinja2 import Environment, StrictUndefined

            plays = yaml.safe_load(PLAYBOOK.read_text())
            expr = next(
                p["vars"]["_node_address_is_ephemeral"]
                for p in plays
                if "_node_address_is_ephemeral" in (p.get("vars") or {})
            )
            env = Environment(undefined=StrictUndefined)
            env.tests["search"] = lambda value, pattern: _re.search(pattern, value) is not None
            env.from_string(str(expr)).render()


def test_wait_node_ready_generates_the_inventory_it_needs() -> None:
    """It reads a generated inventory and nothing was generating one.

    `gcp1-replace` and `aws1-replace` both call `wait-node-ready` FIRST and
    `provision` second. Only `provision` regenerates, so on a fresh worktree the
    recreate chain died at its first step:

        [ERROR] Inventory not found: infra/ansible/generated/hub/hosts.yml
        [INFO] Run 'toolkit infra ansible generate --env {env}' first

    Measured during a real preemption test. Fixed in `wait-node-ready` rather
    than in the two callers, because the requirement belongs to the step that
    has it -- otherwise the next caller inherits the same gap.
    """
    makefile = (Path(__file__).resolve().parent.parent / "Makefile").read_text()
    recipe = re.search(r"^wait-node-ready:[^\n]*\n((?:\t.*\n)+)", makefile, re.M)
    assert recipe, "wait-node-ready has no recipe"
    body = recipe.group(1)

    generate = body.find("ansible generate")
    run = body.find("ansible run -p wait-node-ready")
    assert generate != -1, "wait-node-ready never generates the inventory it reads"
    assert generate < run, "the inventory is generated after the playbook has already run"
