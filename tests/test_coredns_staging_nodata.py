"""A staging name answers every query type, not only A (DNS-005, #2711).

rpi4's CoreDNS answers `*.staging.kubelab.live` from a `template IN A` block.
A query of any other type matched nothing, ran off the end of the plugin chain
and came back SERVFAIL. glibc ignores that for the AAAA half of a lookup; musl
(Alpine, busybox) sends A and AAAA together and fails the lookup if either
fails. Staging Vikunja's `wait-for-idp` init container, on busybox, could not
resolve `auth.staging.kubelab.live` for eight days, while every glibc client
and `dig A` said the name was fine.

The other types must get NODATA: NOERROR, no answer, the zone's SOA in the
authority section (RFC 2308). This runs the rendered zone in the CoreDNS image
the role pins and asks it, because the failure lives in how CoreDNS chains
plugins, which no reading of the Corefile can show. It asks over UDP, the
transport the incident lived on, except on macOS (see `TRANSPORT`).
"""

from __future__ import annotations

import os
import random
import shutil
import socket
import struct
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

import pytest
import yaml

from tests.test_coredns_prod_zone_targets import ROLE, _role_vars
from tests.test_coredns_staging_zone_hosts import APEX, _staging_zone

TYPES = {"A": 1, "SOA": 6, "AAAA": 28, "HTTPS": 65}
NOERROR = 0
# Colima, the macOS Docker VM, forwards published TCP ports and drops UDP
# (measured 2026-11-05, #3072). The plugin chain answers both transports alike,
# so macOS asks over TCP. CI and Linux keep UDP: a fallback from UDP to TCP would
# hide a UDP-only failure exactly where it can be seen.
TRANSPORT = "tcp" if sys.platform == "darwin" else "udp"
SUBDOMAIN = f"auth.{APEX}"


class Reply(NamedTuple):
    rcode: int
    answers: list[tuple[int, bytes]]
    authority: list[tuple[int, bytes]]


def _skip_name(packet: bytes, offset: int) -> int:
    """Offset just past a (possibly compressed) name."""
    while True:
        length = packet[offset]
        if length & 0xC0 == 0xC0:
            return offset + 2
        if length == 0:
            return offset + 1
        offset += 1 + length


def _records(packet: bytes, offset: int, count: int) -> tuple[list[tuple[int, bytes]], int]:
    records = []
    for _ in range(count):
        offset = _skip_name(packet, offset)
        rtype, _cls, _ttl, rdlength = struct.unpack("!HHIH", packet[offset : offset + 10])
        offset += 10
        records.append((rtype, packet[offset : offset + rdlength]))
        offset += rdlength
    return records, offset


