"""What the offsite backup destination holds, asked from off the node.

Every value comes from SSOT: `backup.r2` in `common.yaml` for the non-secrets,
SOPS for the credentials, so this never becomes a second place where the account
id or a bucket name is written down.

That a node's bucket is reachable, isolated and locked is proved by
`backup_isolation`; that its data restores, by `make backup-drill-node`. The
write/read/delete probes that lived here tested the shared bucket every node left
on 2026-10-08, and cannot move: a node bucket's lock refuses those deletes (#2917).
"""

from __future__ import annotations

import ipaddress
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from toolkit.core.logging import logger
from toolkit.features.backup_node_credentials import access_key_path, restic_password_path, secret_key_path
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.r2_tfvars import node_bucket

# SSOT paths. Changing a bucket or account means editing common.yaml, not this file.
_CFG_ROOT = ("backup", "r2")
_ACCESS_KEY_SECRET = "backup.r2.access_key_id"
_SECRET_KEY_SECRET = "backup.r2.secret_access_key"

_RESTIC_PASSWORD_SECRET = "backup.restic_password"

_TIMEOUT = 60

# (argv, env) -> (returncode, stdout, stderr). Injectable so the probes are
# testable without a network or a live credential.
RunFn = Callable[[list[str], dict[str, str]], "tuple[int, str, str]"]


@dataclass(frozen=True)
class DestinationConfig:
    """The non-secret half, resolved from common.yaml."""

    account_id: str
    bucket: str
    endpoint: str


class DestinationError(RuntimeError):
    """A precondition failed — missing config, missing credential, missing aws CLI."""


def _default_run(argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
    # The shell's AWS_* are dropped: an AWS_SESSION_TOKEN or AWS_PROFILE sent
    # along with an R2 pair makes R2 refuse it, and the refusal reads as a
    # wrong credential (TF-007 review).
    merged = {**{k: v for k, v in os.environ.items() if not k.startswith("AWS_")}, **env}
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=_TIMEOUT, env=merged, check=False)
    return proc.returncode, proc.stdout, proc.stderr


def load_destination(cm: ConfigurationManager) -> DestinationConfig:
    """Resolve `backup.r2` from the merged config, or explain what is missing."""
    node = cm.get_merged_config()
    for key in _CFG_ROOT:
        if not isinstance(node, dict) or key not in node:
            raise DestinationError(f"Missing '{'.'.join(_CFG_ROOT)}' in the config SSOT (common.yaml)")
        node = node[key]

    missing = [f for f in ("account_id", "bucket", "endpoint") if not node.get(f)]
    if missing:
        raise DestinationError(f"'{'.'.join(_CFG_ROOT)}' is missing: {', '.join(missing)}")

    return DestinationConfig(
        account_id=str(node["account_id"]),
        bucket=str(node["bucket"]),
        endpoint=str(node["endpoint"]),
    )


def load_credentials(
    cm: ConfigurationManager, access_path: str = _ACCESS_KEY_SECRET, secret_path: str = _SECRET_KEY_SECRET
) -> dict[str, str]:
    """Read an S3 pair from SOPS into an env mapping. Values are never logged."""
    access = cm.get_secret_by_path(access_path)
    secret = cm.get_secret_by_path(secret_path)

    absent = [p for p, v in ((access_path, access), (secret_path, secret)) if not v]
    if absent:
        raise DestinationError(
            f"Missing SOPS value(s): {', '.join(absent)}. "
            "Set them with `toolkit secrets set <path> --env common --stdin`."
        )

    return {
        "AWS_ACCESS_KEY_ID": str(access).strip(),
        "AWS_SECRET_ACCESS_KEY": str(secret).strip(),
        # R2 ignores region but the SDK requires one.
        "AWS_DEFAULT_REGION": "auto",
        # R2 rejects the newer default integrity headers on some operations.
        "AWS_REQUEST_CHECKSUM_CALCULATION": "when_required",
        "AWS_RESPONSE_CHECKSUM_VALIDATION": "when_required",
    }


# --- coverage: what is actually in R2, asked from off the node --------------
# BACKUP-044 AC1. "Verify every node-path consumer is present, by listing
# snapshots FROM A MACHINE THAT IS NOT THE SOURCE NODE. Reading the playbook is
# not verification."
#
# That last sentence is the whole design constraint. Every other control here
# runs ON the node whose backup it is checking, so it shares the node's fate: a
# node that is lying, broken or gone reports nothing, or reports what it
# believes. This asks the destination instead, from a workstation, and it works
# with the homelab powered off — which is when half the fleet cannot answer for
# itself.


