"""A timeline of each load-test step, so what moves first at the knee can be read (#3102).

A step's figures are totals over the step. They show that Traefik's CPU and k6's
`waiting` rose at the degraded step, not which rose first, and the candidates for the
stall can only be told apart by order: GC in Traefik, other pods on the node, softirq,
conntrack, the generator.

Everything here is read, nothing is changed. Traefik's Go runtime and entrypoint
metrics come from its metrics port through the apiserver's pod proxy (a GET), and the
node's figures from /proc and the two pods' cgroups over ssh.

What it cannot see, stated so a reader does not look for it: concurrent GC mark and
mark-assist CPU (this Traefik exports neither `go_cpu_classes_*` nor scheduler
latencies, so GC shows as cycles per second, stop-the-world time and allocation rate),
and listen-queue drops inside the pod's network namespace. The apiserver that serves
the proxy runs on the node under test, so each sample costs it one small request.
"""

from __future__ import annotations

import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

SAMPLE_SECONDS = 2
SEPARATOR = "\n@@\n"

# Counters and gauges of the Go runtime, summed over their label sets.
_RUNTIME = (
    "go_gc_duration_seconds_sum",
    "go_gc_duration_seconds_count",
    "go_memstats_alloc_bytes_total",
    "process_cpu_seconds_total",
    "go_goroutines",
    "go_memstats_heap_inuse_bytes",
)
# Traefik's own, kept for the entrypoint the load goes through and summed over codes.
_ENTRYPOINT = (
    "traefik_open_connections",
    "traefik_entrypoint_request_duration_seconds_sum",
    "traefik_entrypoint_request_duration_seconds_count",
)
PUBLIC_ENTRYPOINT = "websecure"
_SAMPLE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+(\S+)")
_UID = re.compile(r"[0-9a-f-]+")

Reader = Callable[[], Any]


@dataclass(frozen=True)
class Readers:
    """One callable per source; each returns its parsed reading or raises."""

    edge: Reader
    node: Reader
    generator: Reader


