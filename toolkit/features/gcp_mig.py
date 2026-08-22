"""Lifecycle operations on the hub's managed instance group.

`aws1` needed an out-of-band Spot-request cancellation before every destroy,
because the request outlived the instance and relaunched a replacement Terraform
knew nothing about. A MIG has no such shadow object: the group IS the contract,
and resizing it is the whole of start and stop. That is capability the migration
ADDS -- `aws1` never had a start or stop target at all.

`recreate` deletes the running instance and lets the group rebuild it. That is
deliberately the SAME path a real preemption takes, so exercising it exercises
the recreate contract rather than rehearsing something adjacent to it.

Nothing here can run against real GCP until a project exists, so every guard is
about the SHAPE of the command. That is where the mistakes live: a regional group
addressed with `--zone` resolves to nothing and fails naming a missing resource
rather than a wrong flag, and gcloud's ambient default project is whatever the
operator last set -- a resize against the wrong project is not an error, it is a
resize.
"""

from __future__ import annotations

import json
import subprocess
import time
from typing import Any

from toolkit.core.logging import logger

# The hub is a singleton by design: two Argo CD controllers reconciling one spoke
# is the exact failure `managed_spokes` exists to prevent, and a fat-fingered
# size is the cheapest way to cause it.
MAX_TARGET_SIZE = 1

# How long to wait for the group to finish replacing an instance. Generous
# because a Spot rebuild includes capacity acquisition, and the failure this
# bounds is a STUCK replacement -- which must be reported, never waited on
# for ever inside an unattended chain.
RECREATE_TIMEOUT_S = 600


def _gcp(config: dict[str, Any]) -> dict[str, Any]:
    gcp = config.get("networking", {}).get("gcp", {})
    for key in ("hostname", "region", "project_id"):
        if not gcp.get(key):
            raise KeyError(f"networking.gcp.{key} is missing; the MIG cannot be addressed without it")
    return gcp


def _scope(config: dict[str, Any]) -> list[str]:
    """Group name, region and project — never inherited from gcloud's context."""
    gcp = _gcp(config)
    return [
        f"{gcp['hostname']}-mig",
        "--region",
        str(gcp["region"]),
        "--project",
        str(gcp["project_id"]),
    ]


def _run(argv: list[str]) -> int:
    """Run a gcloud command, streaming its output. No secret ever transits here."""
    logger.info(" ".join(argv))
    try:
        return subprocess.run(argv, check=False).returncode
    except FileNotFoundError as exc:
        raise RuntimeError(
            "gcloud is not installed. It is a prerequisite of the hub bootstrap — "
            "see docs/runbooks/gcp-hub-bootstrap.md §2."
        ) from exc


def _managed_instances(config: dict[str, Any]) -> list[dict[str, Any]]:
    """The group's managed instances, with `id`, `instanceStatus` and `currentAction`.

    The numeric `id` is the only field that distinguishes one VM from its
    replacement: `replacement_method = RECREATE` preserves the NAME deliberately
    (see main.tf -- a changing name reintroduces the Headscale given-name
    collision), so name comparison cannot detect a replacement at all.
    """
    argv = ["gcloud", "compute", "instance-groups", "managed", "list-instances", *_scope(config), "--format=json"]
    try:
        out = subprocess.run(argv, check=True, capture_output=True, text=True).stdout
    except FileNotFoundError as exc:
        raise RuntimeError(
            "gcloud is not installed. It is a prerequisite of the hub bootstrap — "
            "see docs/runbooks/gcp-hub-bootstrap.md §2."
        ) from exc
    result: list[dict[str, Any]] = json.loads(out or "[]")
    return result


def _list_instances(config: dict[str, Any]) -> list[str]:
    argv = ["gcloud", "compute", "instance-groups", "managed", "list-instances", *_scope(config), "--format=json"]
    logger.info(" ".join(argv))
    try:
        out = subprocess.run(argv, check=True, capture_output=True, text=True).stdout
    except FileNotFoundError as exc:
        raise RuntimeError(
            "gcloud is not installed. It is a prerequisite of the hub bootstrap — "
            "see docs/runbooks/gcp-hub-bootstrap.md §2."
        ) from exc
    return [i["instance"].rsplit("/", 1)[-1] for i in json.loads(out or "[]")]


