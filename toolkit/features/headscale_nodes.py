"""Give a recreated node its name back, after the cleanup that should have.

The hub is a Spot VM in a MIG. When GCP preempts it the group rebuilds it in
seconds, and the replacement asks Headscale to register under the same hostname.
Headscale identifies a node by its GIVEN NAME, and a given name is taken until
its record is deleted -- so a registration while the predecessor's record still
exists lands as `gcp1-<random>` instead.

Nothing about that is cosmetic. `gcp1.kubelab.internal` keeps resolving to the
dead node's address, and every path that addresses the hub by name follows it
there: the Ansible inventory, the kubeconfig server URL, and the prod Argo CD
EndpointSlice, whose `RESOLVE_GCP1_TAILSCALE_IP` placeholder is filled from
MagicDNS at apply time. Measured 2026-08-24 (#1369): a real preemption at
17:13:39, the MIG rebuilt the VM by 17:13:57, and `argo.kubelab.live` was down
until a human noticed.

`cloud-init.yml` already tries to do this at boot and did not (its own log line
reads `no stale Headscale node to recycle` while the predecessor was sitting
right there). This module exists so the repair is a command rather than two
remembered `docker exec`s, and so the fix for that boot-time query has one
implementation to converge on instead of a second copy of the same jq.

TRANSPORT: the Headscale CLI over SSH, matching `secret_expiry.py`. Not the REST
API, deliberately -- the API needs a key, and a key that reaches this process is
a key that can reach a log. The CLI on the VPS already has the authority.

DEFAULT IS A PLAN, NOT AN ACTION. `recycle` reports what it would do and changes
nothing until told; deleting a mesh identity is not the sort of thing a command
should do because someone ran it to look.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass

# A given name Headscale minted for a duplicate registration: the canonical name
# plus its random suffix (`gcp1-mj5bsge9`). Anchored at both ends so a name that
# merely STARTS with the canonical one is not a candidate -- `gcp1-hub-backup`
# does not match, because the suffix Headscale generates carries no hyphen.
#
# What this pattern does NOT do is tell a random suffix from a deliberate name
# of the same shape: `gcp1-mig` would match it. The regex is a filter, not the
# safety property. The safety property is the refusal set in `plan_recycle` --
# exactly one candidate, it must be online, and the name's current holder must be
# offline -- which is what makes acting on the wrong machine require three
# independent coincidences rather than one unlucky name.
_SUFFIXED = "^{canonical}-[a-z0-9]+$"


class HeadscaleUnavailableError(RuntimeError):
    """Headscale could not be asked. Distinct from 'there is nothing to do'."""


class RecycleRefused(RuntimeError):
    """The situation is not the one this command is safe to act on."""


@dataclass(frozen=True)
class Node:
    id: int
    given_name: str
    online: bool
    address: str

    @property
    def label(self) -> str:
        return f"{self.given_name} (id {self.id}, {self.address}, {'online' if self.online else 'offline'})"


@dataclass(frozen=True)
class RecyclePlan:
    """What would happen. `stale` is deleted, `live` is renamed to `canonical`."""

    canonical: str
    stale: Node
    live: Node


def parse_nodes(payload: str) -> list[Node]:
    """`headscale nodes list --output json`.

    `online` is read with a default of False rather than indexed, and that is the
    defect this whole module descends from: the field is ABSENT on an offline
    node, because proto3 JSON omits false booleans. A predicate written as
    `.online == false` therefore compares `null` against `false` and matches
    nothing -- it does not select offline nodes, it selects none at all.
    """
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HeadscaleUnavailableError(f"headscale did not return JSON: {exc}") from exc

    nodes = []
    for entry in raw:
        addresses = entry.get("ip_addresses") or []
        ipv4 = next((a for a in addresses if ":" not in a), "")
        nodes.append(
            Node(
                id=int(entry["id"]),
                given_name=entry.get("given_name", ""),
                # Absent means offline. See the docstring.
                online=bool(entry.get("online", False)),
                address=ipv4,
            )
        )
    return nodes


def list_nodes(ssh_target: str, container: str = "headscale") -> list[Node]:
    """Ask the VPS which nodes Headscale currently knows about."""
    result = subprocess.run(
        [
            "ssh",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "BatchMode=yes",
            ssh_target,
            f"docker exec {container} headscale nodes list --output json",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise HeadscaleUnavailableError(f"could not ask headscale on {ssh_target}: {result.stderr.strip()}")

    nodes = parse_nodes(result.stdout)
    if not nodes:
        raise HeadscaleUnavailableError(
            f"headscale on {ssh_target} reported zero nodes. An empty mesh and a failed query are "
            "indistinguishable from here, and only one of them is safe to act on."
        )
    return nodes


def plan_recycle(nodes: list[Node], canonical: str) -> RecyclePlan:
    """Decide whether this is the situation the command exists for.

    Every refusal below is a case where acting would be worse than doing nothing,
    and they are separated so the message says which one happened.
    """
    holder = [n for n in nodes if n.given_name == canonical]
    suffixed = [n for n in nodes if re.match(_SUFFIXED.format(canonical=re.escape(canonical)), n.given_name)]

    if not holder:
        raise RecycleRefused(
            f"nothing holds the name {canonical!r}. Either it was already recycled, or the name is wrong."
        )
    if len(holder) > 1:
        raise RecycleRefused(f"{len(holder)} nodes claim {canonical!r}; Headscale should make that impossible")
    if holder[0].online:
        raise RecycleRefused(
            f"{holder[0].label} holds {canonical!r} and is ONLINE. Refusing: this command reclaims a name "
            "from a dead record, and that record is alive."
        )
    if not suffixed:
        raise RecycleRefused(
            f"{canonical!r} is held by an offline node and NO suffixed replacement exists. That is a node "
            "that simply died, not a name collision — deleting it here would hide it instead of fixing it."
        )
    if len(suffixed) > 1:
        raise RecycleRefused(
            f"{len(suffixed)} suffixed candidates ({', '.join(n.given_name for n in suffixed)}). "
            "Refusing to guess which one should own the name."
        )
    if not suffixed[0].online:
        raise RecycleRefused(
            f"the replacement {suffixed[0].label} is offline too. Renaming a dead node onto the canonical "
            "name would move the outage rather than end it."
        )

    return RecyclePlan(canonical=canonical, stale=holder[0], live=suffixed[0])


def _headscale(ssh_target: str, args: str, container: str = "headscale") -> str:
    result = subprocess.run(
        [
            "ssh",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "BatchMode=yes",
            ssh_target,
            f"docker exec {container} headscale {args}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise HeadscaleUnavailableError(f"headscale {args} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _checked_id(node_id: int) -> str:
    """Node ids are interpolated into a shell command on a remote host.

    They come from Headscale's own output and are already ints by the time they
    reach here, so this asserts an invariant rather than sanitising input -- the
    same posture `expire_headscale_preauthkey` takes, and for the same reason:
    the day the parse loosens, this is the line that has to fail.
    """
    if not isinstance(node_id, int) or node_id < 0:
        raise RecycleRefused(f"refusing to build a remote command around {node_id!r}")
    return str(node_id)


def delete_node(ssh_target: str, node_id: int, container: str = "headscale") -> None:
    """`--force`, because without it headscale prompts and the ssh session hangs."""
    _headscale(ssh_target, f"nodes delete --identifier {_checked_id(node_id)} --force", container)


def rename_node(ssh_target: str, node_id: int, new_name: str, container: str = "headscale") -> None:
    if not re.match(r"^[a-z0-9][a-z0-9-]{0,62}$", new_name):
        raise RecycleRefused(f"refusing to rename to {new_name!r}: not a plausible node name")
    _headscale(ssh_target, f"nodes rename --identifier {_checked_id(node_id)} {new_name}", container)


def apply_recycle(ssh_target: str, plan: RecyclePlan, container: str = "headscale") -> None:
    """Delete first, then rename. The order is not interchangeable: Headscale
    refuses to assign a given name that is still taken, so a rename before the
    delete fails and leaves both records in place."""
    delete_node(ssh_target, plan.stale.id, container)
    rename_node(ssh_target, plan.live.id, plan.canonical, container)
