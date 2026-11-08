"""Mint one-off tagged pre-auth keys from the declared tenant segment.

VPN-ACL-016 (#2863). Enrolling a tenant node needs a pre-auth key that carries
exactly one ACL tag -- the segment's hosts or clients tag -- so the policy
rendered by VPN-ACL-014 admits the machine to its segment and nothing else.
The tag is read from the SOPS segment declaration, never taken from argv: the
operator names the segment and the role, and the declaration supplies the tag.
A reusable key is a standing invitation (three were found live on 2026-08-23),
so this module never passes `--reusable`.

Delivery posture: the key material is written once to an owner-only file and
is the one value this module never prints, logs, or returns. The file is
created empty and hardened before the material is written, and a delivery that
cannot be hardened or written is unlinked rather than left behind (#3196).
Everything it reports -- the returned summary, exception text, failure
diagnostics -- names the key's id, never its material. Failure messages about
unparseable headscale output may list field NAMES, never values, because
exception text lands in logs.

Transport follows `secret_expiry`'s pattern: `ssh ... docker exec <container>
headscale ...` with BatchMode, and guards where the remote string is built
(the #1353 rule -- the guard belongs at the boundary, as a raise, not an
assert that `python -O` would switch off).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from toolkit.config.settings import settings
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.secrets_manager import SecretsManager

_SAFE_CONTAINER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
# Prometheus-style duration as headscale's `--expiration` accepts it (1h, 30m,
# 1h30m). Anything else is refused before it reaches the remote shell.
_EXPIRATION = re.compile(r"\d+[smh](?:\d+[smh])*")

_SEGMENT_KEY = "apps.services.core.headscale.segments.{name}"

# Every failure that comes AFTER the create command has run carries this. The key
# exists in headscale whether or not we could read the answer, and "key not
# delivered" described our delivery while reading as "nothing to clean up" -- so
# the operator retried and left another orphan nobody holds (#3198).
_ORPHAN_CAVEAT = (
    "a pre-auth key may exist on the VPS anyway, as an orphan nobody holds: "
    "`headscale preauthkeys list` shows it and `headscale preauthkeys expire --id <id>` retires it"
)


class AuthKeyRefused(Exception):
    """The mint was refused before anything was asked of the VPS."""


class MintUnavailableError(Exception):
    """The VPS could not be asked, or answered something unusable."""


@dataclass(frozen=True)
class Segment:
    """One tenant segment as declared in SOPS (shape of EXAMPLE_SEGMENT)."""

    owner: str
    hosts_tag: str
    clients_tag: str
    ports: tuple[int, ...]


@dataclass(frozen=True)
class MintedKey:
    """What the operator is told about a mint. Never carries the key itself."""

    key_id: str
    out_path: str
    role: str
    tag: str
    expiration: str


def parse_segment(raw: str | None, name: str) -> Segment:
    """Parse the SOPS segment declaration, refusing anything undecleared or malformed.

    A SOPS miss is a refusal, not an empty segment: minting with no declaration
    would mean minting with no tag at all, and a key without its segment tag is
    admitted to nothing -- or worse, to whatever a caller improvises next.
    """
    if raw is None:
        raise AuthKeyRefused(f"segment {name!r} is not declared in SOPS ({_SEGMENT_KEY.format(name=name)})")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AuthKeyRefused(f"segment {name!r} is malformed: not JSON") from exc
    if not isinstance(data, dict):
        raise AuthKeyRefused(f"segment {name!r} is malformed: expected a mapping")
    owner = data.get("owner")
    hosts_tag = data.get("hosts_tag")
    clients_tag = data.get("clients_tag")
    ports = data.get("ports")
    if (
        not isinstance(owner, str)
        or not owner
        or not isinstance(hosts_tag, str)
        or not isinstance(clients_tag, str)
        or not isinstance(ports, list)
        or not all(isinstance(p, int) and not isinstance(p, bool) for p in ports)
    ):
        raise AuthKeyRefused(f"segment {name!r} is malformed: expected owner/hosts_tag/clients_tag/ports")
    for tag in (hosts_tag, clients_tag):
        if not tag.startswith("tag:"):
            raise AuthKeyRefused(f"segment {name!r} tag {tag!r} does not carry the tag: prefix")
    return Segment(owner=owner, hosts_tag=hosts_tag, clients_tag=clients_tag, ports=tuple(ports))


def resolve_role_tag(segment: Segment, role: str) -> str:
    """The segment's tag for the role. The role is hosts|clients and nothing else."""
    if role == "hosts":
        return segment.hosts_tag
    if role == "clients":
        return segment.clients_tag
    raise AuthKeyRefused(f"undeclared role {role!r}: only hosts or clients")


