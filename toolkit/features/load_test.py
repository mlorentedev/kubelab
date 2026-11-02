"""Measure staging's capacity with a repeatable load test (OPS-054, #2956).

k6 runs on the generator node, next to the staging node on the LAN: from the
operator's Mac the path is a Tailscale relay, which would measure the relay.

Staging only, by construction: the target list is built here from the staging
config and no command takes a URL. A host that is not a staging name, or that prod
declares, is refused; k6 connects to the staging node's LAN address whatever DNS
answers; it follows no redirect; and constant-rate.js repeats the host check.

The rate limiter (30/s per host) is not edited. A run applies
infra/k8s/overlays/staging/load-test-route.yaml, a header-scoped route with the same
chain minus `rate-limit`, and deletes it in a `finally`. A 429 on that route means
the bypass is not in force, so the step reads invalid rather than as capacity.
"""

from __future__ import annotations

import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Finer between 800 and 2000: the first run went from healthy at 800 to Traefik
# OOMKilled at 1600, a cliff too wide to read.
STEPS = (50, 100, 200, 400, 800, 1000, 1200, 1400, 1600, 2000, 3200, 6400)
BASELINE_RATE = 25  # below the limiter's 30/s, so it needs no route at all
STEP_SECONDS = 60
SETTLE_SECONDS = 15
TOP_AFTER_SECONDS = 45  # metrics-server averages over about 15 s

# Declared before the first run, so the knee cannot be chosen after seeing the data.
MAX_ERROR_RATE = 0.01
MAX_P95_MS = 250.0
MIN_ACHIEVED = 0.95
MAX_GENERATOR_CPU = 85.0

# After an edge restart nothing measured means anything until it stays up: the first
# run's later ramps read a crash loop as a service failing at 50/s.
EDGE_NAMESPACE = "kube-system"
EDGE_WORKLOAD = "traefik"
EDGE_STABLE_SECONDS = 120
EDGE_WAIT_SECONDS = 900

BYPASS_HEADER = "X-Load-Test"
BYPASS_VALUE = "ops-054"
ROUTE_NAME = "load-test"
ROUTE_MANIFEST = "infra/k8s/overlays/staging/load-test-route.yaml"
SCRIPT = "infra/load-test/constant-rate.js"
STAGING_NAME = re.compile(r"(^|\.)staging\.[a-z0-9.-]+$")


class LoadTestRefused(Exception):
    """The run would leave staging, or could not prove it stays there."""


@dataclass(frozen=True)
class Target:
    name: str
    host: str
    path: str
    workload: str


def refuse_unless_staging(env: str) -> None:
    if env != "staging":
        raise LoadTestRefused(f"load tests run against staging only, not {env!r}")


def _hosts(values: dict[str, Any]) -> dict[str, str]:
    platform = values["apps"]["platform"]
    return {"api": platform["api"]["domain"], "web": platform["web"]["domain"]}


def build_targets(staging: dict[str, Any], prod: dict[str, Any]) -> tuple[Target, ...]:
    """The only places load can go. `/health` touches no dependency; `/` is static."""
    hosts = _hosts(staging)
    prod_hosts = set(_hosts(prod).values())
    for host in hosts.values():
        if host in prod_hosts or not STAGING_NAME.search(host):
            raise LoadTestRefused(f"{host} is not a staging host")
    return (
        Target("api-health", hosts["api"], "/health", "api"),
        Target("web-static", hosts["web"], "/", "web"),
    )


def resolve_nodes(values: dict[str, Any], prod: dict[str, Any]) -> tuple[str, str, str]:
    """(target node, its LAN address, generator node); never an address prod owns."""
    declared = values["load_test"]
    target, generator = declared["target_node"], declared["generator_node"]
    nodes = values["networking"]["nodes"]
    address = nodes[target]["lan_ip"]
    vps = prod["networking"]["vps"]
    if address in {vps.get("public_ip"), vps.get("tailscale_ip")}:
        raise LoadTestRefused(f"{address} belongs to prod")
    if target == generator:
        raise LoadTestRefused("the generator must not share the node it measures")
    return target, address, generator