def repository_name(cm: ConfigurationManager, node: str) -> str:
    """The R2 repository name for a node in `backup.sources`.

    NOT the same string as the `backup.sources` key, and the difference is not
    cosmetic. `node_backup_r2_repository` is built from `inventory_hostname`,
    and the inventory is not uniformly prefixed: the VPS is `kubelab-vps` while
    beelink, rpi3 and rpi4 carry no prefix.

    Verified against the live bucket 2026-08-22:

        PRE beelink/   PRE kubelab-vps/   PRE rpi3/   PRE rpi4/

    So a coverage report keyed on `backup.sources` alone would look for `vps/`,
    find nothing, and report the VPS as UNCOVERED while its backup ran nightly.
    The same regex the backup playbook uses, in reverse.
    """
    return _repository_name_in(cm.get_merged_config(), node)


def _node_entry(config: dict[str, Any], node: str) -> dict[str, Any]:
    """A node's `networking` entry: `networking.<node>` for cloud nodes (vps, aws,
    gcp), `networking.nodes.<node>` for the homelab — the same sibling-vs-member
    shape SSOT-014a keys off."""
    networking = config.get("networking", {})
    nodes = networking.get("nodes", {})
    entry = nodes.get(node) if node in nodes else networking.get(node, {})
    return entry or {}


def _repository_name_in(config: dict[str, Any], node: str) -> str:
    """`repository_name()` over an already-merged config, so a renderer needs no SOPS."""
    entry = _node_entry(config, node)
    # `hostname` IS the inventory name, verbatim, with no prefix rule to apply:
    # `networking.vps.hostname` is already `kubelab-vps` while every homelab node
    # is its own bare name. An earlier revision inferred the prefix from the
    # node's position instead of reading it, and produced `kubelab-kubelab-vps`
    # — reporting the VPS as UNCOVERED with a nightly backup sitting in R2.
    # Caught by running it, not by reading it.
    return str(entry.get("hostname") or node)


# Where the in-cluster watcher's targets live (BACKUP-055). Served to the
# CronJob through `configMapGenerator`; `render_watcher_targets` is the only
# writer, and `tests/test_r2_watcher_targets.py` fails on a stale copy.
WATCHER_TARGETS_PATH = "infra/k8s/base/services/r2-backup-watcher/targets.txt"

_WATCHER_TARGETS_HEADER = (
    "# Generated from backup.sources in common.yaml by `make sync-r2-watcher-targets`. Do not edit.\n"
    "# One line per node: <node> <restic repository URL> <repository id, or -> <tailscale ip> <probe port>\n"
    "#   <ADR-028 class> <declared source>...\n"
)


def _reachability(config: dict[str, Any], node: str) -> list[str]:
    """Where the probe knocks to tell "off" from "up and not shipping" (BACKUP-032).

    Raises on a node with no Tailscale IP or no class. Both would render a row
    that is silently wrong: no address reads as "always off", and no class is a
    node the freshness rule, which filters on it, never sees.
    """
    entry = _node_entry(config, node)
    missing = [field for field in ("tailscale_ip", "location") if not entry.get(field)]
    if missing:
        raise ValueError(f"node {node} has no networking {', '.join(missing)}: the watcher cannot judge it")
    watcher = (config.get("backup", {}) or {}).get("watcher", {}) or {}
    port = (watcher.get("reachability_ports") or {}).get(node) or watcher.get("reachability_port", 22)
    return [str(entry["tailscale_ip"]), str(port), str(entry["location"])]


# ── per-node buckets (BACKUP-057 PR 4) ──────────────────────────────────────
#
# A node moves from the shared bucket to its own by being listed in
# `backup.r2.own_bucket_nodes`, never by a merge: the list is edited at the
# migration sitting, once that node's copy is verified. Every consumer below
# asks these three functions, so no consumer can move a node on its own.


def own_bucket_nodes(config: dict[str, Any]) -> frozenset[str]:
    """The nodes already in a bucket of their own. Raises on a name that backs nothing up."""
    backup = config.get("backup", {}) or {}
    declared = (backup.get("r2", {}) or {}).get("own_bucket_nodes") or []
    unknown = sorted(set(declared) - set(backup.get("sources", {}) or {}))
    if unknown:
        raise ValueError(f"backup.r2.own_bucket_nodes names {', '.join(unknown)}, which is not in backup.sources")
    return frozenset(declared)