def parse_edge(text: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in text.splitlines():
        found = _SAMPLE.match(line)
        if not found:
            continue
        name, labels, value = found.groups()
        public = f'entrypoint="{PUBLIC_ENTRYPOINT}"' in (labels or "")
        if name in _RUNTIME or (name in _ENTRYPOINT and public):
            out[name] = out.get(name, 0.0) + float(value)
    return out


def _usage_usec(cpu_stat: str) -> int | None:
    found = re.search(r"^usage_usec (\d+)", cpu_stat, re.MULTILINE)
    return int(found.group(1)) if found else None


def parse_node(text: str) -> dict[str, Any]:
    stat, conntrack, edge, workload = text.split(SEPARATOR)
    cpus = {
        fields[0]: [int(x) for x in fields[1:]]
        for fields in (line.split() for line in stat.splitlines())
        if fields and fields[0].startswith("cpu")
    }
    return {
        "cpus": cpus,
        "conntrack": int(conntrack.strip()) if conntrack.strip() else None,
        "edge_usec": _usage_usec(edge),
        "workload_usec": _usage_usec(workload),
    }


def parse_cpu_line(text: str) -> list[int]:
    return [int(x) for x in text.split()[1:]]


def node_command(edge_uid: str, workload_uid: str) -> str:
    """One ssh round trip per sample. A pod replaced mid-step leaves its cgroup unread, not the sample."""
    paths = []
    for uid in (edge_uid, workload_uid):
        if not _UID.fullmatch(uid):
            raise ValueError(f"not a pod uid: {uid!r}")
        slug = uid.replace("-", "_")
        paths.append(f"/sys/fs/cgroup/kubepods.slice/kubepods-*/kubepods-*-pod{slug}.slice/cpu.stat")
    sep = SEPARATOR.strip()
    return (
        f"cat /proc/stat; echo {sep}; cat /proc/sys/net/netfilter/nf_conntrack_count; echo {sep}; "
        f"cat {paths[0]} 2>/dev/null; echo {sep}; cat {paths[1]} 2>/dev/null; true"
    )


def _busy(before: list[int], after: list[int]) -> tuple[int, int, int]:
    """Elapsed, busy and softirq jiffies between two /proc/stat rows (idle and iowait are not busy)."""
    delta = [b - a for a, b in zip(before, after, strict=False)]
    idle = delta[3] + (delta[4] if len(delta) > 4 else 0)
    softirq = delta[6] if len(delta) > 6 else 0
    return sum(delta), sum(delta) - idle, softirq


def _edge_row(a: dict[str, float], b: dict[str, float], dt: float) -> dict[str, Any]:
    def d(name: str) -> float:
        return b.get(name, 0.0) - a.get(name, 0.0)

    counters = ("process_cpu_seconds_total", "go_gc_duration_seconds_count", "go_memstats_alloc_bytes_total")
    if any(d(name) < 0 for name in counters):
        return {"edge_reset": True}  # a new process: its counters restarted from zero
    requests = d("traefik_entrypoint_request_duration_seconds_count")
    row: dict[str, Any] = {
        "edge_rps": round(requests / dt, 1),
        "open_connections": int(b.get("traefik_open_connections", 0)),
        "goroutines": int(b.get("go_goroutines", 0)),
        "heap_mb": round(b.get("go_memstats_heap_inuse_bytes", 0) / 2**20, 1),
        "gc_per_s": round(d("go_gc_duration_seconds_count") / dt, 2),
        "gc_pause_ms": round(d("go_gc_duration_seconds_sum") * 1000, 3),
        "alloc_mb_s": round(d("go_memstats_alloc_bytes_total") / 1e6 / dt, 1),
        "traefik_cores": round(d("process_cpu_seconds_total") / dt, 2),
    }
    if requests > 0:
        row["edge_mean_ms"] = round(d("traefik_entrypoint_request_duration_seconds_sum") / requests * 1000, 2)
    return row


def _node_row(a: dict[str, Any], b: dict[str, Any], dt: float) -> dict[str, Any]:
    ncpu = sum(1 for name in b["cpus"] if name != "cpu")
    elapsed, busy, softirq = _busy(a["cpus"]["cpu"], b["cpus"]["cpu"])
    if elapsed <= 0 or ncpu == 0:
        return {}
    row: dict[str, Any] = {
        "node_cores": round(busy / elapsed * ncpu, 2),
        "softirq_cores": round(softirq / elapsed * ncpu, 2),
        "conntrack": b["conntrack"],
    }
    per_cpu = [_busy(a["cpus"][n], b["cpus"][n]) for n in b["cpus"] if n != "cpu" and n in a["cpus"]]
    row["max_cpu_busy_pct"] = round(max((100 * u / e for e, u, _ in per_cpu if e > 0), default=0.0), 1)
    cores = {}
    for key, name in (("edge_usec", "edge_cgroup_cores"), ("workload_usec", "workload_cores")):
        if a[key] is not None and b[key] is not None and b[key] >= a[key]:
            cores[name] = round((b[key] - a[key]) / 1e6 / dt, 2)
    row |= cores
    if len(cores) == 2:
        # /proc/stat and the cgroups are read moments apart, so the remainder can dip below zero.
        row["other_cores"] = round(max(row["node_cores"] - sum(cores.values()), 0.0), 2)
    return row


def interval(a: dict[str, Any], b: dict[str, Any], start: float) -> dict[str, Any]:
    """What changed between two samples, as rates, stamped with seconds since the step began."""
    dt = b["t"] - a["t"]
    row: dict[str, Any] = {"t": round(b["t"] - start, 1)}
    if dt <= 0:
        return row
    if a["edge"] is not None and b["edge"] is not None:
        row |= _edge_row(a["edge"], b["edge"], dt)
    if a["node"] is not None and b["node"] is not None:
        row |= _node_row(a["node"], b["node"], dt)
    if a["generator"] is not None and b["generator"] is not None:
        elapsed, busy, _ = _busy(a["generator"], b["generator"])
        if elapsed > 0:
            row["generator_busy_pct"] = round(100 * busy / elapsed, 1)
    return row


def _take(readers: Readers, clock: Callable[[], float]) -> dict[str, Any]:
    sample: dict[str, Any] = {"t": clock()}
    for name in ("edge", "node", "generator"):
        try:
            sample[name] = getattr(readers, name)()
        except (subprocess.SubprocessError, OSError, ValueError):
            sample[name] = None  # one missed read loses two intervals of that source, not the step
    return sample


def sample_timeline(
    readers: Readers,
    seconds: float,
    every: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    """Sample every `every` seconds for `seconds`, and return the intervals between samples."""
    if every <= 0:
        raise ValueError("the timeline needs a positive interval")
    start = clock()
    samples = [_take(readers, clock)]
    while clock() - start < seconds:
        sleep(every)
        samples.append(_take(readers, clock))
    return [interval(a, b, start) for a, b in zip(samples, samples[1:], strict=False)]
