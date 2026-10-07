"""Move one node's restic history into its own bucket (BACKUP-057 AC4).

`restic copy` reads the source repository with the same `AWS_*` it writes the
destination with, and no standing pair holds both: the shared one cannot write
a node bucket and a node's cannot read `kubelab-backups`. So the copy runs under
a temporary token, Object Read on the shared bucket and Object Read & Write on
this node's, minted for the copy, proven by consequence before it is used, and
revoked when the copy has been compared, whatever happened. It is never stored.

Then the node moves, in this order, stopping at the first failure:
  1. it is declared in `backup.r2.own_bucket_nodes`, so every consumer resolves
     its own bucket and secrets;
  2. `backup` deploys that to the node;
  3. `backup-repo-reinit` journals and clears the node's recorded repository id;
  4. `backup-node` ships once, and the node records the copied repository's id;
  5. that id is pinned in `backup.r2.repository_ids` and the watcher targets are
     regenerated.
The deploy precedes the reinit: a scheduled ship that lands between them then
refuses the new repository and pages, where the other order would let it record
the OLD repository's id and fail the migration's own ship.
"""

from __future__ import annotations

import copy as _copy
import json
import time
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

from toolkit.core.logging import logger
from toolkit.features.backup_destination import (
    RunFn,
    _repository_name_in,
    load_credentials,
    node_repository,
    node_secret_paths,
    own_bucket_nodes,
    write_watcher_targets,
)
from toolkit.features.backup_node_credentials import (
    MINTER_KEY,
    READ_GROUP,
    WRITE_GROUP,
    HttpFn,
    MintError,
    _s3_env,
    _scope_error,
    bucket_resource,
    cloudflare_http,
    permission_group_id,
)
from toolkit.features.r2_tfvars import node_bucket

TOKEN_PREFIX = "kubelab-backup-migrate-"
# The shared runner stops a call at 60 s; copying a node's history takes minutes.
COPY_TIMEOUT_S = 3600
# The line `pin` rewrites: the node's entry under `backup.r2.repository_ids`.
PIN_LINE = r"^(      {node}:) [0-9a-f]{{64}}"
# (playbook, limit, extra vars) -> success
PlaybookFn = Callable[[str, str, dict[str, str]], bool]


class Values(Protocol):
    def pinnable(self, node: str) -> bool: ...

    def declare(self, node: str) -> None: ...

    def pin(self, node: str, repository_id: str) -> None: ...


def migration_token_request(
    node: str, *, legacy_bucket: str, account_id: str, read_group_id: str, write_group_id: str
) -> dict[str, Any]:
    """Object Read on the shared bucket and Object Read & Write on `node`'s, nothing else."""
    return {
        "name": f"{TOKEN_PREFIX}{node}",
        "policies": [
            {
                "effect": "allow",
                "resources": {bucket_resource(account_id, legacy_bucket): "*"},
                "permission_groups": [{"id": read_group_id}],
            },
            {
                "effect": "allow",
                "resources": {bucket_resource(account_id, node_bucket(node)): "*"},
                "permission_groups": [{"id": write_group_id}],
            },
        ],
    }


def unmatched_snapshots(source: list[dict[str, Any]], copied: list[dict[str, Any]]) -> list[str]:
    """Source snapshot ids without exactly one copy.

    `restic copy` stamps each copy's `original` with its source's `original`, or
    with the source's id when it has none. A count and an oldest time can agree
    while one snapshot is missing and another doubled; this cannot.
    """
    copies: dict[str, int] = {}
    for snap in copied:
        key = snap.get("original")
        if key:
            copies[key] = copies.get(key, 0) + 1
    return [s["id"] for s in source if copies.get(s.get("original") or s["id"], 0) != 1]


