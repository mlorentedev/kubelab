"""Measure staging's capacity with a repeatable load test (OPS-054, #2956).

k6 runs on the generator node, next to the staging node on the LAN: from the
operator's Mac the path is a Tailscale relay, which would measure the relay.

Staging only, by construction: the target list is built here from the staging
config and no command takes a URL. A host that is not a staging name, or that prod
declares, is refused; k6 connects to the staging node's LAN address whatever DNS
answers; it follows no redirect; and constant-rate.js repeats the host check.

The rate limiter (30/s per host) is not edited. A run applies
infra/load-test/limiter-bypass-route.yaml, a header-scoped route with the same
chain minus `rate-limit`, and deletes it in a `finally`. A 429 on that route means
the bypass is not in force, so the step reads invalid rather than as capacity.

The header's value is drawn fresh for each run and never recorded (#3012): a route
a dead run leaves behind then bypasses nothing anyone can send, and the next run's
`apply` replaces it.
"""

from __future__ import annotations

import json
import re
import secrets
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from toolkit.features import load_test_timeline as tl

# Finer between 800 and 2000: the first run went from healthy at 800 to Traefik
# OOMKilled at 1600, a cliff too wide to read.
STEPS = (50, 100, 200, 400, 800, 1000, 1200, 1400, 1600, 2000, 3200, 6400)
BASELINE_RATE = 25  # below the limiter's 30/s, so it needs no route at all
STEP_SECONDS = 60
# Each step opens with this much load on the same virtual users before the verdict starts
# reading (#3294). Run d46f3fbb: a healthy step settled 4 to 6 s into the step, and every
# degraded one recovered between t = 16 and 32 s of the sampler, which starts about 2 s
# before k6. 30 s covers that range and leaves no margin, so the report checks the warm
# rows of the timeline are flat instead of assuming it.
WARMUP_SECONDS = 30
SETTLE_SECONDS = 15
TOP_AFTER_SECONDS = 45  # metrics-server averages over about 15 s
# The sampler outlives the step by this much: k6's container starts a few seconds after
# the sampler, so the rise and fall of the edge's rate mark where k6 ran (#3102).
TIMELINE_TAIL_SECONDS = 10
TIMELINE_READ_TIMEOUT = 8
# The step's ssh masters outlive the sampling by this much, and are closed explicitly anyway.
MUX_MARGIN_SECONDS = 60

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
BYPASS_PLACEHOLDER = "__LOAD_TEST_BYPASS_VALUE__"  # the manifest's stand-in for the run's value
BYPASS_VALUE_SHAPE = re.compile(r"[0-9a-f]{32}")
ROUTE_NAME = "load-test"
ROUTE_MANIFEST = "infra/load-test/limiter-bypass-route.yaml"
SCRIPT = "infra/load-test/constant-rate.js"
STAGING_NAME = re.compile(r"(^|\.)staging\.[a-z0-9.-]+$")

# Where a request's time went (#3102). `http_req_duration` is sending + waiting +
# receiving and leaves out `blocked`, the time before the request had a connection,
# which includes `connecting` and `tls_handshaking` when it had to open one.
PHASES = ("blocked", "connecting", "tls_handshaking", "waiting", "receiving")


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


# What the client may declare it accepts. k6 sends `Accept-Encoding: gzip` unless told
# otherwise, so a server that compresses per request pays for it on every request;
# `identity` is the other arm of that A/B. The value lands unquoted in `docker run -e`.
ACCEPT_ENCODINGS = ("gzip", "identity")


def refuse_unknown_encoding(value: str) -> None:
    if value not in ACCEPT_ENCODINGS:
        raise LoadTestRefused(f"accept-encoding must be one of {ACCEPT_ENCODINGS}, not {value!r}")


def new_bypass_value() -> str:
    """The header value for one run: 128 random bits, so a leftover route opens nothing."""
    return secrets.token_hex(16)