def k6_env(target: Target, address: str, rate: int, seconds: int, bypass: bool) -> dict[str, str]:
    env = {
        "LT_HOST": target.host,
        "LT_PATH": target.path,
        "LT_ADDRESS": address,
        "LT_RATE": str(rate),
        "LT_SECONDS": str(seconds),
    }
    if bypass:
        env |= {"LT_BYPASS_HEADER": BYPASS_HEADER, "LT_BYPASS_VALUE": BYPASS_VALUE}
    return env


def k6_command(image: str, env: dict[str, str]) -> str:
    flags = " ".join(f"-e {key}={value}" for key, value in sorted(env.items()))
    return f"docker run --rm -i --network host {flags} {image} run --quiet --no-usage-report -"


def parse_summary(stdout: str) -> dict[str, float]:
    """The figures of one step, from the metrics k6 printed. Latencies in ms."""
    metrics = json.loads(stdout.strip().splitlines()[-1])
    duration = metrics["http_req_duration"]["values"]

    def value(metric: str, key: str) -> float:
        return float(metrics.get(metric, {}).get("values", {}).get(key, 0))

    return {
        "requests": value("http_reqs", "count"),
        "achieved_rps": value("http_reqs", "rate"),
        "error_rate": value("http_req_failed", "rate"),
        "status_429": value("status_429", "count"),
        "dropped": value("dropped_iterations", "count"),
        "vus_peak": value("vus", "max"),
        "avg_ms": duration["avg"],
        "p50_ms": duration["med"],
        "p90_ms": duration["p(90)"],
        "p95_ms": duration["p(95)"],
        "p99_ms": duration["p(99)"],
        "max_ms": duration["max"],
    }


def classify(step: dict[str, Any], rate: int, bypass: bool = True) -> list[str]:
    """Why this step does not count as healthy; empty means it does."""
    reasons = []
    if step.get("edge_restarts"):
        reasons.append("edge-restart")
    if step.get("pod_replaced"):
        reasons.append("rollout")  # a deploy landed mid-step: it measured the rollout
    if bypass and step["status_429"] > 0:
        reasons.append("limiter")  # never capacity: the route was not in force
    if step.get("generator_cpu", 0) > MAX_GENERATOR_CPU:
        reasons.append("generator")
    if step["error_rate"] >= MAX_ERROR_RATE:
        reasons.append("errors")
    if step["p95_ms"] > MAX_P95_MS:
        reasons.append("latency")
    if step["achieved_rps"] < MIN_ACHIEVED * rate:
        reasons.append("throughput")
    return reasons


