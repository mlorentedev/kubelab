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
from typing import Any

from toolkit.core.logging import logger

# The hub is a singleton by design: two Argo CD controllers reconciling one spoke
# is the exact failure `managed_spokes` exists to prevent, and a fat-fingered
# size is the cheapest way to cause it.
MAX_TARGET_SIZE = 1


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


def recreate(config: dict[str, Any]) -> int:
    """Delete the running instance and let the group rebuild it.

    The same path a preemption takes. An empty group is reported rather than
    passed to gcloud, which would succeed trivially and report a recreate that
    never happened.
    """
    instances = _list_instances(config)
    if not instances:
        raise RuntimeError(
            "the MIG holds no instance, so there is nothing to recreate. "
            "If the hub is stopped, `make gcp1-start` first."
        )
    return _run(
        [
            "gcloud",
            "compute",
            "instance-groups",
            "managed",
            "recreate-instances",
            *_scope(config),
            "--instances",
            ",".join(instances),
        ]
    )