def build_create_command(user_id: str, tag: str, expiration: str, ephemeral: bool) -> str:
    """The `headscale preauthkeys create` argument string, guarded at the boundary.

    Every value here is interpolated into a string a remote shell executes, so
    each one is validated where the string is built -- not where today's only
    caller happens to be careful. Never `--reusable`: a reusable key admits any
    number of machines until it expires.
    """
    if not user_id.isdigit():
        raise ValueError(f"owner id must be numeric, got {user_id!r}")
    if not tag.startswith("tag:"):
        raise ValueError(f"tag must carry the tag: prefix, got {tag!r}")
    if not _EXPIRATION.fullmatch(expiration):
        raise ValueError(f"malformed expiration {expiration!r}")
    command = f"--user {user_id} --expiration {expiration} --tags {tag}"
    if ephemeral:
        command += " --ephemeral"
    return command


def resolve_owner_id(users_json: str, owner: str) -> str:
    """The numeric headscale user id for the segment owner, from `users list --output json`.

    Zero matches and two matches are both refusals: minting against a guessed
    owner would put the key in whatever user headscale falls back to.
    """
    try:
        data = json.loads(users_json)
    except json.JSONDecodeError as exc:
        raise MintUnavailableError("could not parse headscale users list output") from exc
    if isinstance(data, dict) and len(data) == 1 and isinstance(next(iter(data.values())), list):
        data = next(iter(data.values()))
    if not isinstance(data, list):
        raise MintUnavailableError("headscale users list output is not a user list")
    matches = [u for u in data if isinstance(u, dict) and u.get("name") == owner]
    if not matches:
        raise AuthKeyRefused(f"owner {owner!r} not found in headscale users")
    if len(matches) > 1:
        raise AuthKeyRefused(f"owner {owner!r} is ambiguous: {len(matches)} users share the name")
    user_id = str(matches[0].get("id", ""))
    if not user_id.isdigit():
        raise MintUnavailableError(f"headscale returned a non-numeric id for owner {owner!r}")
    return user_id


def parse_create_output(stdout: str) -> tuple[str, str]:
    """(key, id) from `preauthkeys create --output json`, defensively.

    The exact protojson shape is unverified against the running binary, so a
    single nested object carrying the key is unwrapped rather than guessed
    against. When the shape is not recognized the failure names the fields it
    saw -- never their values, because this text reaches logs.
    """
    try:
        data = json.loads(stdout.strip())
    except json.JSONDecodeError as exc:
        raise MintUnavailableError(f"could not parse headscale create output (not JSON); {_ORPHAN_CAVEAT}") from exc
    obj = data
    if isinstance(obj, dict) and "key" not in obj:
        nested = [v for v in obj.values() if isinstance(v, dict)]
        if len(nested) == 1 and "key" in nested[0]:
            obj = nested[0]
    if not isinstance(obj, dict) or "key" not in obj:
        fields = sorted(obj.keys()) if isinstance(obj, dict) else type(obj).__name__
        raise MintUnavailableError(
            f"headscale create output has no key field; top-level fields: {fields}; {_ORPHAN_CAVEAT}"
        )
    key = obj["key"]
    if not isinstance(key, str) or not key:
        raise MintUnavailableError(f"headscale returned an empty key field; {_ORPHAN_CAVEAT}")
    return key, str(obj.get("id", ""))


def _restrict_to_owner(path: Path) -> None:
    """Make an existing file readable only by its owner.

    Windows mode bits are meaningless, so the ACL is rewritten: inheritance
    removed, only the current user granted. POSIX uses an explicit chmod so the
    mode does not depend on the caller's umask.
    """
    if os.name == "nt":
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{os.environ.get('USERNAME', '')}:F"],
            check=True,
            capture_output=True,
            # icacls prints in the locale code page, not UTF-8; None is the
            # honest name for that (tests/test_subprocess_names_its_encoding.py).
            encoding=None,
        )
    else:
        os.chmod(path, 0o600)


