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

from tests.loki_harness import ALERTING_DIR, REPO, Loki, rule_expr, run_loki, slot, stream_labels
from tests.test_r2_backup_watcher_probe import FAKE_NC, FAKE_RESTIC, PREFIX, PROBE, STAGING, _listing

FRESHNESS = "backup032-on-demand-freshness"
SHRINK = "backup032-r2-backup-shrink"
BUDGET = "backup081-check-budget"
UNMEASURED = "backup083-node-sizes-unmeasured"
HEALTH = "obs015-r2-backup-health"
WATCHER_MANIFEST = REPO / "infra/k8s/base/services/r2-backup-watcher.yaml"
NODE_BACKUP_DEFAULTS = REPO / "infra/ansible/roles/node_backup/defaults/main.yml"


def _seconds(duration: str) -> int:
    """A Go-style duration (`1h`, `90m`, `1h30m`) in seconds. Anything else raises:
    a unit this cannot read must fail the guard that uses it, never read as 0."""
    units = {"h": 3600, "m": 60, "s": 1}
    if not re.fullmatch(r"(\d+[hms])+", duration):
        raise ValueError(f"unreadable duration {duration!r}")
    seconds = sum(int(n) * units[u] for n, u in re.findall(r"(\d+)([hms])", duration))
    if seconds <= 0:
        raise ValueError(f"zero duration {duration!r}")
    return seconds


def _probe_interval() -> int:
    """Seconds between watcher runs, read from the CronJob `schedule:`, never retyped:
    the rule's `for:` and windows mean "two probes" only relative to it."""
    cron = next(
        d for d in yaml.safe_load_all(WATCHER_MANIFEST.read_text(encoding="utf-8")) if d and d.get("kind") == "CronJob"
    )
    schedule = cron["spec"]["schedule"]
    minute, hour, *rest = schedule.split()
    every = re.fullmatch(r"\*/(\d+)", hour)
    assert minute.isdigit() and every and rest == ["*", "*", "*"], f"unparsed schedule {schedule!r}"
    return int(every.group(1)) * 3600


def _ship_interval(defaults: pathlib.Path = NODE_BACKUP_DEFAULTS) -> int:
    """Seconds between ships on an on-demand node, from the role default that sets them."""
    return _seconds(yaml.safe_load(defaults.read_text(encoding="utf-8"))["node_backup_interval"])


STALE_AFTER = 12 * 3600  # three of the 4h ship intervals (#3035)
PROBE_INTERVAL = _probe_interval()
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
    # What size.sh wrote for the node's prefix; None is its listing failing.
    size: int | None = 1_000_000
    # What size.sh wrote for the packs under the node's `data/`; None is its listing failing.
    packs: int | None = 100