def node_repository(config: dict[str, Any], node: str) -> str:
    """The restic repository URL `node` ships to: its own bucket's root, or its prefix in the shared one."""
    r2 = (config.get("backup", {}) or {}).get("r2", {}) or {}
    if node in own_bucket_nodes(config):
        return f"s3:{str(r2['endpoint']).rstrip('/')}/{node_bucket(node)}"
    return f"{str(r2['repo_prefix']).rstrip('/')}/{_repository_name_in(config, node)}"


def node_secret_paths(config: dict[str, Any], node: str) -> tuple[str, str, str]:
    """SOPS paths of `node`'s access key, secret key and restic password."""
    if node in own_bucket_nodes(config):
        return access_key_path(node), secret_key_path(node), restic_password_path(node)
    return _ACCESS_KEY_SECRET, _SECRET_KEY_SECRET, _RESTIC_PASSWORD_SECRET


def watcher_password_paths(config: dict[str, Any]) -> dict[str, str]:
    """The watcher Secret's restic passwords: one `RESTIC_PASSWORD_<NODE>` per node, by SOPS path.

    A path, never a value: the Secret reads the node's own key, so rotating a
    node's password reaches the watcher on the next `apply-secrets`.
    """
    sources = (config.get("backup", {}) or {}).get("sources", {}) or {}
    paths = {}
    for node in sorted(sources):
        if not node.isidentifier():
            raise ValueError(f"backup node {node!r} cannot name an environment variable")
        paths[f"RESTIC_PASSWORD_{node.upper()}"] = node_secret_paths(config, node)[2]
    return paths


def render_watcher_targets(config: dict[str, Any]) -> str:
    """What the watcher must find in R2: per node, its repository, its id, where to
    knock, its class and its declared sources.

    Plain whitespace-separated lines, because the reader is `sh` in a restic
    image that has no YAML or JSON parser.
    """
    backup = config.get("backup", {}) or {}
    sources = backup.get("sources", {}) or {}
    # The full URL, not the bare name, so the R2 endpoint reaches the cluster
    # from the SSOT rather than as a second copy typed into the manifest.
    r2 = backup.get("r2", {}) or {}
    # BACKUP-058: the id pins which history the node's repository must be. `-`
    # keeps the column fixed for a node with none declared, which the probe
    # reports unhealthy rather than trusting whatever repository answers.
    repository_ids = r2.get("repository_ids", {}) or {}
    lines = [
        " ".join(
            [
                node,
                node_repository(config, node),
                str(repository_ids.get(node) or "-"),
                *_reachability(config, node),
                *sorted(sources[node] or {}),
            ]
        )
        for node in sorted(sources)
    ]
    return _WATCHER_TARGETS_HEADER + "\n".join(lines) + "\n"


def write_watcher_targets(project_root: Path, config: dict[str, Any]) -> bool:
    """Write the targets file. True if it changed."""
    target = project_root / WATCHER_TARGETS_PATH
    rendered = render_watcher_targets(config)
    if target.exists() and target.read_text(encoding="utf-8") == rendered:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")
    return True


# Where the edge watcher's targets live (NET-005 AC12). Same contract as the R2
# watcher's file: rendered from the SSOT, served through `configMapGenerator`,
# and `tests/test_edge_watcher_targets.py` fails on a stale copy.
EDGE_WATCHER_TARGETS_PATH = "infra/k8s/base/services/edge-watcher/targets.txt"

_EDGE_WATCHER_TARGETS_HEADER = (
    "# Generated from networking in common.yaml by `make sync-edge-watcher-targets`. Do not edit.\n"
    "# One line per target: <node> <tailscale ip> <probe port>\n"
)


def render_edge_watcher_targets(config: dict[str, Any]) -> str:
    """The edge and the always-on nodes behind it, where prod knocks to see them alive.

    The edge is the one node in the `gateway` Ansible group, a target whatever
    its class: it is the thing being watched. A node is behind it when its LAN
    address is in the homelab LAN or the lab Wi-Fi, and only an always-on one is
    a target, because an on-demand node is off whenever nobody is working.
    """
    networking = config.get("networking", {}) or {}
    nodes = networking.get("nodes", {}) or {}
    edges = sorted(name for name, entry in nodes.items() if "gateway" in ((entry or {}).get("ansible_groups") or []))
    if len(edges) != 1:
        raise ValueError(f"the edge watcher needs exactly one node in the gateway group, found {edges or 'none'}")
    networks = [
        ipaddress.ip_network(networking["lan_cidr"]),
        ipaddress.ip_network(networking["edge"]["lab_wifi"]["cidr"]),
    ]

    def behind_the_edge(entry: dict[str, Any]) -> bool:
        lan_ip = entry.get("lan_ip")
        return bool(lan_ip) and any(ipaddress.ip_address(str(lan_ip)) in network for network in networks)

    targets = set(edges) | {
        name
        for name, entry in nodes.items()
        if entry and entry.get("location") == "always-on" and behind_the_edge(entry)
    }
    # `_reachability` refuses a node with no Tailscale IP: prod reaches the edge
    # only over the tailnet, so such a row could only ever read "down".
    lines = [" ".join([node, *_reachability(config, node)[:2]]) for node in sorted(targets)]
    return _EDGE_WATCHER_TARGETS_HEADER + "\n".join(lines) + "\n"