def knee(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """The last healthy rate, the first that was not, and whether that reads as a bound.

    A ramp that ended on the generator, or never degraded, says nothing about where
    the service stops: `last_healthy_rps` is then only a lower bound. One stopped by
    the limiter measured nothing at all, and neither did one a rollout cut short."""
    healthy = [s["rate"] for s in steps if not s["reasons"]]
    bad = next((s for s in steps if s["reasons"]), None)
    invalid = bad is not None and bool({"limiter", "rollout"} & set(bad["reasons"]))
    bound = bad is None or invalid or "generator" in bad["reasons"]
    return {
        "last_healthy_rps": healthy[-1] if healthy and not invalid else None,
        "first_degraded_rps": bad["rate"] if bad else None,
        "reasons": bad["reasons"] if bad else [],
        "lower_bound_only": bound,
        "vus_at_last_healthy": next((s["vus_peak"] for s in steps if healthy and s["rate"] == healthy[-1]), None),
    }


def cpu_percent(before: str, after: str) -> float:
    """Busy share of the node between two `cpu` lines of /proc/stat."""
    first, second = ([int(x) for x in line.split()[1:]] for line in (before, after))
    delta = [b - a for a, b in zip(first, second, strict=True)]
    total, idle = sum(delta), delta[3] + delta[4]
    return round(100 * (total - idle) / total, 1) if total else 0.0


def throttled_ms(before: str, after: str) -> float:
    """CPU-throttled milliseconds between two cgroup cpu.stat reads."""

    def read(text: str) -> int:
        found = re.search(r"throttled_usec (\d+)", text)
        return int(found.group(1)) if found else 0

    return (read(after) - read(before)) / 1000


class Lab:
    """Every effect the run has: two SSH hosts and the staging kubeconfig."""

    def __init__(self, root: Path, kubeconfig: str, operator_as: str, target_node: str, generator: str) -> None:
        self.root, self.kubeconfig, self.operator_as = root, kubeconfig, operator_as
        self.target_node, self.generator = target_node, generator

    def ssh(self, node: str, command: str, stdin: str | None = None, timeout: int = 60) -> str:
        done = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", node, command],
            input=stdin, capture_output=True, text=True, timeout=timeout, check=True,
        )  # fmt: skip
        return done.stdout

    def kubectl(self, *args: str, impersonate: bool = False) -> str:
        cmd = ["kubectl", "--kubeconfig", self.kubeconfig, *args]
        if impersonate:
            cmd.append(f"--as={self.operator_as}")
        return subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True).stdout

    def assert_cluster(self) -> None:
        """The kubeconfig reaches the single staging node, or nothing is applied."""
        names = self.kubectl("get", "nodes", "-o", "name").split()
        if names != [f"node/{self.target_node}"]:
            raise LoadTestRefused(f"kubeconfig reaches {names}, not node/{self.target_node}")

    def arm(self) -> None:
        self.kubectl("apply", "-f", str(self.root / ROUTE_MANIFEST), impersonate=True)

    def disarm(self) -> None:
        self.kubectl("delete", "-f", str(self.root / ROUTE_MANIFEST), "--ignore-not-found", impersonate=True)

    def pod(self, workload: str, namespace: str = "kubelab") -> dict[str, Any]:
        out = self.kubectl("get", "pods", "-n", namespace, "-l", f"app.kubernetes.io/name={workload}", "-o", "json")
        items = [p for p in json.loads(out)["items"] if p["status"].get("phase") == "Running"]
        return items[0]

    def restarts(self, workload: str, namespace: str = "kubelab") -> int:
        return sum(c["restartCount"] for c in self.pod(workload, namespace)["status"]["containerStatuses"])

    def edge_ready(self) -> bool:
        return all(c["ready"] for c in self.pod(EDGE_WORKLOAD, EDGE_NAMESPACE)["status"]["containerStatuses"])

    def edge_memory_peak_mb(self) -> float:
        """Highest the edge's pod has reached since its cgroup began: a ramp only climbs."""
        uid = self.pod(EDGE_WORKLOAD, EDGE_NAMESPACE)["metadata"]["uid"].replace("-", "_")
        path = f"/sys/fs/cgroup/kubepods.slice/kubepods-*/kubepods-*-pod{uid}.slice/memory.peak"
        return round(int(self.ssh(self.target_node, f"cat {path}").strip()) / 1048576, 1)

    def cpu_line(self, node: str) -> str:
        return self.ssh(node, "head -1 /proc/stat")

    def cpu_stat(self, workload: str) -> str:
        uid = self.pod(workload)["metadata"]["uid"].replace("-", "_")
        return self.ssh(
            self.target_node, f"cat /sys/fs/cgroup/kubepods.slice/kubepods-*/kubepods-*-pod{uid}.slice/cpu.stat"
        )

    def memory_available_mb(self, node: str) -> int:
        out = self.ssh(node, "grep MemAvailable /proc/meminfo")
        return int(out.split()[1]) // 1024

    def top(self, workload: str) -> dict[str, str]:
        out = self.kubectl("top", "pod", "-A", "--no-headers", "-l", f"app.kubernetes.io/name in ({workload},traefik)")
        return {row[1].rsplit("-", 2)[0]: f"{row[2]} {row[3]}" for row in (line.split() for line in out.splitlines())}


