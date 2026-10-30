"""Read the lab edge's uplink soak from its kernel log (NET-005 B12, #2807).

The soak is the edge's current boot. It passes once the boot has run 48 hours with
no reset of the uplink adapter: the adapter dropping off USB, or its driver probing
it again within the boot. Either takes the uplink down. The driver's "failed to
leave lps state" warnings are reported and not counted, since the operator chose
to observe them through the soak (#2807). A reboot starts a new boot, so it starts
the soak again and can never read as a pass.

The journal holds about 8 hours on this node (#2702), so the reading comes from
rsyslog's `kern.log`, which the edge keeps for weeks. Two facts about that file,
measured on the edge, decide how it is read:

- A power cut leaves runs of NUL bytes in it, and grep then answers "binary file
  matches" instead of printing the lines. The NULs are dropped before matching.
- The RPi4 has no clock that survives power-off, so a boot's first lines carry a
  stale time, hours early after a power cut. The file is read in the order it was
  written, never by timestamp, and the current boot starts at its last banner.

The reading fails closed. With no banner, or with an rsyslog that has not run since
the start of this boot, it says it cannot tell instead of reporting a clean soak.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from typing import Any

from toolkit.features.edge_status import _ssh

# B12 in specs/NET-005-lab-edge-site-modes/tasks.md.
SOAK_HOURS = 48
KERNEL_LOG = "/var/log/kern.log"
# rsyslog enters `active` about 15 s into a boot on the edge. One that entered it
# later was restarted, and may not hold this boot's banner.
RSYSLOG_START_LIMIT_S = 300

BANNER = re.compile(r" kernel: Linux version ")
PROBE = re.compile(r" kernel: rtw_\w+ \S+: Firmware version ")
# The adapter's USB path, as the driver names its interface: `1-1.4` in `1-1.4:1.0`.
DRIVER_PATH = re.compile(r" kernel: rtw_\w+ (\d+-[\d.]+):")
DISCONNECT = re.compile(r" kernel: usb (\d+-[\d.]+): USB disconnect")
LPS = "failed to leave lps state"
# Linux names a USB adapter after its MAC until the role renames it (ADR-075 C7).
MAC_NAMED = re.compile(r"\b(wlx|enx)[0-9a-f]{12}\b")
MAC = re.compile(r"\b[0-9a-f]{2}(?::[0-9a-f]{2}){5}\b", re.IGNORECASE)


@dataclass
class Reading:
    """What the current boot's kernel log says about the uplink adapter."""

    hours: float = 0.0
    unreadable: str = ""
    boot: str = ""
    resets: list[str] = field(default_factory=list)
    lps: list[str] = field(default_factory=list)
    other: list[str] = field(default_factory=list)

    @property
    def code(self) -> int:
        """0 passed, 1 failed, 2 in progress, 3 cannot be read."""
        if self.unreadable:
            return 3
        if self.resets:
            return 1
        return 0 if self.hours >= SOAK_HOURS else 2


def log_command(path: str = KERNEL_LOG) -> str:
    """The pipeline that prints the lines the reading uses, oldest file first."""
    # `ls -rv` puts kern.log.4.gz first and kern.log last; -v keeps .10 after .9.
    return (
        f'for f in $(ls -rv {path}*); do zcat -f "$f"; done'
        " | tr -d '\\000'"
        " | LC_ALL=C grep -aE 'kernel: (Linux version|rtw_|usb [0-9.-]+: USB disconnect)'"
    )


def remote_command() -> str:
    """What the edge runs: its uptime, rsyslog's state, then the kernel log's lines."""
    return "; ".join(
        [
            "printf 'uptime %s\\n' \"$(cut -d' ' -f1 /proc/uptime)\"",
            "systemctl show rsyslog -p ActiveState -p ActiveEnterTimestampMonotonic",
            log_command(),
        ]
    )