def write_edge_watcher_targets(project_root: Path, config: dict[str, Any]) -> bool:
    """Write the edge watcher's targets file. True if it changed."""
    target = project_root / EDGE_WATCHER_TARGETS_PATH
    rendered = render_edge_watcher_targets(config)
    if target.exists() and target.read_text(encoding="utf-8") == rendered:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")
    return True


def node_restic(cm: ConfigurationManager, node: str) -> tuple[str, dict[str, str]]:
    """One node's repository URL and the env restic needs to read it. Values are never logged.

    Resolved through `node_repository` and `node_secret_paths`, so a node in its
    own bucket is read with its own pair and password, never the shared ones.
    """
    config = cm.get_merged_config()
    try:
        repo = node_repository(config, node)
        access, secret, password_path = node_secret_paths(config, node)
    except (KeyError, ValueError) as exc:
        raise DestinationError(f"backup.r2 cannot resolve {node}'s repository: {exc}") from exc
    credentials = load_credentials(cm, access, secret)
    password = cm.get_secret_by_path(password_path)
    if not password:
        raise DestinationError(f"Missing SOPS value at '{password_path}' — {node}'s repository cannot be read.")
    return repo, {**credentials, "RESTIC_PASSWORD": str(password).strip()}


def cluster_node(config: dict[str, Any]) -> Optional[str]:
    """The node in `k3s_servers` for this env's merged config, or None if not exactly one.

    The key matches `backup.sources`: `networking.vps` is `vps`, `networking.nodes.ace1` is `ace1`.
    """
    networking = config.get("networking", {}) or {}
    candidates = {key: value for key, value in networking.items() if key != "nodes"}
    candidates.update(networking.get("nodes", {}) or {})
    found = [
        name
        for name, node in candidates.items()
        if isinstance(node, dict) and "k3s_servers" in (node.get("ansible_groups") or [])
    ]
    return found[0] if len(found) == 1 else None


def _claims_in(entries: Optional[dict[str, Any]]) -> set[tuple[str, str]]:
    return {
        (e["pvc"]["namespace"], e["pvc"]["claim"])
        for e in (entries or {}).values()
        if isinstance(e, dict) and isinstance(e.get("pvc"), dict)
    }


def unruled_claims(backup: dict[str, Any], node: str, live: set[tuple[str, str]]) -> list[tuple[str, str]]:
    """Live claims that are neither a backup source nor an exclusion on `node`."""
    ruled = _claims_in((backup.get("sources") or {}).get(node)) | _claims_in((backup.get("excluded") or {}).get(node))
    return sorted(live - ruled)


def check_claim_rulings(config: dict[str, Any], kubeconfig: Path, run: RunFn) -> bool:
    """BACKUP-046 AC4: every claim the cluster holds has a ruling in `backup`.

    The static guard reads the rendered overlay. This reads the cluster, which also
    holds claims nothing in the overlay declares (`kube-system/traefik`, from K3s's
    own chart). Every way of not looking is CANNOT CHECK and returns False.
    """
    import json

    backup = config.get("backup", {}) or {}
    node = cluster_node(config)
    if node is None:
        logger.error("claims: CANNOT CHECK — no single node is in k3s_servers for this env")
        return False
    if node not in ((backup.get("sources") or {}) | (backup.get("excluded") or {})):
        logger.warning(f"claims: cluster node '{node}' declares no backups in this env; rulings not checked")
        return True
    if not kubeconfig.is_file():
        logger.error(f"claims: CANNOT CHECK — no kubeconfig at {kubeconfig} (make kubeconfig ENV=<env>)")
        return False

    rc, out, err = run(["kubectl", "--kubeconfig", str(kubeconfig), "get", "pvc", "--all-namespaces", "-o", "json"], {})
    try:
        items = json.loads(out or "{}").get("items", []) if rc == 0 else []
    except json.JSONDecodeError:
        items = []
    if not items:
        # A cluster with state always holds claims, so zero means the read failed.
        reason = err.strip()[:160] if rc != 0 else "the cluster returned no claims"
        logger.error(f"claims: CANNOT CHECK — {reason}")
        return False

    live = {(i["metadata"]["namespace"], i["metadata"]["name"]) for i in items}
    missing = unruled_claims(backup, node, live)
    for namespace, claim in missing:
        logger.error(
            f"claims: {namespace}/{claim} has no ruling — declare it in backup.sources.{node} "
            f"or in backup.excluded.{node} with a reason and tier: 3"
        )
    if not missing:
        logger.success(f"claims: all {len(live)} live claims on '{node}' have a backup ruling")
    return not missing


