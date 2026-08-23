"""BACKUP-044 offsite-destination verification.

Proves the R2 bucket is usable *before* a backup pipeline depends on it, and
keeps proving it afterwards. Every value comes from SSOT — `backup.r2` in
`common.yaml` for the non-secrets, SOPS for the credentials — so this never
becomes a second place where the account id or bucket name is written down.

The probes, in the order they matter:

1. **Scope.** A correctly scoped token is REFUSED `ListBuckets` while still
   reaching its own bucket. Both outcomes are reported: an account-wide token is
   not a hard failure, but it means a leak of this credential reaches every
   bucket in the account, and that should be a decision rather than a surprise.
2. **Reach.** The target bucket lists.
3. **Round-trip.** Write, read back, compare SHA-256, then DELETE.

Delete is the probe that earns this module. A read-write token *without* delete
lets backups run green for weeks: the failure only surfaces the first time
`restic forget`/`prune` tries to reclaim space, by which point the bucket is full
and the retention policy has never once retained anything. It is invisible to any
check that only asserts "a recent object exists".

The object written is 1 KB of throwaway data under a `_smoketest/` prefix, and it
is removed. Nothing real is uploaded: the first object in an unproven destination
should be the least valuable thing available, not the most.
"""

from __future__ import annotations

import hashlib
import os
import secrets as _secrets
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from toolkit.core.logging import logger
from toolkit.features.configuration import ConfigurationManager

# SSOT paths. Changing a bucket or account means editing common.yaml, not this file.
_CFG_ROOT = ("backup", "r2")
_ACCESS_KEY_SECRET = "backup.r2.access_key_id"
_SECRET_KEY_SECRET = "backup.r2.secret_access_key"

_RESTIC_PASSWORD_SECRET = "backup.restic_password"

_SMOKE_PREFIX = "_smoketest"
_PROBE_BYTES = 1024
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
    merged = {**os.environ, **env}
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


def load_credentials(cm: ConfigurationManager) -> dict[str, str]:
    """Read the S3 credentials from SOPS into an env mapping. Values are never logged."""
    access = cm.get_secret_by_path(_ACCESS_KEY_SECRET)
    secret = cm.get_secret_by_path(_SECRET_KEY_SECRET)

    absent = [p for p, v in ((_ACCESS_KEY_SECRET, access), (_SECRET_KEY_SECRET, secret)) if not v]
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


def verify_destination(
    env: str = "common",
    project_root: Optional[Path] = None,
    cm: Optional[ConfigurationManager] = None,
    run: Optional[RunFn] = None,
) -> bool:
    """Probe the offsite backup destination end to end. True iff every probe passed.

    Reports the token's scope rather than asserting it: an account-wide token is a
    finding, not a failure.
    """
    logger.section("backup destination — Cloudflare R2")

    cm = cm or ConfigurationManager(env if env != "common" else "prod", project_root)
    run = run or _default_run

    try:
        dest = load_destination(cm)
        credentials = load_credentials(cm)
    except DestinationError as exc:
        logger.error(str(exc))
        return False

    logger.info(f"Bucket:   {dest.bucket}")
    logger.info(f"Endpoint: {dest.endpoint}")

    base = ["aws", "--endpoint-url", dest.endpoint]
    rc, _, err = run(["aws", "--version"], {})
    if rc != 0:
        logger.error(f"The aws CLI is required and was not runnable: {err.strip()}")
        return False

    ok = True

    # 1. Scope — informational, never fatal.
    rc, out, _ = run([*base, "s3api", "list-buckets"], credentials)
    if rc == 0:
        logger.warning("Token is ACCOUNT-WIDE: ListBuckets succeeded, so a leak reaches every bucket")
    else:
        logger.success("Token is bucket-scoped: ListBuckets refused, as it should be")

    # 2. Reach.
    rc, _, err = run([*base, "s3", "ls", f"s3://{dest.bucket}"], credentials)
    if rc != 0:
        logger.error(f"Cannot list s3://{dest.bucket}: {err.strip().splitlines()[-1] if err.strip() else rc}")
        return False
    logger.success(f"Bucket {dest.bucket} is reachable")

    # 3. Round-trip, including the delete that everything downstream depends on.
    key = f"{_SMOKE_PREFIX}/verify-{int(time.time())}-{_secrets.token_hex(4)}.bin"
    payload = _secrets.token_bytes(_PROBE_BYTES)
    expected = hashlib.sha256(payload).hexdigest()

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "probe.bin"
        dst = Path(tmp) / "probe.back"
        src.write_bytes(payload)

        rc, _, err = run([*base, "s3", "cp", str(src), f"s3://{dest.bucket}/{key}"], credentials)
        if rc != 0:
            logger.error(f"write FAILED: {err.strip()}")
            return False
        logger.success("write")

        rc, _, err = run([*base, "s3", "cp", f"s3://{dest.bucket}/{key}", str(dst)], credentials)
        if rc != 0:
            logger.error(f"read FAILED: {err.strip()}")
            ok = False
        else:
            logger.success("read")
            if hashlib.sha256(dst.read_bytes()).hexdigest() == expected:
                logger.success("integrity (sha256 match)")
            else:
                logger.error("integrity FAILED — content differs from what was written")
                ok = False

        rc, _, err = run([*base, "s3", "rm", f"s3://{dest.bucket}/{key}"], credentials)
        if rc != 0:
            logger.error(
                "delete FAILED — restic forget/prune will not work with this token, "
                "and backups will appear healthy until the bucket fills"
            )
            return False
        logger.success("delete")

    return ok


