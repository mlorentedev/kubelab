"""Check that the offsite escrow holds the restic passwords SOPS holds (BACKUP-057 AC5).

The escrow is a Bitwarden entry per password, the one copy that survives the
loss of the age key. Nothing else reads it, so a rotation that skipped it goes
unnoticed until the day it is the only way in. This compares fingerprints, never
values: `dotf secrets probe` reports the escrow's sha256[:12] without printing
the value, and the SOPS side is hashed here the same way.
"""

from __future__ import annotations

import hashlib
import re
from typing import Callable, Optional

from toolkit.core.logging import logger
from toolkit.features.backup_destination import _RESTIC_PASSWORD_SECRET, RunFn
from toolkit.features.backup_node_credentials import restic_password_path

ESCROW_PREFIX = "KUBELAB_RESTIC_PASSWORD"
# The registry maps each entry's `password` field to the login's password.
_PASSWORD_LINE = re.compile(r"^\s*data\.login\.password\s+len=\d+\s+([0-9a-f]{12})\s*$", re.MULTILINE)


def escrow_id(node: Optional[str]) -> str:
    """The `dotf` registry id: the shared password's, or `node`'s own."""
    return ESCROW_PREFIX if node is None else f"{ESCROW_PREFIX}_{node.upper()}"


def fingerprint(value: str) -> str:
    """The same sha256[:12] `dotf` reports."""
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def check(nodes: list[str], *, secret: Callable[[str], Optional[str]], run: RunFn) -> bool:
    """True iff every restic password in SOPS has a matching escrow entry."""
    entries = [(None, _RESTIC_PASSWORD_SECRET)] + [(n, restic_password_path(n)) for n in nodes]
    ok = True
    for node, path in entries:
        entry = escrow_id(node)
        value = secret(path)
        if not value:
            logger.error(f"{path}: MISSING in SOPS, so there is nothing to compare {entry} with")
            ok = False
            continue
        rc, out, err = run(["dotf", "secrets", "probe", entry], {})
        if rc != 0:
            logger.error(
                f"{entry}: the escrow is unreadable ({err.strip()}). Is Bitwarden locked? `dotf secrets unlock`"
            )
            ok = False
            continue
        match = _PASSWORD_LINE.search(out)
        if not match:
            logger.error(f"{entry}: MISSING in the escrow, the entry holds no password")
            ok = False
        elif match.group(1) != fingerprint(str(value)):
            logger.error(f"{entry}: STALE, the escrow does not hold {path}. Re-escrow it in this sitting")
            ok = False
        else:
            logger.success(f"{entry}: matches {path}")
    return ok


def check_fleet(env: str, *, cm: object = None, run: Optional[RunFn] = None) -> bool:
    """`check` over `backup.sources`, with the passwords from SOPS."""
    logger.section("backup escrow check")
    if cm is None:
        from toolkit.features.configuration import ConfigurationManager

        cm = ConfigurationManager(env)
    from toolkit.features.backup_destination import _default_run

    config = cm.get_merged_config()  # type: ignore[attr-defined]
    nodes = sorted((config.get("backup", {}) or {}).get("sources", {}) or {})
    return check(nodes, secret=cm.get_secret_by_path, run=run or _default_run)  # type: ignore[attr-defined]