def _probe(tmp_path: pathlib.Path, nodes: list[Node], now: int) -> list[dict]:
    """Run the real probe once, at `now`, over `nodes`; return every line it printed."""
    run = tmp_path / f"run-{now}"
    fake, bin_dir = run / "fake", run / "bin"
    fake.mkdir(parents=True)
    bin_dir.mkdir()
    for name, body in (("restic", FAKE_RESTIC), ("nc", FAKE_NC)):
        (bin_dir / name).write_text(body, encoding="utf-8", newline="\n")
        (bin_dir / name).chmod(0o755)
    rows = []
    sizes = []
    for index, node in enumerate(nodes, start=1):
        address, repository_id = f"192.0.2.{index}", f"{index}" * 64
        rows.append(f"{node.name} {PREFIX}/{node.name} {repository_id} {address} 22 {node.cls} app")
        (fake / f"{node.name}.id").write_text(repository_id, encoding="utf-8", newline="\n")
        (fake / f"{node.name}.ls").write_text(_listing("app"), encoding="utf-8", newline="\n")
        if node.age is None:
            (fake / f"{node.name}.fail").write_text(
                "Fatal: unable to open config file\n", encoding="utf-8", newline="\n"
            )
        else:
            stamp = datetime.datetime.fromtimestamp(now - node.age, datetime.timezone.utc)
            (fake / f"{node.name}.snaps").write_text(
                json.dumps([{"time": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"), "id": "x", "short_id": "s"}]),
                encoding="utf-8",
                newline="\n",
            )
        sizes.append(f"node {node.name} {'null' if node.size is None else node.size} 1\n")
        sizes.append(f"packs {node.name} {'null' if node.packs is None else node.packs} 1\n")
        if not node.up:
            (fake / f"{address}.down").write_text("", encoding="utf-8", newline="\n")
    targets = run / "targets.txt"
    targets.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")
    bucket = sum(node.size or 0 for node in nodes)
    (run / "sizes.txt").write_text(
        "".join(sizes) + f"bucket {PREFIX.rsplit('/', 1)[1]} {bucket} 1\n", encoding="utf-8", newline="\n"
    )
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_DIR": str(fake),
        "WATCHER_TARGETS": str(targets),
        "WATCHER_SIZES": str(run / "sizes.txt"),
        "STAGING_DIR": STAGING,
        "RESTIC_TIMEOUT": "2",
        "REACH_TIMEOUT": "1",
        "NC": str(bin_dir / "nc"),
        "PROBE_NOW": str(now),
        "AWS_ACCESS_KEY_ID": "not-a-real-value-fixture",
        "AWS_SECRET_ACCESS_KEY": "not-a-real-value-fixture",
        # One per node, as the Secret carries them (BACKUP-057): the probe reads no shared key.
        **{f"RESTIC_PASSWORD_{node.name.upper()}": "not-a-real-value-fixture" for node in nodes},
    }
    proc = subprocess.run(["sh", str(PROBE)], env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
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
    return {node for node, v in values.items() if v > STALE_AFTER}


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
    case.probe(0, [Node("beelink", "on-demand", age=13 * 3600), Node("vps", "always-on")])
    case.probe(PROBE_INTERVAL, [Node("beelink", "on-demand", age=20 * 3600), Node("vps", "always-on")])
    assert _held(case) == {"beelink"}


def test_each_on_demand_node_is_judged_on_its_own(case: Case) -> None:
    """Two on-demand nodes in one probe, one stale and one fresh: only the stale
    one fires. Rules that group on Vector's `node` label (the K8s node) fold both
    into one series and judge whichever line came last (lesson-512)."""
    nodes = [Node("beelink", "on-demand", age=20 * 3600), Node("rpi4", "on-demand", age=600)]
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
            Node("beelink", "on-demand", up=False, age=20 * 3600),
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
        # The listing failed this time: `null` is dropped, so the last size is
        # the previous one and nothing shrank.
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


# ------------------------------------------------------------ unmeasured sizes

DAY = 24 * 3600


def _unmeasured(case: Case, offset: int) -> set[str]:
    """Nodes the rule would alert on at `offset`: the rule's threshold is `lt 1`."""
    return {node for node, v in case.value(UNMEASURED, offset).items() if v < 1}


def _probe_a_day(case: Case, nodes: list[Node]) -> int:
    """Probe every interval for 24 h; return the offset just after the last probe."""
    for offset in range(0, DAY + 1, PROBE_INTERVAL):
        case.probe(offset, nodes)
    return DAY + 60


@pytest.mark.parametrize("field", ["size", "packs"])
def test_one_node_unmeasured_for_a_day_alerts_while_the_others_keep_the_rule_evaluating(case: Case, field) -> None:
    """BACKUP-083 (#3304): the shrink and check-budget rules lose a node's series when its value is
    `null`, and `noDataState` only fires when EVERY node is gone. This rule keeps the series."""
    nodes = [Node("beelink", "on-demand", **{field: None}), Node("vps", "always-on")]
    end = _probe_a_day(case, nodes)
    assert case.value(UNMEASURED, end) == {"beelink": 0.0, "vps": 1.0}
    assert _unmeasured(case, end) == {"beelink"}
    # The gap this closes, on the real probe's lines: the old rule for the same field has no
    # series for that node, so nothing about it can alert.
    old = case.value(SHRINK if field == "size" else BUDGET, end)
    assert "beelink" not in old and "vps" in old, old


def test_a_node_measured_once_in_the_day_does_not_alert_until_that_probe_leaves_the_window(case: Case) -> None:
    """One good probe in 24 h is a measured node: a single failed listing is not a page."""
    case.probe(0, [Node("beelink", "on-demand"), Node("vps", "always-on")])
    failing = [Node("beelink", "on-demand", size=None, packs=None), Node("vps", "always-on")]
    for offset in range(PROBE_INTERVAL, DAY + 1, PROBE_INTERVAL):
        case.probe(offset, failing)
    assert _unmeasured(case, DAY - 60) == set()
    assert _unmeasured(case, DAY + 60) == {"beelink"}


def test_a_fully_measured_fleet_does_not_alert(case: Case) -> None:
    end = _probe_a_day(case, [Node("beelink", "on-demand"), Node("vps", "always-on")])
    assert case.value(UNMEASURED, end) == {"beelink": 1.0, "vps": 1.0}


# --------------------------------------------------------------------- static


def _rule(uid: str) -> dict:
    for path in sorted(ALERTING_DIR.glob("*.yaml")):
        for group in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("groups") or []:
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
    assert threshold["evaluator"] == {"type": "gt", "params": [STALE_AFTER]}


def test_the_alert_windows_follow_the_cadences_they_depend_on() -> None:
    """The windows are literals in the rules, and the cadences live elsewhere: the
    watcher's CronJob and the role's ship interval. A change to either must turn
    this red, never leave a rule that pages healthy nodes or sees a single probe."""
    probe, ship = _probe_interval(), _ship_interval()
    assert STALE_AFTER >= 3 * ship, f"a healthy node ships every {ship} s; a {STALE_AFTER} s threshold pages it"
    assert _hours(_rule(FRESHNESS)["for"]) * 3600 > probe, "for: must outlast one probe interval"
    (shrink_window,) = set(re.findall(r"\[(\d+[hms])\]", rule_expr(SHRINK)))
    assert _seconds(shrink_window) > probe, "the shrink window must hold two probes"


@pytest.mark.parametrize("duration", ["1d", "1w", "", "{{ node_backup_interval }}", "0h", "1h30x"])
def test_a_duration_the_guard_cannot_read_fails_instead_of_reading_as_zero(duration: str) -> None:
    """A unit `_seconds` does not know must never read as 0: `STALE_AFTER >= 3 * 0`
    holds for any threshold, so the cadence guard would pass without measuring (#2045)."""
    with pytest.raises(ValueError):
        _seconds(duration)


def test_a_ship_interval_in_days_fails_the_cadence_guard(tmp_path: pathlib.Path) -> None:
    """The same failure through the path the guard reads, so a refactor of
    `_ship_interval` that swallows the error turns this red (#2045)."""
    defaults = tmp_path / "main.yml"
    defaults.write_text('node_backup_interval: "1d"\n', encoding="utf-8", newline="\n")
    with pytest.raises(ValueError):
        _ship_interval(defaults)


def test_the_shrink_rule_threshold_is_half() -> None:
    rule = _rule(SHRINK)
    (threshold,) = next(d for d in rule["data"] if d["refId"] == "C")["model"]["conditions"]
    assert threshold["evaluator"] == {"type": "lt", "params": [0.5]}
    assert rule["noDataState"] == "Alerting"


def test_the_unmeasured_sizes_rule_is_declared_to_alert_and_its_runbook_anchor_exists() -> None:
    rule = _rule(UNMEASURED)
    assert rule["noDataState"] == "Alerting" and rule["execErrState"] == "Alerting"
    assert _hours(rule["for"]) > 0
    (threshold,) = next(d for d in rule["data"] if d["refId"] == "C")["model"]["conditions"]
    assert threshold["evaluator"] == {"type": "lt", "params": [1]}
    expr = rule_expr(UNMEASURED)
    assert "by (backup_node)" in expr and "unwrap sizes_measured" in expr and "[24h]" in expr
    anchor = rule["annotations"]["runbook_url"].rsplit("#", 1)[1]
    runbook = (REPO / "docs/runbooks/offsite-backup-restore.md").read_text(encoding="utf-8")
    headings = {
        re.sub(r"[^a-z0-9 -]", "", h.lower()).replace(" ", "-") for h in re.findall(r"^#+ (.+)$", runbook, re.M)
    }
    assert anchor in headings, f"{anchor} is not a heading of the runbook"