class ValuesFile:
    """`common.yaml`, edited one line at a time.

    A round-trip YAML dump re-indents the whole 2,000-line file; these two keys
    each live on a line of their own, so the edit replaces that line, and the
    result is read back and compared before it is written.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def _replace(self, pattern: str, line: str, check: Callable[[dict[str, Any]], bool]) -> None:
        import re

        import yaml

        text = self.path.read_text()
        # A trailing comment on the edited line is kept: only the value is replaced.
        edited, count = re.subn(pattern + r"(\s+#.*)?$", line + r"\g<2>", text, count=1, flags=re.MULTILINE)
        if count != 1:
            raise ValueError(f"{self.path}: no line matches {pattern!r}")
        if not check(yaml.safe_load(edited)["backup"]["r2"]):
            raise ValueError(f"{self.path}: the edit did not produce the expected value")
        self.path.write_text(edited)

    def pinnable(self, node: str) -> bool:
        """Whether `pin` will find the node's line, so a run that cannot finish never starts."""
        import re

        return re.search(PIN_LINE.format(node=node), self.path.read_text(), flags=re.MULTILINE) is not None

    def declare(self, node: str) -> None:
        import yaml

        current = (yaml.safe_load(self.path.read_text())["backup"]["r2"].get("own_bucket_nodes")) or []
        nodes = sorted({*current, node})
        self._replace(
            r"^(    own_bucket_nodes:) [^#\n]*?",
            rf"\1 [{', '.join(nodes)}]",
            lambda r2: r2["own_bucket_nodes"] == nodes,
        )

    def pin(self, node: str, repository_id: str) -> None:
        self._replace(
            PIN_LINE.format(node=node),
            rf"\1 {repository_id}",
            lambda r2: r2["repository_ids"][node] == repository_id,
        )


def _default_playbook(name: str, limit: str, extra_vars: dict[str, str]) -> bool:
    import typer

    from toolkit.cli.infra import ansible_run

    extra = " ".join(f"{k}={v}" for k, v in extra_vars.items()) or None
    try:
        ansible_run(playbook=name, env="prod", limit=limit, extra_vars=extra)
    except typer.Exit as exc:
        return exc.exit_code == 0
    return True


