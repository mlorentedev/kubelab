"""Halt the lab Wi-Fi's radio on purpose and watch the edge bring it back (NET-005 B10, AC13).

The RPi4's radio firmware can halt (raspberrypi/firmware#1403). The gateway role's
liveness check answers with a ladder: a driver reload at the grace-th missed check,
then one reboot per outage. B10 proves the ladder on the edge itself by unloading
the AP's driver, which takes the interface away as a halt would, and then waiting
for the AP to serve again with no human step.

The interface and the driver are read from the deployed liveness unit's ExecStart,
so the fault is injected on exactly what the ladder watches and reloads.

The unload is tried first on its own, with hostapd serving, because whether that
succeeds is part of what B10 records: on the RPi4 the vendor module brcmfmac_wcc
holds brcmfmac. When it is refused, the holders are unloaded with it, as the
ladder's own reload does.

Nothing is injected unless the AP is serving first. The reading after the fault
tolerates SSH failing, since the ladder's last step reboots the edge.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from toolkit.features.edge_status import _ssh

LIVENESS_UNIT = "kubelab-edge-liveness.service"
# The timer runs every minute and the grace is 3 misses, so the reload lands near
# minute 3 and a reboot near minute 4. The deadline also covers the reboot's boot.
DEADLINE_S = 12 * 60
POLL_S = 20
SESSION_TIMEOUT_S = 60
# hostapd's control socket, from `ctrl_interface` in the gateway role's hostapd.conf.j2.
HOSTAPD_DIR = "/run/hostapd"

INJECTED, NOT_SERVING, UNLOAD_FAILED, NO_UNIT, NOT_HALTED = (
    "injected",
    "not-serving",
    "unload-failed",
    "no-unit",
    "not-halted",
)

# `argv[]=/usr/local/sbin/kubelab-edge-liveness wlan0 brcmfmac uplink0 ;`
_ARGV = r"s/.*argv\[\]=\([^;]*\);.*/\1/p"


def _hostapd_state(ap: str) -> str:
    """The ladder's own test of the AP: hostapd's `state=` for the interface, or
    `unanswered` when its control socket does not answer."""
    return (
        f'$(s=$(sudo -n timeout 10 hostapd_cli -p {HOSTAPD_DIR} -i "{ap}" status 2>/dev/null'
        """ | sed -n 's/^state=//p'); echo "${s:-unanswered}")"""
    )


def inject_script() -> str:
    """What the edge runs to inject the fault. It prints `key value` lines, and the
    last one is `result <outcome>`."""
    return "\n".join(
        [
            f"argv=$(systemctl show -p ExecStart --value {LIVENESS_UNIT} | sed -n '{_ARGV}')",
            "set -- $argv",
            'ap=$2; driver=$3; [ -n "$driver" ] || { echo "result ' + NO_UNIT + '"; exit 0; }',
            'printf "interface %s\\ndriver %s\\n" "$ap" "$driver"',
            'printf "boot %s\\nclock %s\\n" "$(cat /proc/sys/kernel/random/boot_id)" "$(date -u +%s)"',
            # The ladder's own overrides, so a test can run this script on a fake sysfs.
            "sys_net=${EDGE_SYS_NET:-/sys/class/net}; sys_module=${EDGE_SYS_MODULE:-/sys/module}",
            'state=$(cat "$sys_net/$ap/operstate" 2>/dev/null || echo absent)',
            f"hostapd={_hostapd_state('$ap')}",
            'printf "before %s %s\\n" "$state" "$hostapd"',
            '[ "$state" = up ] && [ "$hostapd" = ENABLED ] || { echo "result ' + NOT_SERVING + '"; exit 0; }',
            'if out=$(sudo -n modprobe -r "$driver" 2>&1); then echo "bare-unload ok"; else',
            '  printf "bare-unload refused %s\\n" "$(echo "$out" | head -1)"',
            '  holders=$(ls "$sys_module/$driver/holders" 2>/dev/null | tr "\\n" " ")',
            '  if out=$(sudo -n modprobe -r $holders "$driver" 2>&1); then printf "holder-unload ok %s\\n" "$holders"',
            '  else printf "holder-unload failed %s\\n" "$(echo "$out" | head -1)"; echo "result '
            + UNLOAD_FAILED
            + '"; exit 0; fi',
            "fi",
            # The fault is observed, not assumed: an interface still up after the
            # unload proves nothing about the ladder.
            'after=$(cat "$sys_net/$ap/operstate" 2>/dev/null || echo absent)',
            'printf "after %s\\n" "$after"',
            '[ "$after" != up ] || { echo "result ' + NOT_HALTED + '"; exit 0; }',
            f'echo "result {INJECTED}"',
        ]
    )


def poll_script(interface: str, since: int) -> str:
    """What the edge runs after the fault: the AP's state, the boot, and the ladder's lines since."""
    return "\n".join(
        [
            'printf "boot %s\\n" "$(cat /proc/sys/kernel/random/boot_id)"',
            f'printf "state %s %s\\n" "$(cat /sys/class/net/{interface}/operstate 2>/dev/null || echo absent)"'
            f' "{_hostapd_state(interface)}"',
            # The unit's own failure lines too: a run that fails before it logs
            # anything about the lab Wi-Fi still shows in the report.
            f"sudo -n journalctl -u {LIVENESS_UNIT} --since @{since} -o short-iso --no-pager 2>/dev/null"
            " | grep -F -e 'lab Wi-Fi' -e 'Failed to start' | sed 's/^/ladder /'",
        ]
    )


def parse(output: str) -> dict[str, Any]:
    """Read `key value` lines; `ladder` lines are kept in order."""
    facts: dict[str, Any] = {"ladder": []}
    for line in output.splitlines():
        key, _, value = line.partition(" ")
        if key == "ladder":
            facts["ladder"].append(value)
        elif key:
            facts[key] = value.strip()
    return facts


@dataclass
class Outcome:
    """What one B10 run observed."""

    injected: dict[str, Any]
    recovered_after_s: int | None = None
    rebooted: bool = False
    ladder: list[str] = field(default_factory=list)
    unreachable_polls: int = 0

    @property
    def code(self) -> int:
        """0 the AP serves again, 1 it did not by the deadline, 3 nothing injected or
        the fault not observed, 255 SSH."""
        result = self.injected.get("result")
        if result != INJECTED:
            return 255 if result is None else 3
        return 0 if self.recovered_after_s is not None else 1


def serving(facts: dict[str, Any]) -> bool:
    """The ladder's own test: the interface is up and hostapd reports it ENABLED."""
    return facts.get("state") == "up ENABLED"


