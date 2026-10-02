"""The on-demand freshness and shrink rules, evaluated in a real Loki (BACKUP-032 AC2, AC3).

A ship that never starts on an on-demand node pages nobody: the failure hook
needs the unit to run, and the node's Uptime Kuma heartbeat is muted for the
`on-demand` tag. The freshness rule closes that gap from the destination, and
only while the node is up: off is that node's normal state (ADR-028).

Every fixture line here is printed by the real `probe.sh`, run against a fake
restic and a fake `nc`, never written by hand. So the rule and the emitter are
tested against one label set: a rule that filters on a label the probe stopped
emitting goes red here instead of paging forever through `noDataState` (the
OBS-018 shape, #1377).
"""

from __future__ import annotations

import datetime
import itertools
import json
import os
import pathlib
import re
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
import yaml

from tests.loki_harness import ALERTING_DIR, Loki, rule_expr, run_loki, slot, stream_labels
from tests.test_r2_backup_watcher_probe import FAKE_NC, FAKE_RESTIC, PREFIX, PROBE, STAGING, _listing

FRESHNESS = "backup032-on-demand-freshness"
SHRINK = "backup032-r2-backup-shrink"
HEALTH = "obs015-r2-backup-health"
THREE_HOURS = 3 * 3600
PROBE_INTERVAL = 6 * 3600
# The K8s node the Job ran on, as Vector labels it: a different thing from the
# backup node a line reports on, and the reason the rules extract `backup_node`.
K8S_NODE = "k8s-node-fixture"
_case = itertools.count()


@dataclass
class Node:
    name: str
    cls: str
    up: bool = True
    # Seconds between the newest snapshot and the probe; None is restic failing.
    age: int | None = 3600
    size: int | None = 1_000_000