def repo_url(dest: DestinationConfig, node: str) -> str:
    """restic repository URL for one node.

    One repository per node, so a compromised node cannot rewrite another's
    history — and so a restore only needs the credentials for the node being
    restored.
    """
    return f"s3:{dest.endpoint}/{dest.bucket}/{node}"


def verify_restic(
    node: str = f"{_SMOKE_PREFIX}-probe",
    env: str = "prod",
    project_root: Optional[Path] = None,
    cm: Optional[ConfigurationManager] = None,
    run: Optional[RunFn] = None,
    keep: bool = False,
) -> bool:
    """Prove restic can create, use and verify a repository in R2.

    Runs the full lifecycle against a throwaway repository: init, backup a small
    file, list snapshots, `restic check`, then remove the repository unless
    `keep`. This is the step that turns "the bucket accepts objects" into "restic
    works here" — they are different claims, and only the second one matters.
    """
    logger.section("backup destination — restic lifecycle")

    cm = cm or ConfigurationManager(env, project_root)
    run = run or _default_run

    try:
        dest = load_destination(cm)
        credentials = load_credentials(cm)
    except DestinationError as exc:
        logger.error(str(exc))
        return False

    password = cm.get_secret_by_path(_RESTIC_PASSWORD_SECRET)
    if not password:
        logger.error(
            f"Missing SOPS value at '{_RESTIC_PASSWORD_SECRET}' — generate it with `make backup-generate-password`."
        )
        return False

    # RESTIC_PASSWORD is read from the environment, never passed as an argument,
    # so it stays out of the process list.
    renv = {**credentials, "RESTIC_PASSWORD": str(password).strip()}
    repo = repo_url(dest, node)
    logger.info(f"Repository: {repo}")

    rc, _, err = run(["restic", "version"], {})
    if rc != 0:
        logger.error(f"restic is required and was not runnable: {err.strip()}")
        return False

    base = ["restic", "-r", repo]

    rc, _, err = run([*base, "init"], renv)
    if rc != 0 and "already initialized" not in (err or "").lower():
        logger.error(f"init FAILED: {err.strip()}")
        return False
    logger.success("init")

    import tempfile

    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        sample = Path(tmp) / "probe.txt"
        sample.write_text("BACKUP-044 restic lifecycle probe\n", encoding="utf-8")

        rc, _, err = run([*base, "backup", str(sample)], renv)
        if rc != 0:
            logger.error(f"backup FAILED: {err.strip()}")
            ok = False
        else:
            logger.success("backup")

        rc, out, err = run([*base, "snapshots", "--json"], renv)
        if rc != 0 or not out.strip():
            logger.error(f"snapshots FAILED: {err.strip()}")
            ok = False
        else:
            logger.success("snapshots listed")

        # The claim AC7 rests on: the repository is internally consistent.
        rc, _, err = run([*base, "check"], renv)
        if rc != 0:
            logger.error(f"check FAILED: {err.strip()}")
            ok = False
        else:
            logger.success("check")

    if keep:
        logger.info("Repository kept (--keep)")
        return ok

    rc, _, err = run(
        ["aws", "--endpoint-url", dest.endpoint, "s3", "rm", f"s3://{dest.bucket}/{node}", "--recursive"],
        credentials,
    )
    if rc != 0:
        logger.warning(f"Could not remove the probe repository at {node}/ — remove it by hand")
    else:
        logger.success("probe repository removed")

    return ok


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
    config = cm.get_merged_config()
    networking = config.get("networking", {})
    nodes = networking.get("nodes", {})
    # `networking.<node>` for cloud nodes (vps, aws, gcp), `networking.nodes.<node>`
    # for the homelab — the same sibling-vs-member shape SSOT-014a keys off.
    entry = nodes.get(node) if node in nodes else networking.get(node, {})
    # `hostname` IS the inventory name, verbatim, with no prefix rule to apply:
    # `networking.vps.hostname` is already `kubelab-vps` while every homelab node
    # is its own bare name. An earlier revision inferred the prefix from the
    # node's position instead of reading it, and produced `kubelab-kubelab-vps`
    # — reporting the VPS as UNCOVERED with a nightly backup sitting in R2.
    # Caught by running it, not by reading it.
    return str((entry or {}).get("hostname") or node)


def coverage(
    env: str = "prod",
    project_root: Optional[Path] = None,
    cm: Optional[ConfigurationManager] = None,
    run: Optional[RunFn] = None,
) -> bool:
    """Report the newest snapshot per declared node, read from R2.

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

    try:
        dest = load_destination(cm)
        credentials = load_credentials(cm)
    except DestinationError as exc:
        logger.error(str(exc))
        return False

    password = cm.get_secret_by_path(_RESTIC_PASSWORD_SECRET)
    if not password:
        logger.error(
            f"Missing SOPS value at '{_RESTIC_PASSWORD_SECRET}' — generate it with `make backup-generate-password`."
        )
        return False

    declared = sorted((cm.get_merged_config().get("backup", {}) or {}).get("sources", {}) or {})
    if not declared:
        logger.error("No nodes declared in backup.sources — nothing to report on.")
        return False

    renv = {**credentials, "RESTIC_PASSWORD": str(password).strip()}
    rc, _, err = run(["restic", "version"], {})
    if rc != 0:
        logger.error(f"restic is required and was not runnable: {err.strip()}")
        return False

    import json
    from datetime import datetime, timezone

    ok = True
    for node in declared:
        repo = repo_url(dest, repository_name(cm, node))
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

    return ok