def report(outcome: Outcome) -> list[str]:
    """The lines `make edge-ap-halt` prints, the verdict last."""
    i = outcome.injected
    result = i.get("result")
    if result is None:
        # A session that dies after the unload prints no result either, so this
        # cannot say that nothing was injected.
        return [
            "verdict: the edge did not answer, so whether the driver was unloaded is unknown; "
            "run `make edge-boot-check`, and wait for the ladder if the lab Wi-Fi is down"
        ]
    if result == NO_UNIT:
        return [f"verdict: {LIVENESS_UNIT} is not deployed, nothing was injected"]
    lines = [f"interface: {i.get('interface')}, driver: {i.get('driver')}", f"before: {i.get('before')}"]
    if result == NOT_SERVING:
        return [*lines, "verdict: the AP was not serving, so nothing was injected"]
    lines.append(f"unload alone: {i.get('bare-unload')}")
    if "holder-unload" in i:
        lines.append(f"unload with holders: {i['holder-unload']}")
    if result == UNLOAD_FAILED:
        return [*lines, "verdict: the driver would not unload, nothing was injected"]
    lines.append(f"after the unload: {i.get('after')}")
    if result == NOT_HALTED:
        return [*lines, "verdict: cannot tell, the interface stayed up after the unload, so no halt was observed"]
    lines.append(f"ladder: {len(outcome.ladder)} line(s)")
    lines.extend(f"  {entry}" for entry in outcome.ladder)
    lines.append(f"edge rebooted: {'yes' if outcome.rebooted else 'no'}")
    if outcome.unreachable_polls:
        lines.append(f"polls with no answer: {outcome.unreachable_polls}")
    if outcome.recovered_after_s is None:
        lines.append(f"verdict: FAILED, the AP was not serving {DEADLINE_S // 60} min after the unload")
    else:
        lines.append(f"verdict: recovered, the AP served again {outcome.recovered_after_s} s after the unload")
    return lines


def _run(networking: dict[str, Any], script: str) -> tuple[int, str]:
    try:
        result = subprocess.run(
            [*_ssh(networking), script],
            check=False,
            stdout=subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=SESSION_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return 255, ""
    return result.returncode, result.stdout


def run_ap_halt(
    networking: dict[str, Any],
    run: Callable[[dict[str, Any], str], tuple[int, str]] = _run,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[int, list[str]]:
    """Inject the fault, then poll until the AP serves again or the deadline passes."""
    _, out = run(networking, inject_script())
    outcome = Outcome(injected=parse(out))
    if outcome.injected.get("result") != INJECTED:
        return outcome.code, report(outcome)
    start = clock()
    while (remaining := DEADLINE_S - (clock() - start)) > 0:
        sleep(min(POLL_S, remaining))
        code, out = run(networking, poll_script(outcome.injected["interface"], int(outcome.injected["clock"])))
        if code != 0:
            outcome.unreachable_polls += 1
            continue
        facts = parse(out)
        outcome.rebooted = outcome.rebooted or facts.get("boot") != outcome.injected.get("boot")
        # After a reboot the journal's current boot holds the ladder's later lines only.
        outcome.ladder = _merge(outcome.ladder, facts["ladder"])
        # A poll that answers after the deadline is not a recovery within it.
        if serving(facts) and clock() - start <= DEADLINE_S:
            outcome.recovered_after_s = int(clock() - start)
            break
    return outcome.code, report(outcome)


def _merge(seen: list[str], new: list[str]) -> list[str]:
    return seen + [line for line in new if line not in seen]