def _probe(tmp_path: pathlib.Path, nodes: list[Node], now: int) -> list[dict]:
    """Run the real probe once, at `now`, over `nodes`; return every line it printed."""
    run = tmp_path / f"run-{now}"
    fake, bin_dir = run / "fake", run / "bin"
    fake.mkdir(parents=True)
    bin_dir.mkdir()
    for name, body in (("restic", FAKE_RESTIC), ("nc", FAKE_NC)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    rows = []
    for index, node in enumerate(nodes, start=1):
        address, repository_id = f"192.0.2.{index}", f"{index}" * 64
        rows.append(f"{node.name} {PREFIX}/{node.name} {repository_id} {address} 22 {node.cls} app")
        (fake / f"{node.name}.id").write_text(repository_id)
        (fake / f"{node.name}.ls").write_text(_listing("app"))
        if node.age is None:
            (fake / f"{node.name}.fail").write_text("Fatal: unable to open config file\n")
        else:
            stamp = datetime.datetime.fromtimestamp(now - node.age, datetime.timezone.utc)
            (fake / f"{node.name}.snaps").write_text(
                json.dumps([{"time": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"), "id": "x", "short_id": "s"}])
            )
        if node.size is None:
            (fake / f"{node.name}.nostats").write_text("")
        else:
            (fake / f"{node.name}.size").write_text(str(node.size))
        if not node.up:
            (fake / f"{address}.down").write_text("")
    targets = run / "targets.txt"
    targets.write_text("\n".join(rows) + "\n")
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_DIR": str(fake),
        "WATCHER_TARGETS": str(targets),
        "STAGING_DIR": STAGING,
        "RESTIC_TIMEOUT": "2",
        "REACH_TIMEOUT": "1",
        "NC": str(bin_dir / "nc"),
        "PROBE_NOW": str(now),
        "RESTIC_PASSWORD": "not-a-real-value-fixture",
        "AWS_ACCESS_KEY_ID": "not-a-real-value-fixture",
        "AWS_SECRET_ACCESS_KEY": "not-a-real-value-fixture",
    }
    proc = subprocess.run(["sh", str(PROBE)], env=env, capture_output=True, text=True, timeout=60)
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


@pytest.fixture(scope="module")
def loki() -> Iterator[Loki]:
    yield from run_loki()


class Case:
    """One scenario in its own time slot and its own stream, so cases never meet."""

    def __init__(self, loki: Loki, tmp_path: pathlib.Path) -> None:
        self.loki, self.tmp_path = loki, tmp_path
        self.start = slot(next(_case))

    def probe(self, offset: int, nodes: list[Node]) -> list[dict]:
        """Probe at `start + offset` and ship the lines to Loki with that timestamp.

        Each run is a new Job pod, so each lands in its own stream, as in prod."""
        at = self.start + offset
        records = _probe(self.tmp_path, nodes, at)
        labels = stream_labels(
            namespace="kubelab",
            container="r2-backup-watcher",
            pod=f"r2-backup-watcher-{at}",
            node=K8S_NODE,
        )
        self.loki.push({**labels, "case": str(self.start)}, [(at, record) for record in records])
        return records

    def value(self, uid: str, offset: int) -> dict[str, float]:
        """The rule's query at `start + offset`, keyed by backup node (or namespace for fleet rules)."""
        result = self.loki.query(rule_expr(uid), self.start + offset)
        return {dict(labels).get("backup_node", dict(labels).get("namespace", "")): v for labels, v in result.items()}


@pytest.fixture
def case(loki: Loki, tmp_path: pathlib.Path) -> Case:
    return Case(loki, tmp_path)


def _over(values: dict[str, float]) -> set[str]:
    return {node for node, v in values.items() if v > THREE_HOURS}


def _held(case: Case) -> set[str]:
    """Nodes over the threshold at every evaluation from just after the first probe
    to just after the second: what `for:` asks, sampled either side of the boundary."""
    times = (60, PROBE_INTERVAL - 60, PROBE_INTERVAL + 60, PROBE_INTERVAL + 3600)
    return set.intersection(*(_over(case.value(FRESHNESS, t)) for t in times))


# --------------------------------------------------------------------- harness


def test_the_harness_reads_the_existing_health_rule_both_ways(case: Case) -> None:
    """The harness itself, proven on a rule already in production before it judges a new one."""
    case.probe(0, [Node("vps", "always-on")])
    assert case.value(HEALTH, 60) == {"kubelab": 1.0}
    case.probe(PROBE_INTERVAL, [Node("vps", "always-on", age=None)])
    assert case.value(HEALTH, PROBE_INTERVAL + 60) == {"kubelab": 0.0}


# ------------------------------------------------------------------ freshness


def test_a_reachable_on_demand_node_that_stopped_shipping_fires(case: Case) -> None:
    case.probe(0, [Node("beelink", "on-demand", age=4 * 3600), Node("vps", "always-on")])
    case.probe(PROBE_INTERVAL, [Node("beelink", "on-demand", age=10 * 3600), Node("vps", "always-on")])
    assert _held(case) == {"beelink"}


def test_each_on_demand_node_is_judged_on_its_own(case: Case) -> None:
    """Two on-demand nodes in one probe, one stale and one fresh: only the stale
    one fires. Rules that group on Vector's `node` label (the K8s node) fold both
    into one series and judge whichever line came last (lesson-512)."""
    nodes = [Node("beelink", "on-demand", age=10 * 3600), Node("rpi4", "on-demand", age=600)]
    case.probe(0, nodes)
    case.probe(PROBE_INTERVAL, nodes)
    assert _held(case) == {"beelink"}


@pytest.mark.parametrize(
    "scenario",
    ["off both times", "turned off before the second probe", "fresh", "always-on and stale"],
)
def test_the_freshness_rule_stays_silent(case: Case, scenario: str) -> None:
    first, second = {
        "off both times": (Node("beelink", "on-demand", up=False, age=30 * 3600),) * 2,
        "turned off before the second probe": (
            Node("beelink", "on-demand", age=4 * 3600),
            Node("beelink", "on-demand", up=False, age=10 * 3600),
        ),
        "fresh": (Node("beelink", "on-demand", age=600),) * 2,
        # Its own heartbeat is not muted; this rule is not its judge.
        "always-on and stale": (Node("vps", "always-on", age=30 * 3600),) * 2,
    }[scenario]
    case.probe(0, [first])
    case.probe(PROBE_INTERVAL, [second])
    assert _held(case) == set()


def test_every_on_demand_node_off_is_a_zero_never_no_data(case: Case) -> None:
    """The homelab off is the common case. The rule answers 0 for each node, so it
    is never "no data", which `noDataState: Alerting` would turn into a page."""
    nodes = [Node("beelink", "on-demand", up=False, age=50 * 3600), Node("rpi4", "on-demand", up=False, age=50 * 3600)]
    case.probe(0, [*nodes, Node("vps", "always-on")])
    assert case.value(FRESHNESS, 60) == {"beelink": 0.0, "rpi4": 0.0}


def test_a_restic_failure_is_the_health_rules_page_not_this_ones(case: Case) -> None:
    """A `null` age is dropped by `unwrap`, so this rule is silent for that node,
    and the node is unhealthy, so the health rule pages instead: one cause, one page."""
    nodes = [Node("beelink", "on-demand", age=None), Node("vps", "always-on")]
    case.probe(0, nodes)
    case.probe(PROBE_INTERVAL, nodes)
    assert "beelink" not in case.value(FRESHNESS, PROBE_INTERVAL + 60)
    assert case.value(HEALTH, PROBE_INTERVAL + 60) == {"kubelab": 0.0}


# --------------------------------------------------------------------- shrink


@pytest.mark.parametrize(
    ("before", "after", "fires"),
    [
        (1_000_000, 400_000, True),
        (1_000_000, 700_000, False),
        (1_000_000, 2_000_000, False),
        # `stats` failed this time: `null` is dropped, so the last size is the
        # previous one and nothing shrank.
        (1_000_000, None, False),
    ],
)
def test_the_shrink_rule_fires_only_on_a_drop_of_more_than_half(case: Case, before, after, fires) -> None:
    case.probe(0, [Node("rpi4", "on-demand", size=before)])
    case.probe(PROBE_INTERVAL, [Node("rpi4", "on-demand", size=after)])
    values = case.value(SHRINK, PROBE_INTERVAL + 60)
    assert ({n for n, v in values.items() if v < 0.5} == {"rpi4"}) is fires, values


def test_nodes_of_different_sizes_never_read_as_a_shrink(case: Case) -> None:
    """Sizes are compared per backup node, never across them: a small node after
    a large one is not a drop (the first rules divided vps by beelink, lesson-512)."""
    nodes = [Node("beelink", "on-demand", size=2_000_000), Node("vps", "always-on", size=500_000)]
    case.probe(0, nodes)
    case.probe(PROBE_INTERVAL, nodes)
    assert case.value(SHRINK, PROBE_INTERVAL + 60) == {"beelink": 1.0, "vps": 1.0}


def test_the_fixture_streams_carry_every_label_vector_sets() -> None:
    """The guard on the guard: fixtures pushed without Vector's labels would
    prove the rules against a stream shape prod never has."""
    with pytest.raises(ValueError):
        stream_labels(namespace="kubelab", container="r2-backup-watcher")


def test_a_single_probe_never_reads_as_a_shrink(case: Case) -> None:
    case.probe(0, [Node("rpi4", "on-demand", size=1_000_000)])
    assert case.value(SHRINK, 60) == {"rpi4": 1.0}


# --------------------------------------------------------------------- static


def _rule(uid: str) -> dict:
    for path in sorted(ALERTING_DIR.glob("*.yaml")):
        for group in (yaml.safe_load(path.read_text()) or {}).get("groups") or []:
            for rule in group.get("rules") or []:
                if rule.get("uid") == uid:
                    return rule
    raise KeyError(uid)


def _hours(duration: str) -> float:
    units = {"h": 3600, "m": 60, "s": 1}
    return sum(int(n) * units[u] for n, u in re.findall(r"(\d+)([hms])", duration)) / 3600


def test_the_freshness_rule_waits_for_two_probes_and_judges_only_on_demand_nodes() -> None:
    """`for:` longer than one probe interval is what "two consecutive probes" means
    in Grafana: one stale line is a node that booted mid-window, two are not."""
    rule = _rule(FRESHNESS)
    assert _hours(rule["for"]) > PROBE_INTERVAL / 3600, rule["for"]
    assert rule["noDataState"] == "Alerting"
    expr = rule_expr(FRESHNESS)
    assert expr.count("class=`on-demand`") == 2, "both operands must select the same nodes"
    assert "unwrap snapshot_age_seconds" in expr and "unwrap reachable" in expr
    (threshold,) = next(d for d in rule["data"] if d["refId"] == "C")["model"]["conditions"]
    assert threshold["evaluator"] == {"type": "gt", "params": [THREE_HOURS]}


def test_the_shrink_rule_threshold_is_half() -> None:
    rule = _rule(SHRINK)
    (threshold,) = next(d for d in rule["data"] if d["refId"] == "C")["model"]["conditions"]
    assert threshold["evaluator"] == {"type": "lt", "params": [0.5]}
    assert rule["noDataState"] == "Alerting"