def render_route(manifest: str, value: str) -> str:
    """The bypass route with this run's value in every rule.

    The value lands inside a Traefik matcher, so only the shape `new_bypass_value`
    draws is accepted; anything else could rewrite the rule.
    """
    if not BYPASS_VALUE_SHAPE.fullmatch(value):
        raise LoadTestRefused("the bypass value must be 32 lowercase hex characters, drawn per run")
    if BYPASS_PLACEHOLDER not in manifest:
        raise LoadTestRefused(f"the route manifest has no {BYPASS_PLACEHOLDER}: it would arm a fixed value")
    return manifest.replace(BYPASS_PLACEHOLDER, value)


def k6_env(
    target: Target,
    address: str,
    rate: int,
    seconds: int,
    bypass: str | None,
    accept_encoding: str | None = None,
    warmup: int = 0,
) -> dict[str, str]:
    env = {
        "LT_HOST": target.host,
        "LT_PATH": target.path,
        "LT_ADDRESS": address,
        "LT_RATE": str(rate),
        "LT_SECONDS": str(seconds),
        "LT_WARMUP": str(warmup),
    }
    if bypass is not None:
        env |= {"LT_BYPASS_HEADER": BYPASS_HEADER, "LT_BYPASS_VALUE": bypass}
    if accept_encoding is not None:
        refuse_unknown_encoding(accept_encoding)
        env["LT_ACCEPT_ENCODING"] = accept_encoding
    return env


def k6_command(image: str, env: dict[str, str]) -> str:
    """One remote shell runs this, so every value is quoted, not only the ones checked."""
    flags = " ".join(f"-e {shlex.quote(f'{key}={value}')}" for key, value in sorted(env.items()))
    return f"docker run --rm -i --network host {flags} {shlex.quote(image)} run --quiet --no-usage-report -"


def parse_summary(stdout: str, warmup: int = 0, seconds: int = 0) -> dict[str, Any]:
    """The figures of one step, from the metrics k6 printed. Latencies in ms.

    With a warm-up, the step's figures are those of its `warm` phase and the warm-up's
    are kept under `cold` (#3294). What k6 does not tag per request (429s, VUs, dropped
    iterations) stays step-wide, so a 429 in either phase still marks the route absent.
    """
    metrics = json.loads(stdout.strip().splitlines()[-1])

    def value(metric: str, key: str) -> float:
        return float(metrics.get(metric, {}).get("values", {}).get(key, 0))

    def figures(tag: str, span: int) -> dict[str, Any]:
        def named(metric: str) -> str:
            return f"{metric}{{phase:{tag}}}" if tag else metric

        count = value(named("http_reqs"), "count")
        return {
            "requests": count,
            # k6's own rate of a submetric is over the whole test, so the phase's comes from its length.
            "achieved_rps": round(count / span, 1) if tag else value("http_reqs", "rate"),
            "error_rate": value(named("http_req_failed"), "rate"),
            **{name: value(named("http_req_duration"), key) for name, key in _DURATION},
            "phases": {
                phase: {name: value(named(f"http_req_{phase}"), key) for name, key in _PHASE_STATS} for phase in PHASES
            },
        }

    primary = "warm" if warmup > 0 else ""
    required = "http_req_duration{phase:warm}" if primary else "http_req_duration"
    if required not in metrics:
        raise KeyError(required)  # a summary without the step's own figures is unreadable, not zero
    step = {
        **figures(primary, seconds),
        "status_429": value("status_429", "count"),
        "dropped": value("dropped_iterations", "count"),
        "vus_peak": value("vus", "max"),
    }
    if primary:
        step["cold"] = figures("cold", warmup)
    return step


_DURATION = (
    ("avg_ms", "avg"),
    ("p50_ms", "med"),
    ("p90_ms", "p(90)"),
    ("p95_ms", "p(95)"),
    ("p99_ms", "p(99)"),
    ("max_ms", "max"),
)
_PHASE_STATS = (("p50_ms", "med"), ("p95_ms", "p(95)"), ("p99_ms", "p(99)"), ("max_ms", "max"))


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


def cold_reasons(step: dict[str, Any], rate: int, bypass: bool = True) -> list[str]:
    """The same limits applied to the step's warm-up, with what is step-wide left as it is."""
    return classify({**step, **step["cold"]}, rate, bypass)