def _recv_exactly(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("the server closed the connection mid-reply")
        data += chunk
    return data


def _query(port: int, name: str, qtype: str) -> Reply:
    query_id = random.randrange(1 << 16)
    question = b"".join(bytes([len(label)]) + label.encode() for label in name.split(".")) + b"\x00"
    packet = struct.pack("!HHHHHH", query_id, 0, 1, 0, 0, 0) + question + struct.pack("!HH", TYPES[qtype], 1)
    if TRANSPORT == "udp":
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(2)
            sock.sendto(packet, ("127.0.0.1", port))
            reply, _ = sock.recvfrom(4096)
    else:
        with socket.create_connection(("127.0.0.1", port), timeout=2) as sock:
            sock.sendall(struct.pack("!H", len(packet)) + packet)
            reply = _recv_exactly(sock, struct.unpack("!H", _recv_exactly(sock, 2))[0])
    reply_id, flags, qdcount, ancount, nscount, _ar = struct.unpack("!HHHHHH", reply[:12])
    assert reply_id == query_id, "a reply to another query"
    offset = 12
    for _ in range(qdcount):
        offset = _skip_name(reply, offset) + 4
    answers, offset = _records(reply, offset, ancount)
    authority, _ = _records(reply, offset, nscount)
    return Reply(flags & 0x0F, answers, authority)


@pytest.fixture
def coredns(docker_mount_dir: Path) -> Iterator[int]:
    """The rendered staging apex zone, served by the role's pinned image; yields its port for `TRANSPORT`."""
    if shutil.which("docker") is None:
        # In CI a missing docker must fail: a skip would hide the only check of this.
        if os.environ.get("CI"):
            pytest.fail("docker not on PATH in CI: the staging zone went unqueried")
        pytest.skip("docker not on PATH: cannot run CoreDNS (a skip is CANNOT CHECK, not OK)")
    image = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))["coredns_image"]
    (docker_mount_dir / "Corefile").write_text(f"{APEX}:1053 {{{_staging_zone()}", encoding="utf-8", newline="\n")
    # The image runs as a non-root user, and the temporary directory is 0700:
    # without this CoreDNS cannot read its config and exits at once.
    docker_mount_dir.chmod(0o755)
    # Docker picks the host port. A port probed here and released before `docker
    # run` binds it is free for any parallel worker to take in between (#3078).
    name = f"coredns-staging-nodata-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker", "run", "-d", "--rm", "--name", name,
            "-p", f"127.0.0.1::1053/{TRANSPORT}",
            "-v", f"{docker_mount_dir}:/etc/coredns:ro",
            image, "-conf", "/etc/coredns/Corefile",
        ],
        check=True, capture_output=True, text=True, encoding="utf-8", timeout=180,
    )  # fmt: skip
    try:
        published = subprocess.run(
            ["docker", "port", name, f"1053/{TRANSPORT}"], check=True, capture_output=True, text=True, encoding="utf-8"
        )
        port = int(published.stdout.split()[0].rsplit(":", 1)[1])
        deadline = time.monotonic() + 30
        while True:
            try:
                _query(port, APEX, "A")
                break
            except OSError:
                if time.monotonic() > deadline:
                    logs = subprocess.run(
                        ["docker", "logs", name], capture_output=True, text=True, encoding="utf-8", errors="replace"
                    ).stdout
                    pytest.fail(f"CoreDNS never answered on {port}:\n{logs}")
                time.sleep(0.5)
        yield port
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


@pytest.mark.integration
def test_a_staging_name_answers_every_type_and_a_with_ace1(coredns: int) -> None:
    ace1 = socket.inet_aton(_role_vars()["node_ips"]["ace1"])
    replies = {qtype: _query(coredns, SUBDOMAIN, qtype) for qtype in ("A", "AAAA", "HTTPS")}

    assert {qtype: reply.rcode for qtype, reply in replies.items()} == dict.fromkeys(replies, NOERROR), (
        "a type other than A fails the whole lookup in musl clients"
    )
    assert replies["A"].answers == [(TYPES["A"], ace1)]
    for qtype in ("AAAA", "HTTPS"):
        assert replies[qtype].answers == [], f"{qtype} answered something for a name only A serves"
        assert [rtype for rtype, _ in replies[qtype].authority] == [TYPES["SOA"]], (
            f"{qtype} NODATA without the SOA cannot be cached negatively (RFC 2308)"
        )


@pytest.mark.integration
def test_the_apex_still_reaches_hosts(coredns: int) -> None:
    """The NODATA block falls through for the apex, which no pattern matches.

    AAAA is asked too: musl sends it with A, so the apex needs `hosts`' NODATA
    for it as much as the A answer. HTTPS stands for every type `hosts` keeps no
    record of, which browsers ask before A."""
    reply = _query(coredns, APEX, "A")

    assert reply.rcode == NOERROR
    assert reply.answers == [(TYPES["A"], socket.inet_aton(_role_vars()["node_ips"]["ace1"]))]
    for qtype in ("AAAA", "HTTPS"):
        other = _query(coredns, APEX, qtype)
        assert other.rcode == NOERROR, f"the apex fails {qtype}"
        assert other.answers == [], f"the apex answered {qtype} with a record nothing declares"