def soak_command(networking: dict[str, Any]) -> list[str]:
    """The SSH command that reads the soak, over the edge's LAN address."""
    return [*_ssh(networking), remote_command()]


def _classify(boot: list[str], reading: Reading) -> None:
    """Sort the lines after the banner. The first probe is the boot's own."""
    paths: set[str] = set()
    probed = False
    for line in boot:
        if match := DRIVER_PATH.search(line):
            paths.add(match.group(1))
        if PROBE.search(line):
            (reading.resets if probed else reading.other).append(line)
            probed = True
        elif (match := DISCONNECT.search(line)) and match.group(1) in paths:
            reading.resets.append(line)
        elif LPS in line:
            reading.lps.append(line)
        else:
            reading.other.append(line)


def read(output: str) -> Reading:
    """Read what `remote_command` printed."""
    facts: dict[str, str] = {}
    log: list[str] = []
    for line in output.splitlines():
        if " kernel: " in line:
            log.append(line)
        elif line.startswith("uptime "):
            facts["uptime"] = line.split()[1]
        elif "=" in line:
            key, _, value = line.partition("=")
            facts[key] = value
    reading = Reading()
    try:
        reading.hours = float(facts["uptime"]) / 3600
    except (KeyError, ValueError):
        reading.unreadable = "the edge printed no uptime"
        return reading
    entered_s = int(facts.get("ActiveEnterTimestampMonotonic") or 0) / 1_000_000
    if facts.get("ActiveState") != "active" or entered_s > RSYSLOG_START_LIMIT_S:
        reading.unreadable = (
            f"rsyslog is {facts.get('ActiveState', 'unknown')}, active since {entered_s:.0f} s into this boot: "
            "kern.log may not hold this boot's banner"
        )
        return reading
    banners = [i for i, line in enumerate(log) if BANNER.search(line)]
    if not banners:
        reading.unreadable = f"no kernel banner in {KERNEL_LOG}*, so this boot's lines cannot be told apart"
        return reading
    reading.boot = log[banners[-1]]
    _classify(log[banners[-1] + 1 :], reading)
    return reading


def _brief(line: str) -> str:
    """The line's time to the second and its kernel message, with no MAC in it."""
    stamp, _, rest = line.partition(" ")
    text = f"{re.sub(r'[.][0-9]+', '', stamp)} {rest.split(' kernel: ', 1)[-1]}"
    return MAC.sub("<mac>", MAC_NAMED.sub(r"\1<mac>", text))


def report(reading: Reading) -> list[str]:
    """The lines `make edge-soak` prints, the verdict last."""
    if reading.unreadable:
        return [f"verdict: cannot tell ({reading.unreadable})"]
    # The banner's own time can be hours early: the edge has no clock across a power cut.
    lines = [f"boot: {_brief(reading.boot).split(' ', 1)[0]}, up {reading.hours:.1f} h of {SOAK_HOURS}"]
    for title, entries in (
        ("resets", reading.resets),
        ("LPS warnings (reported, not counted)", reading.lps),
        ("other uplink lines", reading.other),
    ):
        lines.append(f"{title}: {len(entries)}")
        lines.extend(f"  {_brief(entry)}" for entry in entries)
    verdict = {0: "passed", 1: "FAILED", 2: f"in progress ({reading.hours:.1f} h of {SOAK_HOURS})"}[reading.code]
    lines.append(f"verdict: {verdict}")
    return lines


def run_soak(networking: dict[str, Any]) -> tuple[int, list[str]]:
    """Read the soak on the edge: 0 passed, 1 failed, 2 in progress, 3 cannot be
    read, 255 SSH. The remote side's errors (an unreadable file) reach stderr."""
    result = subprocess.run(soak_command(networking), check=False, stdout=subprocess.PIPE, text=True, errors="replace")
    if result.returncode == 255:
        return 255, []
    reading = read(result.stdout)
    return reading.code, report(reading)