def coverage(
    env: str = "prod",
    project_root: Optional[Path] = None,
    cm: Optional[ConfigurationManager] = None,
    run: Optional[RunFn] = None,
    kubeconfig: Optional[Path] = None,
) -> bool:
    """Report the newest snapshot per declared node, read from R2, then the claim rulings.

    Answers "does every node that should have a backup actually have one, and
    how old is it" — the question AC1 asks, from where AC1 requires it be asked.

    Returns False when any declared node has no repository or no snapshot. It
    does NOT judge age: the two node classes have different expectations (a
    4-hour wall-clock schedule vs. hourly-while-up on hardware that is off most
    of the week), and that judgement is the coverage monitor's job in Uptime
    Kuma (AC9), which knows the class. Printing the age and letting the operator
    read it keeps one control from silently disagreeing with the other.
    """
    logger.section("backup coverage — snapshots per node, read from R2")

    cm = cm or ConfigurationManager(env, project_root)
    run = run or _default_run

    declared = sorted((cm.get_merged_config().get("backup", {}) or {}).get("sources", {}) or {})
    if not declared:
        logger.error("No nodes declared in backup.sources — nothing to report on.")
        return False

    rc, _, err = run(["restic", "version"], {})
    if rc != 0:
        logger.error(f"restic is required and was not runnable: {err.strip()}")
        return False

    import json
    from datetime import datetime, timezone

    ok = True
    for node in declared:
        try:
            repo, renv = node_restic(cm, node)
        except DestinationError as exc:
            logger.error(f"{node:10} UNREADABLE — {exc}")
            ok = False
            continue
        rc, out, err = run(["restic", "-r", repo, "snapshots", "--json", "--latest", "1"], renv)
        if rc != 0:
            # A repository that does not exist and one that cannot be read are
            # the same verdict here — uncovered — but the message says which,
            # because the remedies differ entirely.
            reason = "no repository" if "does not exist" in (err or "").lower() else err.strip()[:120]
            logger.error(f"{node:10} UNCOVERED — {reason}")
            ok = False
            continue

        try:
            snapshots = json.loads(out or "[]")
        except json.JSONDecodeError:
            logger.error(f"{node:10} UNREADABLE — restic returned no usable JSON")
            ok = False
            continue

        if not snapshots:
            logger.error(f"{node:10} UNCOVERED — repository exists, zero snapshots")
            ok = False
            continue

        newest = snapshots[0]
        # restic stamps a snapshot with the SOURCE NODE's local offset, and the
        # fleet is not uniformly UTC — the VPS runs UTC while beelink, rpi3 and
        # rpi4 run CEST. `fromisoformat` keeps that offset, so the conversion to
        # UTC has to be explicit before a `Z` may be appended. Formatting the
        # parsed value directly printed a homelab wall clock labelled as UTC:
        # measured 2026-08-23, rpi3's newest snapshot reported as `04:01Z
        # (0.2h ago)` at 02:11Z — a timestamp two hours in the future beside a
        # correct age, because only the display dropped the offset.
        when = datetime.fromisoformat(newest["time"].replace("Z", "+00:00")).astimezone(timezone.utc)
        age = datetime.now(timezone.utc) - when
        hours = age.total_seconds() / 3600
        logger.success(
            f"{node:10} covered — newest {when.strftime('%Y-%m-%d %H:%M')}Z "
            f"({hours:.1f}h ago), {len(newest.get('paths') or [])} path(s)"
        )

    if kubeconfig is None:
        from toolkit.features.k8s_kubeconfig import output_path

        kubeconfig = output_path(env)
    return check_claim_rulings(cm.get_merged_config(), kubeconfig, run) and ok