def _long_run(argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
    import os
    import subprocess

    proc = subprocess.run(
        argv, capture_output=True, text=True, timeout=COPY_TIMEOUT_S, env={**os.environ, **env}, check=False
    )
    return proc.returncode, proc.stdout, proc.stderr


def _snapshots(run: RunFn, repo: str, env: dict[str, str]) -> Optional[list[dict[str, Any]]]:
    rc, out, err = run(["restic", "-r", repo, "snapshots", "--json", "--no-lock"], env)
    if rc != 0:
        logger.error(f"snapshots on {repo} failed: {err.strip()}")
        return None
    return json.loads(out or "[]")


def _copy_under_token(
    node: str,
    *,
    src: str,
    dst: str,
    src_password: str,
    dst_password: str,
    r2: dict[str, Any],
    refused: str,
    run: RunFn,
    http: HttpFn,
    sleep: Callable[[float], None],
) -> bool:
    """Mint the temporary token, copy, compare, and revoke the token whatever happened."""
    account_id, endpoint, legacy = str(r2["account_id"]), str(r2["endpoint"]), str(r2["bucket"])
    body = migration_token_request(
        node,
        legacy_bucket=legacy,
        account_id=account_id,
        read_group_id=permission_group_id(http, account_id, READ_GROUP),
        write_group_id=permission_group_id(http, account_id, WRITE_GROUP),
    )
    import hashlib

    result = http("POST", f"/accounts/{account_id}/tokens", body)
    token_id = str(result["id"])
    s3 = _s3_env(token_id, hashlib.sha256(str(result["value"]).encode()).hexdigest())
    try:
        problem = _scope_error(f"{node}'s migration", endpoint, [legacy, node_bucket(node)], refused, s3, run, sleep)
        if problem:
            logger.error(problem)
            return False
        copy_env = {**s3, "RESTIC_PASSWORD": dst_password, "RESTIC_FROM_PASSWORD": src_password}
        rc, _, err = run(["restic", "-r", dst, "init", "--copy-chunker-params", "--from-repo", src], copy_env)
        if rc != 0 and "already" not in err.lower():
            logger.error(f"init of {dst} failed: {err.strip()}")
            return False
        rc, _, err = run(["restic", "-r", dst, "copy", "--from-repo", src], copy_env)
        if rc != 0:
            logger.error(f"copy into {dst} failed: {err.strip()}")
            return False
        source = _snapshots(run, src, {**s3, "RESTIC_PASSWORD": src_password})
        copied = _snapshots(run, dst, {**s3, "RESTIC_PASSWORD": dst_password})
        if source is None or copied is None:
            return False
        if not source:
            # An empty comparison would report a verified copy that measured nothing.
            logger.error(f"{src} lists no snapshots: there is no history to move, and nothing to verify a copy against")
            return False
        missing = unmatched_snapshots(source, copied)
        if missing:
            logger.error(f"{len(missing)} of {len(source)} source snapshots lack exactly one copy: {missing}")
            return False
        logger.success(f"{len(source)} source snapshots, each with exactly one copy in {dst}")
        return True
    finally:
        http("DELETE", f"/accounts/{account_id}/tokens/{token_id}", None)
        logger.info(f"temporary token {TOKEN_PREFIX}{node} revoked")


def migrate(
    node: str,
    *,
    env: str,
    check: bool = False,
    cm: Any = None,
    run: Optional[RunFn] = None,
    http: Optional[HttpFn] = None,
    playbook: Optional[PlaybookFn] = None,
    values: Optional[Values] = None,
    regenerate: Optional[Callable[[dict[str, Any]], Any]] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Move `node` into `kubelab-backup-<node>`. True iff every step passed."""
    logger.section(f"backup migrate — {node}")
    if env != "prod":
        logger.error(f"the node buckets are prod's; refusing --env {env}")
        return False
    if cm is None:
        from toolkit.features.configuration import ConfigurationManager

        cm = ConfigurationManager(env)
    run = run or _long_run
    config = cm.get_merged_config()
    sources = (config.get("backup", {}) or {}).get("sources", {}) or {}
    if node not in sources:
        logger.error(f"{node!r} is not a backup.sources node ({', '.join(sorted(sources))})")
        return False
    if node in own_bucket_nodes(config):
        logger.error(f"{node} is already in backup.r2.own_bucket_nodes")
        return False

    declared = _copy.deepcopy(config)
    r2 = declared["backup"]["r2"]
    r2["own_bucket_nodes"] = sorted({*(r2.get("own_bucket_nodes") or []), node})
    src, dst = node_repository(config, node), node_repository(declared, node)
    src_password = cm.get_secret_by_path(node_secret_paths(config, node)[2])
    access, secret, dst_password_path = node_secret_paths(declared, node)
    dst_password = cm.get_secret_by_path(dst_password_path)
    if not src_password or not dst_password:
        logger.error("a restic password is missing from SOPS; nothing was copied")
        return False
    host = _repository_name_in(config, node)
    logger.info(f"{src} -> {dst}")
    # Everything that can refuse the run is asked before anything is minted or
    # written, and the dry run asks exactly the same questions.
    values = values or ValuesFile(cm.project_root / "infra/config/values/common.yaml")
    if not values.pinnable(node):
        logger.error(f"backup.r2.repository_ids has no 64-hex entry for {node}, so its new id could not be pinned")
        return False
    source = _snapshots(run, src, {**load_credentials(cm), "RESTIC_PASSWORD": str(src_password)})
    if source is None:
        return False
    if not source:
        logger.error(f"{src} lists no snapshots: there is no history to move; nothing was minted or copied")
        return False
    if check:
        logger.info(f"dry run: {len(source)} snapshots would be copied; nothing was minted, copied or deployed")
        return True

    minter = cm.get_secret_by_path(MINTER_KEY)
    if not minter:
        logger.error(f"{MINTER_KEY} is absent from SOPS; the copy's token cannot be minted")
        return False
    refused = node_bucket(next(n for n in sorted(sources) if n != node))
    try:
        copied = _copy_under_token(
            node,
            src=src,
            dst=dst,
            src_password=str(src_password),
            dst_password=str(dst_password),
            r2=r2,
            refused=refused,
            run=run,
            http=http or cloudflare_http(str(minter)),
            sleep=sleep,
        )
    except MintError as exc:
        logger.error(str(exc))
        return False
    if not copied:
        return False

    playbook = playbook or _default_playbook
    values.declare(node)
    for name, extra in (("backup", {}), ("backup-repo-reinit", {"dest": "r2"}), ("backup-node", {})):
        if not playbook(name, host, extra):
            logger.error(f"{name} failed on {host}; the node is declared but not pinned. Fix, then re-run from {name}.")
            return False

    node_env = {**load_credentials(cm, access, secret), "RESTIC_PASSWORD": str(dst_password)}
    rc, out, err = run(["restic", "-r", dst, "cat", "config", "--json", "--no-lock"], node_env)
    if rc != 0:
        logger.error(f"reading {dst}'s repository id failed: {err.strip()}")
        return False
    repository_id = str(json.loads(out)["id"])
    values.pin(node, repository_id)
    r2["repository_ids"] = {**(r2.get("repository_ids") or {}), node: repository_id}
    (regenerate or (lambda c: write_watcher_targets(cm.project_root, c)))(declared)
    logger.success(f"{node} is in {node_bucket(node)}; commit common.yaml and targets.txt in a PR")
    return True