def run_step(
    lab: Lab, image: str, script: str, target: Target, address: str, rate: int, seconds: int, bypass: bool
) -> dict[str, Any]:
    """One step with the node's figures around it. The generator's CPU decides its validity."""
    env = k6_env(target, address, rate, seconds, bypass)
    before = {n: lab.cpu_line(n) for n in (lab.target_node, lab.generator)}
    stat_before = lab.cpu_stat(target.workload)
    pod_before = lab.pod(target.workload)["metadata"]["uid"]
    edge_before = lab.restarts(EDGE_WORKLOAD, EDGE_NAMESPACE)
    with ThreadPoolExecutor(max_workers=2) as pool:
        k6 = pool.submit(lab.ssh, lab.generator, k6_command(image, env), script, seconds + 120)
        mid = pool.submit(_sample_mid_step, lab, target.workload, min(TOP_AFTER_SECONDS, seconds))
        stdout = k6.result()
        top, memory = mid.result()
    step: dict[str, Any] = {"rate": rate, "target": target.name, **parse_summary(stdout)}
    step["node_cpu"] = cpu_percent(before[lab.target_node], lab.cpu_line(lab.target_node))
    step["generator_cpu"] = cpu_percent(before[lab.generator], lab.cpu_line(lab.generator))
    step["node_mem_available_mb"] = memory
    step["pods_top"] = top
    step["throttled_ms"] = throttled_ms(stat_before, lab.cpu_stat(target.workload))
    step["edge_restarts"] = lab.restarts(EDGE_WORKLOAD, EDGE_NAMESPACE) - edge_before
    step["edge_memory_peak_mb"] = lab.edge_memory_peak_mb()
    step["pod_replaced"] = lab.pod(target.workload)["metadata"]["uid"] != pod_before
    step["reasons"] = classify(step, rate, bypass)
    return step


def _sample_mid_step(lab: Lab, workload: str, delay: int) -> tuple[dict[str, str], int]:
    import time

    time.sleep(delay)
    return lab.top(workload), lab.memory_available_mb(lab.target_node)


def wait_for_stable_edge(ready: Any, restarts: Any, sleep: Any, stable: int, limit: int, poll: int = 10) -> None:
    """Return once the edge has been ready, without a restart, for `stable` seconds."""
    calm, count = 0, restarts()
    for _ in range(0, limit, poll):
        sleep(poll)
        now = restarts()
        calm = calm + poll if ready() and now == count else 0
        count = now
        if calm >= stable:
            return
    raise LoadTestRefused(f"the edge did not stay up for {stable}s within {limit}s")


def ramp(step_fn: Any, steps: tuple[int, ...], settle: Any) -> list[dict[str, Any]]:
    """Climb until the first unhealthy step: past it, more load only risks the node."""
    done: list[dict[str, Any]] = []
    for rate in steps:
        done.append(step_fn(rate))
        if done[-1]["reasons"]:
            break
        settle()
    return done


def _runtime_facts(lab: Lab, image: str) -> dict[str, Any]:
    """What the figures are a measurement of, read at run time rather than assumed."""
    digest = lab.ssh(
        lab.generator,
        f"docker pull -q {image} >/dev/null && docker inspect --format '{{{{index .RepoDigests 0}}}}' {image}",
        timeout=300,
    ).strip()
    traefik = lab.kubectl(
        "get", "deploy", "traefik", "-n", "kube-system", "-o", "jsonpath={.spec.template.spec.containers[0].image}"
    )
    node = json.loads(lab.kubectl("get", "node", lab.target_node, "-o", "json"))["status"]
    images = {w: lab.pod(w)["spec"]["containers"][0] for w in ("api", "web")}
    return {
        "k6_image": digest,
        "traefik_image": traefik,
        "k3s": node["nodeInfo"]["kubeletVersion"],
        "kernel": node["nodeInfo"]["kernelVersion"],
        "node_capacity": {k: node["capacity"][k] for k in ("cpu", "memory")},
        "cpu_model": {
            n: lab.ssh(n, "lscpu | sed -n 's/^Model name: *//p'").strip() for n in (lab.target_node, lab.generator)
        },
        "workloads": {w: {"image": c["image"], "resources": c.get("resources", {})} for w, c in images.items()},
    }