def cold_knee(steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The knee of the cold bursts: how much connection setup ace1 absorbs at once (#3294)."""
    if not steps or any("cold_reasons" not in s for s in steps):
        return None
    return knee([{**s, "reasons": s["cold_reasons"]} for s in steps])


def knee(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """The last healthy rate, the first that was not, and whether that reads as a bound.

    A ramp that ended on the generator, or never degraded, says nothing about where
    the service stops: `last_healthy_rps` is then only a lower bound. One stopped by
    the limiter measured nothing at all, and neither did one a rollout cut short,
    nor one whose generator saturated on the first step, before any healthy step
    gave a figure to bound, nor a ramp with no steps: `measured` is then false and no figure stands beside it."""
    healthy = [s["rate"] for s in steps if not s["reasons"]]
    bad = next((s for s in steps if s["reasons"]), None)
    reasons = set(bad["reasons"]) if bad else set()
    measured = bool(steps) and not ({"limiter", "rollout"} & reasons or ("generator" in reasons and not healthy))
    last = healthy[-1] if healthy and measured else None
    return {
        "measured": measured,
        "last_healthy_rps": last,
        "first_degraded_rps": bad["rate"] if bad and measured else None,
        "reasons": bad["reasons"] if bad else [],
        "lower_bound_only": measured and (bad is None or "generator" in bad["reasons"]),
        "vus_at_last_healthy": next((s["vus_peak"] for s in steps if s["rate"] == last), None)
        if last is not None
        else None,
    }


def cpu_percent(before: str, after: str) -> float:
    """Busy share of the node between two `cpu` lines of /proc/stat."""
    # user..steal only: guest and guest_nice are already counted in user and nice.
    first, second = ([int(x) for x in line.split()[1:9]] for line in (before, after))
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

    def ssh(
        self, node: str, command: str, stdin: str | None = None, timeout: int = 60, options: tuple[str, ...] = ()
    ) -> str:
        done = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", *options, node, command],
            input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=timeout, check=True,
        )  # fmt: skip
        return done.stdout

    @contextmanager
    def multiplexed(self, nodes: tuple[str, ...], seconds: int) -> Iterator[tuple[str, ...]]:
        """One ssh connection per node for a step's timeline, so a sample costs a session, not a handshake.

        A handshake per sample cost ace1 0.1 to 0.2 cores at rest, on the node under test (#3295).
        The masters live in a directory of their own, never the operator's ~/.ssh, and are closed
        when the step ends, failed or not. A master that does not open leaves the readers on direct
        connections: with `ControlMaster=no`, ssh connects directly when the socket is missing or stale
        (checked against ace1, both cases exit 0).
        """
        control = tempfile.mkdtemp(prefix="lt-", dir="/tmp")  # a unix socket path caps near 104 bytes on macOS
        path = ("-o", f"ControlPath={control}/%C")
        try:
            for node in nodes:
                self._ssh_control(node, *path, "-o", "ControlMaster=yes", "-o", f"ControlPersist={seconds}", "-fN")
            yield (*path, "-o", "ControlMaster=no")
        finally:
            for node in nodes:
                self._ssh_control(node, *path, "-O", "exit")
            shutil.rmtree(control, ignore_errors=True)

    @staticmethod
    def _ssh_control(node: str, *args: str) -> None:
        try:
            subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", *args, node],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=15, check=False,
            )  # fmt: skip
        except (subprocess.SubprocessError, OSError):
            pass  # best effort both ways: a missing master costs a handshake per read, not the step

    def kubectl(self, *args: str, impersonate: bool = False, stdin: str | None = None) -> str:
        cmd = ["kubectl", "--kubeconfig", self.kubeconfig, *args]
        if impersonate:
            cmd.append(f"--as={self.operator_as}")
        return subprocess.run(
            cmd, input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=60, check=True
        ).stdout

    def assert_cluster(self) -> None:
        """The kubeconfig reaches the single staging node, or nothing is applied."""
        names = self.kubectl("get", "nodes", "-o", "name").split()
        if names != [f"node/{self.target_node}"]:
            raise LoadTestRefused(f"kubeconfig reaches {names}, not node/{self.target_node}")

    def arm(self, value: str) -> None:
        """Apply, not create: a route a dead run left is replaced, so it lives until the next run at most."""
        manifest = (self.root / ROUTE_MANIFEST).read_text(encoding="utf-8")
        self.kubectl("apply", "-f", "-", impersonate=True, stdin=render_route(manifest, value))

    def disarm(self) -> None:
        self.kubectl("delete", "-f", str(self.root / ROUTE_MANIFEST), "--ignore-not-found", impersonate=True)

    def pod(self, workload: str, namespace: str = "kubelab") -> dict[str, Any]:
        out = self.kubectl("get", "pods", "-n", namespace, "-l", f"app.kubernetes.io/name={workload}", "-o", "json")
        items = [p for p in json.loads(out)["items"] if p["status"].get("phase") == "Running"]
        if not items:
            raise LoadTestRefused(f"no running pod for {workload} in {namespace}")
        return items[0]

    def restarts(self, workload: str, namespace: str = "kubelab") -> int:
        return sum(c["restartCount"] for c in self.pod(workload, namespace)["status"]["containerStatuses"])

    def edge_state(self) -> tuple[str, int]:
        """The pod's identity with its count: a replaced pod starts counting from zero again."""
        try:
            pod = self.pod(EDGE_WORKLOAD, EDGE_NAMESPACE)
        except LoadTestRefused:
            return "", 0  # an edge down right now is a restart to record, not a reason to lose the ramps
        return pod["metadata"]["uid"], sum(c["restartCount"] for c in pod["status"]["containerStatuses"])

    def edge_ready(self) -> bool:
        try:
            pod = self.pod(EDGE_WORKLOAD, EDGE_NAMESPACE)
        except LoadTestRefused:
            return False
        return all(c["ready"] for c in pod["status"]["containerStatuses"])

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

    def timeline_readers(self, workload: str, ssh_options: tuple[str, ...] = ()) -> tl.Readers:
        """Resolve the pods once per step; each sample is then one GET and two ssh reads."""
        edge = self.pod(EDGE_WORKLOAD, EDGE_NAMESPACE)
        ports = [p for c in edge["spec"]["containers"] for p in c.get("ports", []) if p.get("name") == "metrics"]
        if not ports:
            raise LoadTestRefused(f"{EDGE_WORKLOAD} declares no port named metrics")
        path = f"/api/v1/namespaces/{EDGE_NAMESPACE}/pods/{edge['metadata']['name']}:{ports[0]['containerPort']}"
        command = tl.node_command(edge["metadata"]["uid"], self.pod(workload)["metadata"]["uid"])
        return tl.Readers(
            edge=lambda: tl.parse_edge(
                self.kubectl("get", "--raw", f"{path}/proxy/metrics", f"--request-timeout={TIMELINE_READ_TIMEOUT}s")
            ),
            node=lambda: tl.parse_node(
                self.ssh(self.target_node, command, timeout=TIMELINE_READ_TIMEOUT, options=ssh_options)
            ),
            generator=lambda: tl.parse_cpu_line(
                self.ssh(self.generator, "head -1 /proc/stat", timeout=TIMELINE_READ_TIMEOUT, options=ssh_options)
            ),
        )

    def top(self, workload: str) -> dict[str, str]:
        out = self.kubectl("top", "pod", "-A", "--no-headers", "-l", f"app.kubernetes.io/name in ({workload},traefik)")
        return {row[1].rsplit("-", 2)[0]: f"{row[2]} {row[3]}" for row in (line.split() for line in out.splitlines())}


def run_step(
    lab: Lab,
    image: str,
    script: str,
    target: Target,
    address: str,
    rate: int,
    seconds: int,
    bypass: str | None,
    accept_encoding: str | None = None,
    sample_seconds: int = 0,
    warmup: int = 0,
) -> dict[str, Any]:
    """One step with the node's figures around it. The generator's CPU decides its validity.

    `bypass` is the run's header value, or None for a step under the limiter.
    `sample_seconds` above zero adds the step's timeline, one row per interval.
    """
    env = k6_env(target, address, rate, seconds, bypass, accept_encoding, warmup)
    lasts = warmup + seconds
    before = {n: lab.cpu_line(n) for n in (lab.target_node, lab.generator)}
    stat_before = lab.cpu_stat(target.workload)
    pod_before = lab.pod(target.workload)["metadata"]["uid"]
    edge_before = lab.edge_state()
    with ExitStack() as stack:
        readers = None
        if sample_seconds > 0:
            sampled = lasts + TIMELINE_TAIL_SECONDS
            nodes = (lab.target_node, lab.generator)
            options = stack.enter_context(lab.multiplexed(nodes, sampled + MUX_MARGIN_SECONDS))
            readers = lab.timeline_readers(target.workload, options)
        with ThreadPoolExecutor(max_workers=3) as pool:
            timeline = (
                pool.submit(tl.sample_timeline, readers, sampled, sample_seconds) if readers is not None else None
            )
            k6 = pool.submit(lab.ssh, lab.generator, k6_command(image, env), script, lasts + 120)
            # In the warm window: with a warm-up, `pods_top` describes the state the verdict reads.
            mid = pool.submit(_sample_mid_step, lab, target.workload, warmup + min(TOP_AFTER_SECONDS, seconds))
            stdout = k6.result()
            top, memory = mid.result()
            sampled_rows = timeline.result() if timeline is not None else None
    step: dict[str, Any] = {"rate": rate, "target": target.name, **parse_summary(stdout, warmup, seconds)}
    if warmup > 0:
        step["warmup_seconds"] = warmup
    if sampled_rows is not None:
        step["timeline"] = sampled_rows
    step["node_cpu"] = cpu_percent(before[lab.target_node], lab.cpu_line(lab.target_node))
    step["generator_cpu"] = cpu_percent(before[lab.generator], lab.cpu_line(lab.generator))
    step["node_mem_available_mb"] = memory
    step["pods_top"] = top
    step["throttled_ms"] = throttled_ms(stat_before, lab.cpu_stat(target.workload))
    step["edge_restarts"] = edge_restarts_between(edge_before, lab.edge_state())
    step["pod_replaced"] = lab.pod(target.workload)["metadata"]["uid"] != pod_before
    step["reasons"] = classify(step, rate, bypass is not None)
    if "cold" in step:
        step["cold_reasons"] = cold_reasons(step, rate, bypass is not None)
    return step


def _sample_mid_step(lab: Lab, workload: str, delay: int) -> tuple[dict[str, str], int]:
    import time

    time.sleep(delay)
    return lab.top(workload), lab.memory_available_mb(lab.target_node)


def edge_restarts_between(before: tuple[str, int], after: tuple[str, int]) -> int:
    """Restarts between two readings; a pod replaced in between counts as at least one."""
    return after[1] - before[1] if after[0] == before[0] else max(after[1], 1)


def cleanup(lab: Lab, image: str) -> None:
    """Both halves always run: a route left armed still fails the command that left it."""
    try:
        lab.disarm()
    except (subprocess.SubprocessError, OSError) as e:
        raise LoadTestRefused("the route may still be armed: run make load-test-clear") from e
    finally:
        lab.ssh(lab.generator, f"docker image rm {image} >/dev/null 2>&1 || true")


def wait_for_stable_edge(ready: Any, state: Any, sleep: Any, stable: int, limit: int, poll: int = 10) -> None:
    """Return once the edge has been ready, with an unchanged `state`, for `stable` seconds."""
    calm, seen = 0, state()
    for _ in range(0, limit, poll):
        sleep(poll)
        now = state()
        calm = calm + poll if ready() and now == seen else 0
        seen = now
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


def select_steps(min_rate: int, max_rate: int) -> tuple[int, ...]:
    """The ramp's steps from `min_rate` to `max_rate`, both inclusive."""
    return tuple(rate for rate in STEPS if min_rate <= rate <= max_rate)


def refuse_empty_run(repeats: int, seconds: int, max_rate: int, min_rate: int = 0) -> None:
    """A run that would measure nothing must not write a report that looks like one."""
    if repeats < 1 or seconds < 1 or not select_steps(min_rate, max_rate):
        raise LoadTestRefused(f"repeats and seconds must be at least 1, and the rates must include a step of {STEPS}")


def run(
    lab: Lab,
    image: str,
    targets: tuple[Target, ...],
    address: str,
    repeats: int,
    seconds: int,
    max_rate: int,
    checkpoint: Any = lambda _result: None,
    min_rate: int = 0,
    accept_encoding: str | None = None,
    sample_seconds: int = 0,
    warmup: int = 0,
) -> dict[str, Any]:
    """Baseline under the limiter, then `repeats` ramps past it. Always removes the route.

    `checkpoint` gets the result so far, marked incomplete, after the baseline and each
    ramp, so a run that dies later keeps what it measured.
    """
    import time

    refuse_empty_run(repeats, seconds, max_rate, min_rate)
    if accept_encoding is not None:
        refuse_unknown_encoding(accept_encoding)
    lab.assert_cluster()
    script = (lab.root / SCRIPT).read_text(encoding="utf-8")
    if sample_seconds < 0:
        raise LoadTestRefused("sample seconds must be 0 (off) or positive")
    if warmup < 0:
        raise LoadTestRefused("warm-up seconds must be 0 (off) or positive")
    facts = {
        **_runtime_facts(lab, image),
        "accept_encoding": accept_encoding or "gzip (k6 default)",
        "sample_seconds": sample_seconds,
    }
    steps = select_steps(min_rate, max_rate)
    restarts = {t.workload: lab.restarts(t.workload) for t in targets}
    edge_at_start = lab.edge_state()

    def stable_edge() -> None:
        wait_for_stable_edge(
            lab.edge_ready,
            lab.edge_state,
            time.sleep,
            EDGE_STABLE_SECONDS,
            EDGE_WAIT_SECONDS,
        )

    stable_edge()
    baselines = [
        run_step(
            lab,
            image,
            script,
            t,
            address,
            BASELINE_RATE,
            seconds,
            bypass=None,
            accept_encoding=accept_encoding,
            sample_seconds=sample_seconds,
            warmup=warmup,
        )  # fmt: skip
        for t in targets
    ]
    ramps: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "facts": facts,
        "criteria": {
            "max_error_rate": MAX_ERROR_RATE,
            "max_p95_ms": MAX_P95_MS,
            "min_achieved_ratio": MIN_ACHIEVED,
            "max_generator_cpu": MAX_GENERATOR_CPU,
            "step_seconds": seconds,
            "warmup_seconds": warmup,
            "settle_seconds": SETTLE_SECONDS,
        },
        "baseline": baselines,
        "ramps": ramps,
    }
    checkpoint({**result, "incomplete": True})
    bypass = new_bypass_value()  # held in memory only: never in `result`, so never in docs/load-test
    try:
        lab.arm(bypass)
        time.sleep(SETTLE_SECONDS)  # Traefik watches the CRD; give the router time to load
        for repeat in range(1, repeats + 1):
            for target in targets:

                def one(rate: int, target: Target = target) -> dict[str, Any]:
                    return run_step(
                        lab, image, script, target, address, rate, seconds,
                        bypass=bypass, accept_encoding=accept_encoding, sample_seconds=sample_seconds, warmup=warmup,
                    )  # fmt: skip

                done = ramp(one, steps, lambda: time.sleep(SETTLE_SECONDS))
                entry = {"target": target.name, "repeat": repeat, "steps": done, "knee": knee(done)}
                cold = cold_knee(done)
                if cold is not None:
                    entry["cold_knee"] = cold
                ramps.append(entry)
                checkpoint({**result, "incomplete": True})
                stable_edge()
    finally:
        cleanup(lab, image)
    result["restarts_during_run"] = {
        **{w: lab.restarts(w) - before for w, before in restarts.items()},
        EDGE_WORKLOAD: edge_restarts_between(edge_at_start, lab.edge_state()),
    }
    return result