def status(config: dict[str, Any]) -> int:
    """Group state, instance state, and whether the MagicDNS name resolves.

    Three facts, because the interesting failures live between them. A MIG can
    report a healthy managed instance while the node never joined the mesh, and
    `gcp1.kubelab.internal` failing to resolve is what that looks like from
    outside. A `describe` alone reports the group's own opinion of itself.

    The `dig` is the one worth reading twice: Headscale names nodes by
    given-name, so a re-registration without stale-node cleanup lands as
    `gcp1-<random>` -- and the inventory, the kubeconfig and the prod
    EndpointSlice all break at once, silently, because the old records keep
    resolving until they do not.
    """
    from toolkit.features.k8s_render import resolve_magicdns

    code = _run(["gcloud", "compute", "instance-groups", "managed", "describe", *_scope(config)])
    if code != 0:
        return code

    instances = _list_instances(config)
    logger.info(f"instances: {', '.join(instances) if instances else '(none — the group is at target_size 0)'}")

    name = f"{_gcp(config)['hostname']}.kubelab.internal"
    address = resolve_magicdns(name)
    if address:
        logger.success(f"{name} -> {address}")
    else:
        # Not an error exit: a stopped hub is a legitimate state and its name
        # correctly does not resolve. Reported plainly so the reader decides.
        logger.warning(f"{name} does not resolve — expected while stopped, a finding while running")
    return 0


def resize(config: dict[str, Any], size: int) -> int:
    """Set the group's target size. 0 stops paying; 1 rebuilds through cloud-init.

    Refused outside [0, 1] BEFORE reaching gcloud, because gcloud would accept
    a larger number and the resulting second hub is not an error state anything
    else would notice.
    """
    if size < 0:
        raise ValueError(f"size {size} is negative; the target size is 0 or 1")
    if size > MAX_TARGET_SIZE:
        raise ValueError(
            f"size {size} exceeds {MAX_TARGET_SIZE}: the hub is a singleton, and two "
            f"Argo CD controllers reconciling one spoke is what the single-writer "
            f"invariant exists to prevent"
        )
    return _run(["gcloud", "compute", "instance-groups", "managed", "resize", *_scope(config), "--size", str(size)])


def recreate(config: dict[str, Any], timeout_s: int = RECREATE_TIMEOUT_S, poll_s: int = 10) -> int:
    """Delete the running instance, let the group rebuild it, and WAIT for it.

    The same path a preemption takes. An empty group is reported rather than
    passed to gcloud, which would succeed trivially and report a recreate that
    never happened.

    THE WAIT IS THE POINT, and it was missing. `gcloud recreate-instances`
    returns when the request is ACCEPTED, not when the machine has been
    replaced. Measured 2026-08-22 on the full `make gcp1-replace` chain: gcloud
    printed SUCCESS, `wait-node-ready` ran next and connected to the OLD VM --
    still alive, still answering -- and cached its host key. By `provision` the
    replacement had happened, the key had changed, and ssh hung for six minutes
    on its first probe.

    #1265's host-key purge is correct and did fire. What was wrong is WHEN:
    purging before the machine is actually replaced just caches the dying VM's
    key. Fixing the purge again would not help; the ordering is the defect.

    Completion is judged by the numeric `id`, because the NAME is preserved
    across a RECREATE by design. Done means: every instance reports an id that
    was not present before, `currentAction: NONE`, and `instanceStatus: RUNNING`
    -- the last because a STAGING instance has no sshd yet, so handing it to
    the next step reproduces the same hang for a different reason.
    """
    before = _managed_instances(config)
    if not before:
        raise RuntimeError(
            "the MIG holds no instance, so there is nothing to recreate. "
            "If the hub is stopped, `make gcp1-start` first."
        )
    old_ids = {i.get("id") for i in before}
    names = [i["instance"].rsplit("/", 1)[-1] for i in before]

    code = _run(
        [
            "gcloud",
            "compute",
            "instance-groups",
            "managed",
            "recreate-instances",
            *_scope(config),
            "--instances",
            ",".join(names),
        ]
    )
    if code != 0:
        return code

    logger.info(f"waiting for the group to replace {', '.join(names)} (ids {sorted(filter(None, old_ids))})")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        current = _managed_instances(config)
        if current and all(
            i.get("id") not in old_ids and i.get("currentAction") == "NONE" and i.get("instanceStatus") == "RUNNING"
            for i in current
        ):
            new_ids = sorted(str(i.get("id")) for i in current)
            logger.success(f"replaced — new instance id(s): {', '.join(new_ids)}")
            return 0
        time.sleep(poll_s)

    raise RuntimeError(
        f"the group did not replace {', '.join(names)} within {timeout_s}s. "
        "Returning here would hand the next step a machine that is about to be "
        "destroyed, which is how the host key goes stale mid-chain. "
        "Check `make gcp1-status` and the MIG's currentAction."
    )