def write_owner_only(path: Path, key: str) -> None:
    """Write the key to a new file readable only by its owner. Never overwrites.

    The file is created empty, hardened, and only then given the key: an empty
    file has nothing to leak, so the create-to-hardening window cannot expose
    key material (#3196). A failure at any step -- hardening, a write that does
    not land in full, or a close that cannot be trusted to have flushed --
    unlinks the file and raises, because a file we cannot protect or cannot
    trust is worse than no file. By then the key already exists on the VPS, so
    `mint` names it in the error.
    """
    path = Path(path)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise AuthKeyRefused(f"refusing to overwrite: {path} already exists") from exc
    undelivered = True
    failure: OSError | subprocess.SubprocessError | None = None
    try:
        _restrict_to_owner(path)
        pending = memoryview(key.encode("utf-8"))
        while pending:
            written = os.write(fd, pending)
            if written <= 0:
                raise OSError(f"short write: {len(pending)} of the key's bytes were not accepted")
            pending = pending[written:]
        undelivered = False
    except (OSError, subprocess.SubprocessError) as exc:
        failure = exc
    finally:
        # Close before unlinking: Windows refuses to unlink a file it still
        # holds open. A close that fails cannot be trusted to have flushed the
        # key, so it is a delivery failure too, and it must not swallow the
        # original error nor skip the unlink.
        try:
            os.close(fd)
        except OSError as exc:
            undelivered = True
            failure = failure or exc
        if undelivered:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                raise MintUnavailableError(
                    f"could not deliver the key to {path} and could not remove it: "
                    f"{path} still holds it and must be deleted by hand"
                ) from exc
    if failure is not None:
        raise MintUnavailableError(
            f"could not deliver the key to {path} (owner-only hardening, write or close failed); the file was removed"
        ) from failure


def default_ssh_target() -> str:
    """The VPS ssh target, derived from the SSOT -- never a literal.

    The PUBLIC ip, not the Tailscale one: Headscale *is* the VPN, so a check
    that reaches it over the VPN cannot report on a VPN that is down.
    """
    net = ConfigurationManager("common", settings.project_root).get_merged_config()["networking"]
    return f"{net['ssh_users']['cloud']}@{net['vps']['public_ip']}"


def _ensure_safe_container(container: str) -> None:
    if not _SAFE_CONTAINER.fullmatch(container):
        raise ValueError(f"unsafe container name {container!r}")


def _run_headscale(ssh_target: str, container: str, args: str) -> subprocess.CompletedProcess[str]:
    _ensure_safe_container(container)
    return subprocess.run(
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
        # headscale answers protojson, which is UTF-8 by spec.
        encoding="utf-8",
    )


def mint(
    env: str,
    segment_name: str,
    role: str,
    out_path: Path | str,
    expiration: str = "1h",
    ssh_target: str | None = None,
    container: str = "headscale",
) -> MintedKey:
    """Mint one single-use tagged pre-auth key and deliver it to an owner-only file.

    The tag comes from the SOPS segment declaration for `segment_name`; the
    role picks which of the segment's two tags the key carries (hosts keys are
    persistent, client keys ephemeral). The key material is written to
    `out_path` and returned to nobody: the summary names the id, the expiry and
    the file, and nothing else. Run from the authorized deploy controller
    (OPS-051) -- this module performs a mutating VPS operation.
    """
    _ensure_safe_container(container)
    if ssh_target is None:
        ssh_target = default_ssh_target()
    segment = parse_segment(SecretsManager().show_secret(env, _SEGMENT_KEY.format(name=segment_name)), segment_name)
    tag = resolve_role_tag(segment, role)

    users = _run_headscale(ssh_target, container, "users list --output json")
    if users.returncode != 0:
        raise MintUnavailableError(f"could not ask headscale on {ssh_target}: {users.stderr.strip()}")
    user_id = resolve_owner_id(users.stdout, segment.owner)

    create_command = build_create_command(user_id, tag, expiration, ephemeral=(role == "clients"))
    create = _run_headscale(ssh_target, container, f"preauthkeys create {create_command} --output json")
    if create.returncode != 0:
        # A transport death can land after headscale ran, with the key already in
        # stdout we never read; and a refused create is indistinguishable from it
        # by exit code alone. So the orphan caveat applies here too (#3198).
        raise MintUnavailableError(
            f"could not mint pre-auth key on {ssh_target} via `docker exec {container} headscale`: "
            f"{create.stderr.strip()}; {_ORPHAN_CAVEAT}"
        )
    try:
        key, key_id = parse_create_output(create.stdout)
    except MintUnavailableError as exc:
        # The parser reads stdout and cannot know where it came from, and the
        # remedy the caveat names is not typeable without the coordinates.
        raise MintUnavailableError(f"{exc} (asked on {ssh_target} via `docker exec {container} headscale`)") from exc
    try:
        write_owner_only(Path(out_path), key)
    except MintUnavailableError as exc:
        # The key exists on the VPS whatever happened to the file. Naming it is
        # the only way the operator can expire it (#3196, and #3198's shape).
        raise MintUnavailableError(
            f"{exc}; key {key_id or '<id unreported>'} was already created on the VPS and must be expired"
        ) from exc
    return MintedKey(key_id=key_id, out_path=str(out_path), role=role, tag=tag, expiration=expiration)