def render(result: dict[str, Any]) -> str:
    """The raw figures as one Markdown table per ramp."""
    head = (
        "| rate/s | achieved/s | requests | p50 ms | p90 ms | p95 ms | p99 ms | max ms | errors | 429 | dropped | "
        "peak VUs | in flight | node CPU % | generator CPU % | node mem free MB | "
        "throttled ms | pods | verdict |\n"
        "|" + "---|" * 19
    )

    def row(s: dict[str, Any]) -> str:
        pods = "; ".join(f"{k} {v}" for k, v in s["pods_top"].items())
        cells = [
            s["rate"], f"{s['achieved_rps']:.1f}", int(s["requests"]), f"{s['p50_ms']:.2f}", f"{s['p90_ms']:.2f}",
            f"{s['p95_ms']:.2f}", f"{s['p99_ms']:.2f}", f"{s['max_ms']:.1f}", f"{s['error_rate']:.2%}",
            int(s["status_429"]), int(s["dropped"]), int(s["vus_peak"]),
            f"{s['achieved_rps'] * s['avg_ms'] / 1000:.1f}",
            s["node_cpu"], s["generator_cpu"],
            s["node_mem_available_mb"], f"{s['throttled_ms']:.0f}", pods, ",".join(s["reasons"]) or "healthy",
        ]  # fmt: skip
        return "| " + " | ".join(str(c) for c in cells) + " |"

    phase_head = (
        "| rate/s | " + " | ".join(f"{p} p95 | {p} p99" for p in PHASES) + " |\n" + "|" + "---|" * (1 + 2 * len(PHASES))
    )

    def phase_row(s: dict[str, Any]) -> str:
        cells = [str(s["rate"])]
        cells += [f"{s['phases'][p][k]:.1f}" for p in PHASES for k in ("p95_ms", "p99_ms")]
        return "| " + " | ".join(cells) + " |"

    def phase_table(steps: list[dict[str, Any]]) -> list[str]:
        timed = [s for s in steps if "phases" in s]  # runs before #3102 have none
        return ["", "Where the time went, ms:", "", phase_head, *map(phase_row, timed)] if timed else []

    cold_head = (
        "| rate/s | cold achieved/s | cold requests | cold p95 ms | cold p99 ms | cold errors | cold verdict |\n"
        + "|"
        + "---|" * 7
    )

    def cold_row(s: dict[str, Any]) -> str:
        c = s["cold"]
        cells = [
            s["rate"], f"{c['achieved_rps']:.1f}", int(c["requests"]), f"{c['p95_ms']:.2f}", f"{c['p99_ms']:.2f}",
            f"{c['error_rate']:.2%}", ",".join(s["cold_reasons"]) or "healthy",
        ]  # fmt: skip
        return "| " + " | ".join(str(x) for x in cells) + " |"

    def cold_table(steps: list[dict[str, Any]]) -> list[str]:
        burst = [s for s in steps if "cold" in s]  # runs before #3294 have none
        if not burst:
            return []
        return ["", "The warm-up, read as a cold connection burst:", "", cold_head, *map(cold_row, burst)]

    meta = {k: result[k] for k in ("date", "commit", "facts", "criteria", "restarts_during_run") if k in result}
    lines = ["**Incomplete: this run stopped before its last ramp.**", ""] if result.get("incomplete") else []
    lines += ["```json", json.dumps(meta, indent=2), "```", "", "## Baseline under the limiter", "", head]
    lines += [row(s) for s in result["baseline"]]
    for r in result["ramps"]:
        lines += ["", f"## {r['target']}, ramp {r['repeat']}", "", f"Knee: `{json.dumps(r['knee'])}`"]
        if "cold_knee" in r:
            lines += ["", f"Cold knee: `{json.dumps(r['cold_knee'])}`"]
        lines += ["", head]
        lines += [row(s) for s in r["steps"]]
        lines += phase_table(r["steps"])
        lines += cold_table(r["steps"])
    return "\n".join(lines) + "\n"
