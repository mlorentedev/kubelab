"""When does each credential stop working, and who would notice.

`SECRET_CATALOG` records how to rotate every secret and nothing records when any
of them dies. That asymmetry is the gap this closes: rotation is a procedure
someone follows deliberately, expiry is a date that arrives whether or not
anyone is looking.

The failure it prevents is dated and specific. `aws.headscale_api_key` expires
2027-03-27. `aws1` is a Spot instance: if it is replaced after that date, its
cloud-init cannot clean up the stale Headscale node or register the new one, so
the replacement lands as `aws1-<random>` and breaks the inventory, the
kubeconfig and the prod EndpointSlice. Nothing fails loudly -- the hub simply
does not come back, months after anyone last thought about a key.

ASKED, NOT REMEMBERED. Expiry is read from the issuing service, never from a
date recorded here. A recorded date is a second declaration that drifts the
moment a key is re-minted, and it drifts silently in the safe-looking direction:
it keeps saying "fine" about a key that was replaced with a shorter-lived one.
This repository has that failure written down three times over; a date in a
config file would be the fourth.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class Expiry(str, Enum):
    """How a secret's lifetime is determined."""

    # Cannot expire by construction: we generate it, nothing issues it, and no
    # remote service will stop honouring it. Random tokens, argon2 hashes, RSA
    # keys, passwords.
    NEVER = "never"
    # Issued by a service that knows the expiry and can be asked. The only kind
    # this module can check, and the only kind where "unknown" is a real risk.
    PROVIDER = "provider"
    # Not yet assessed. The default deliberately: a new catalog entry should
    # show up as unclassified rather than quietly assumed immortal.
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class KeyExpiry:
    prefix: str
    expires_at: datetime
    created_at: datetime | None = None

    @property
    def days_left(self) -> int:
        return (self.expires_at - datetime.now(timezone.utc)).days


class ExpiryUnavailableError(RuntimeError):
    """The issuing service could not be asked.

    Deliberately distinct from "nothing expires soon". A check that cannot run
    must never report success -- the same rule `argo check-drift` follows with
    its exit code 2.
    """


# `headscale apikeys list` renders a table with ANSI colour. Parsed by column
# rather than by scraping the whole line: the Prefix field is deliberately
# truncated by headscale itself (`hskey-api-xxxx-***`), so no usable key
# material can appear here even if the output format changes.
_ROW = re.compile(
    r"^\s*(?P<id>\d+)\s*\|\s*(?P<prefix>\S+)\s*\|\s*(?P<expires>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"
    r"\s*\|\s*(?P<created>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"
)


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def parse_headscale_apikeys(output: str) -> list[KeyExpiry]:
    """Rows from `headscale apikeys list`, ANSI stripped."""
    keys: list[KeyExpiry] = []
    for line in _strip_ansi(output).splitlines():
        m = _ROW.match(line)
        if not m:
            continue
        keys.append(
            KeyExpiry(
                prefix=m.group("prefix"),
                expires_at=datetime.strptime(m.group("expires"), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc),
                created_at=datetime.strptime(m.group("created"), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc),
            )
        )
    return keys


def headscale_apikeys(ssh_target: str, container: str = "headscale") -> list[KeyExpiry]:
    """Ask the VPS what it will still accept, and when it will stop.

    Raises rather than returning an empty list when the host cannot be reached:
    an unreachable Headscale and a Headscale with no keys are indistinguishable
    from an empty result, and only one of them is safe to ignore.
    """
    result = subprocess.run(
        [
            "ssh",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "BatchMode=yes",
            ssh_target,
            f"docker exec {container} headscale apikeys list",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ExpiryUnavailableError(f"could not ask headscale on {ssh_target}: {result.stderr.strip()}")

    keys = parse_headscale_apikeys(result.stdout)
    if not keys:
        raise ExpiryUnavailableError(
            f"headscale on {ssh_target} reported no API keys. Every hub reads one at boot, "
            "so an empty list means the query failed, not that none are needed."
        )
    return keys
