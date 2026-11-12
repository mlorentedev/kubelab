"""Which routes take long, per router, from the K3s edge's slow-request access log (OPS-065, #3076).

Traefik logs a request only past `k3s_traefik_access_log_min_duration`, plus every
5xx (#3106, #3140), and keeps no path or client address (SEC-021). So the counts
here are of slow requests, not of all requests, and a route with none reads as
"no sample", never as "needs no exception".

`OriginDuration` is the time around the whole proxying, body copy included, so
every figure is an upper bound on the time to the response headers that
`responseHeaderTimeout` bounds. A route past a candidate bound needs its time to
first header measured directly before it is named as an exception.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULTS = Path("infra/ansible/roles/k3s_server/defaults/main.yml")
THRESHOLD_KEY = "k3s_traefik_access_log_min_duration"
STREAM = '{container="traefik"} | json | __error__=""'
# Anchored on the right: a namespace may hold hyphens (`kube-system`), a hash never does.
_ROUTER = re.compile(r"^(?P<prefix>.+)-(?P<hash>[0-9a-f]{20})@kubernetescrd$")
_UNITS = {"ns": 1, "us": 10**3, "ms": 10**6, "s": 10**9, "m": 60 * 10**9, "h": 3600 * 10**9}


def go_duration_ns(text: str) -> int:
    """A Go duration (`1s`, `500ms`, `1m30s`) in nanoseconds."""
    parts = re.findall(r"(\d+(?:\.\d+)?)(ns|us|ms|s|m|h)", text)
    if not parts or "".join(n + u for n, u in parts) != text.strip():
        raise ValueError(f"not a Go duration: {text!r}")
    return int(sum(float(n) * _UNITS[u] for n, u in parts))


def logged_from_ns(project_root: Path) -> int:
    """The duration past which the edge logs a request, from the role that sets it."""
    defaults = yaml.safe_load((project_root / DEFAULTS).read_text(encoding="utf-8"))
    return go_duration_ns(str(defaults[THRESHOLD_KEY]))


def queries(window: str, bounds: Sequence[int], logged_from_ns: int) -> dict[str, str]:
    """LogQL metric queries, one per figure; only router names and numbers come back."""
    slow = f"{STREAM} | Duration >= {logged_from_ns}"
    origin = f"{slow} | unwrap OriginDuration [{window}]"
    q = {
        "count": f"sum by (RouterName) (count_over_time({slow} [{window}]))",
        "p50": f"quantile_over_time(0.5, {origin}) by (RouterName)",
        "p99": f"quantile_over_time(0.99, {origin}) by (RouterName)",
        "max": f"max_over_time({origin}) by (RouterName)",
        "status": f"sum by (RouterName, DownstreamStatus) (count_over_time({slow} [{window}]))",
    }
    for b in bounds:
        q[f"over_{b}"] = f"sum by (RouterName) (count_over_time({slow} | OriginDuration > {b * 10**9} [{window}]))"
    return q


def day_query() -> str:
    """Lines per day, to show how far back the log reaches."""
    return f'sum(count_over_time({STREAM} | RouterName != "" [1d]))'


@dataclass
class Row:
    route: str
    router: str | None
    declared: bool
    count: int = 0
    p50_s: float | None = None
    p99_s: float | None = None
    max_s: float | None = None
    over: dict[int, int] = field(default_factory=dict)
    statuses: dict[str, str | int] = field(default_factory=dict)


def _by_router(series: Iterable[Mapping[str, Any]]) -> dict[str, float]:
    return {s["metric"].get("RouterName", ""): float(s["value"][1]) for s in series}


def _seconds(ns: float | None) -> float | None:
    return None if ns is None else round(ns / 1e9, 2)


def summarize(results: Mapping[str, list[dict[str, Any]]], routes: Sequence[str], bounds: Sequence[int]) -> list[Row]:
    """One row per router seen, plus one per declared route that logged nothing."""
    counts = _by_router(results.get("count", []))
    figures = {k: _by_router(results.get(k, [])) for k in ("p50", "p99", "max")}
    over = {b: _by_router(results.get(f"over_{b}", [])) for b in bounds}
    statuses: dict[str, dict[str, int]] = {}
    for s in results.get("status", []):
        statuses.setdefault(s["metric"].get("RouterName", ""), {})[s["metric"].get("DownstreamStatus", "?")] = int(
            float(s["value"][1])
        )
    rows: list[Row] = []
    seen: set[str] = set()
    for router, count in counts.items():
        m = _ROUTER.match(router)
        name = _route_of(m["prefix"], routes) if m else router
        seen.add(name)
        rows.append(
            Row(
                route=name,
                router=m["hash"] if m else None,
                declared=name in routes,
                count=int(count),
                p50_s=_seconds(figures["p50"].get(router)),
                p99_s=_seconds(figures["p99"].get(router)),
                max_s=_seconds(figures["max"].get(router)),
                over={b: int(over[b].get(router, 0)) for b in bounds},
                statuses=dict(sorted(statuses.get(router, {}).items())),
            )
        )
    rows += [Row(route=r, router=None, declared=True) for r in routes if r not in seen]
    return sorted(rows, key=lambda r: (-(r.max_s or 0), r.route))


def _route_of(prefix: str, routes: Sequence[str]) -> str:
    """The declared route a router's `<namespace>-<name>` prefix ends with, longest first."""
    for route in sorted(routes, key=len, reverse=True):
        if prefix.endswith(f"-{route}"):
            return route
    return prefix


def ingressroutes(docs: Iterable[Mapping[str, Any]]) -> list[str]:
    """The IngressRoute names an overlay declares."""
    return sorted({d["metadata"]["name"] for d in docs if d.get("kind") == "IngressRoute"})


def render(
    rows: Sequence[Row], window: str, bounds: Sequence[int], logged_from_ns: int, days: Sequence[tuple[str, int]]
) -> str:
    seen = [d for d, n in days if n]
    reach = f"{len(seen)} days with lines, the first 24 h ending {seen[0]}" if seen else "no lines at all"
    head = ["Route", "Router", "Slow requests", "p50 s", "p99 s", "Max s", *(f"> {b} s" for b in bounds), "Statuses"]
    out = [
        f"Slow requests per router, last {window} ({reach}).",
        f"Logged from {logged_from_ns / 1e9:g} s. Figures are `OriginDuration`, body copy included: an upper bound on"
        " the time to response headers.",
        "",
        "| " + " | ".join(head) + " |",
        "|" + "---|" * len(head),
    ]
    for r in rows:
        if not r.count:
            out.append(f"| {r.route} | | no sample | | | | {' | '.join('' for _ in bounds)} | |")
            continue
        status = ", ".join(f"{k}: {v}" for k, v in r.statuses.items())
        route = r.route if r.declared else f"{r.route} (not in the overlay)"
        cells = [route, r.router or "", str(r.count), f"{r.p50_s}", f"{r.p99_s}", f"{r.max_s}"]
        out.append("| " + " | ".join([*cells, *(str(r.over.get(b, 0)) for b in bounds), status]) + " |")
    return "\n".join(out) + "\n"