def run(
    lab: Lab, image: str, targets: tuple[Target, ...], address: str, repeats: int, seconds: int, max_rate: int
) -> dict[str, Any]:
    """Baseline under the limiter, then `repeats` ramps past it. Always removes the route."""
    import time

    lab.assert_cluster()
    script = (lab.root / SCRIPT).read_text(encoding="utf-8")
    facts = _runtime_facts(lab, image)
    steps = tuple(rate for rate in STEPS if rate <= max_rate)
    restarts = {t.workload: lab.restarts(t.workload) for t in targets}
    edge_restarts = lab.restarts(EDGE_WORKLOAD, EDGE_NAMESPACE)

    def stable_edge() -> None:
        wait_for_stable_edge(
            lab.edge_ready,
            lambda: lab.restarts(EDGE_WORKLOAD, EDGE_NAMESPACE),
            time.sleep,
            EDGE_STABLE_SECONDS,
            EDGE_WAIT_SECONDS,
        )

    stable_edge()
    baselines = [run_step(lab, image, script, t, address, BASELINE_RATE, seconds, bypass=False) for t in targets]
    ramps: list[dict[str, Any]] = []
    try:
        lab.arm()
        time.sleep(SETTLE_SECONDS)  # Traefik watches the CRD; give the router time to load
        for repeat in range(1, repeats + 1):
            for target in targets:

                def one(rate: int, target: Target = target) -> dict[str, Any]:
                    return run_step(lab, image, script, target, address, rate, seconds, bypass=True)

                done = ramp(one, steps, lambda: time.sleep(SETTLE_SECONDS))
                ramps.append({"target": target.name, "repeat": repeat, "steps": done, "knee": knee(done)})
                stable_edge()
    finally:
        lab.disarm()
        lab.ssh(lab.generator, f"docker image rm {image} >/dev/null 2>&1 || true")
    return {
        "facts": facts,
        "criteria": {
            "max_error_rate": MAX_ERROR_RATE,
            "max_p95_ms": MAX_P95_MS,
            "min_achieved_ratio": MIN_ACHIEVED,
            "max_generator_cpu": MAX_GENERATOR_CPU,
            "step_seconds": seconds,
            "settle_seconds": SETTLE_SECONDS,
        },
        "baseline": baselines,
        "ramps": ramps,
        "restarts_during_run": {
            **{w: lab.restarts(w) - before for w, before in restarts.items()},
            EDGE_WORKLOAD: lab.restarts(EDGE_WORKLOAD, EDGE_NAMESPACE) - edge_restarts,
        },
    }


def render(result: dict[str, Any]) -> str:
    """The raw figures as one Markdown table per ramp."""
    head = (
        "| rate/s | achieved/s | requests | p50 ms | p90 ms | p95 ms | p99 ms | max ms | errors | 429 | dropped | "
        "peak VUs | in flight | edge mem peak MB | node CPU % | generator CPU % | node mem free MB | "
        "throttled ms | pods | verdict |\n"
        "|" + "---|" * 20
    )

    def row(s: dict[str, Any]) -> str:
        pods = "; ".join(f"{k} {v}" for k, v in s["pods_top"].items())
        cells = [
            s["rate"], f"{s['achieved_rps']:.1f}", int(s["requests"]), f"{s['p50_ms']:.2f}", f"{s['p90_ms']:.2f}",
            f"{s['p95_ms']:.2f}", f"{s['p99_ms']:.2f}", f"{s['max_ms']:.1f}", f"{s['error_rate']:.2%}",
            int(s["status_429"]), int(s["dropped"]), int(s["vus_peak"]),
            f"{s['achieved_rps'] * s['avg_ms'] / 1000:.1f}", s.get("edge_memory_peak_mb", "n/a"),
            s["node_cpu"], s["generator_cpu"],
            s["node_mem_available_mb"], f"{s['throttled_ms']:.0f}", pods, ",".join(s["reasons"]) or "healthy",
        ]  # fmt: skip
        return "| " + " | ".join(str(c) for c in cells) + " |"

    meta = {k: result[k] for k in ("date", "commit", "facts", "criteria", "restarts_during_run") if k in result}
    lines = ["```json", json.dumps(meta, indent=2), "```", "", "## Baseline under the limiter", "", head]
    lines += [row(s) for s in result["baseline"]]
    for r in result["ramps"]:
        lines += ["", f"## {r['target']}, ramp {r['repeat']}", "", f"Knee: `{json.dumps(r['knee'])}`", "", head]
        lines += [row(s) for s in r["steps"]]
    return "\n".join(lines) + "\n"
