"""The rules that page on the lab edge from prod (NET-005 AC12, ADR-075 D6).

Two rules over the edge watcher's lines, `grafana-alerting/edge-rules.yaml`:

- per target: a node whose probe has read `up=0` for long enough, judged on its
  own, so an rpi3 that stopped is not hidden by an RPi4 that still answers;
- the watcher: no `edge_probe` line at all.

The expressions are evaluated in a real Loki against lines the real `probe.sh`
printed, the way `tests/test_r2_backup_freshness_rule.py` proves the backup
rules. That runs the query, not Grafana's `for:` or `noDataState`, so the
static tests below pin those.
"""

from __future__ import annotations

import itertools
import json
import os
import pathlib
import re
import subprocess
from collections.abc import Iterator

import pytest
import yaml

from tests.loki_harness import ALERTING_DIR, REPO, Loki, rule_expr, run_loki, slot, stream_labels
from tests.test_alerting_unwrap_grouping import CRONJOB_CONTAINERS
from tests.test_edge_watcher_probe import FAKE_NC, PROBE

RULES = ALERTING_DIR / "edge-rules.yaml"
TARGET_DOWN = "net005-edge-target-down"
SILENT = "net005-edge-watcher-silent"
CONTAINER = "edge-watcher"
WATCHER_MANIFEST = REPO / "infra/k8s/base/services/edge-watcher.yaml"
# The K8s node the Job ran on, as Vector labels it: not the node a line reports on.
K8S_NODE = "k8s-node-fixture"
# Documentation addresses (RFC 5737): nothing real is ever contacted.
TARGETS = {"rpi3": "192.0.2.6", "rpi4": "192.0.2.10"}
_case = itertools.count()


def _seconds(duration: str) -> int:
    units = {"h": 3600, "m": 60, "s": 1}
    if not re.fullmatch(r"(\d+[hms])+", duration):
        raise ValueError(f"unreadable duration {duration!r}")
    return sum(int(n) * units[u] for n, u in re.findall(r"(\d+)([hms])", duration))


def _probe_interval() -> int:
    """Seconds between watcher runs, from the CronJob's `schedule:`, never retyped."""
    cron = next(d for d in yaml.safe_load_all(WATCHER_MANIFEST.read_text()) if d and d.get("kind") == "CronJob")
    schedule = cron["spec"]["schedule"]
    minute, *rest = schedule.split()
    every = re.fullmatch(r"\*/(\d+)", minute)
    assert every and rest == ["*", "*", "*", "*"], f"unparsed schedule {schedule!r}"
    return int(every.group(1)) * 60


PROBE_INTERVAL = _probe_interval()


def _rule(uid: str) -> dict:
    for group in yaml.safe_load(RULES.read_text())["groups"]:
        for rule in group["rules"]:
            if rule["uid"] == uid:
                return rule
    raise KeyError(uid)


def _window(uid: str) -> int:
    (window,) = set(re.findall(r"\[(\d+[hms])\]", rule_expr(uid)))
    return _seconds(window)


def _threshold(uid: str) -> dict:
    (condition,) = next(d for d in _rule(uid)["data"] if d["refId"] == "C")["model"]["conditions"]
    return condition["evaluator"]


# --------------------------------------------------------------------- static


def test_the_rules_ship_in_the_grafana_alerting_generator() -> None:
    kustomization = yaml.safe_load((REPO / "infra/k8s/base/kustomization.yaml").read_text())
    generator = next(g for g in kustomization["configMapGenerator"] if g["name"] == "grafana-alerting")
    assert "services/grafana-alerting/edge-rules.yaml" in generator["files"]


def test_the_watcher_is_guarded_as_a_cronjob_stream() -> None:
    """`CRONJOB_CONTAINERS` feeds the grouping guard and the no-data guard; a
    container missing from it is a rule neither of them reads."""
    assert CONTAINER in CRONJOB_CONTAINERS


@pytest.mark.parametrize("uid", [TARGET_DOWN, SILENT])
def test_both_rules_page_on_no_data_and_on_a_query_error(uid: str) -> None:
    rule = _rule(uid)
    assert rule["noDataState"] == "Alerting"
    assert rule["execErrState"] == "Alerting"
    assert f'{{container="{CONTAINER}"}}' in rule_expr(uid)
    assert "metric=`edge_probe`" in rule_expr(uid)


def test_the_target_rule_judges_each_node_on_its_own() -> None:
    """By the probe's `node`, extracted under another name: Vector's own `node`
    label is the K8s node, and a plain `| json` would group on that (lesson-512)."""
    expr = rule_expr(TARGET_DOWN)
    assert 'edge_node="node"' in expr
    assert re.search(r"\)\s*by \(edge_node\)", expr), expr
    assert "unwrap up" in expr
    assert _threshold(TARGET_DOWN) == {"type": "lt", "params": [1]}


def test_the_silent_rule_counts_every_line_across_runs() -> None:
    expr = rule_expr(SILENT)
    assert "count_over_time(" in expr and "unwrap" not in expr
    assert re.search(r"\)\s*by \(namespace\)", expr), expr
    assert _threshold(SILENT) == {"type": "lt", "params": [1]}


def test_the_windows_follow_the_watcher_s_schedule() -> None:
    """The windows are literals and the schedule lives in the CronJob: a change to
    either must turn this red, never leave a rule that one probe decides."""
    assert _window(TARGET_DOWN) >= 2 * PROBE_INTERVAL, "one up line in two probes must clear the target"
    assert _seconds(_rule(TARGET_DOWN)["for"]) >= PROBE_INTERVAL, "for: must outlast one probe"
    assert _window(SILENT) >= 3 * PROBE_INTERVAL, "one lost Job must never read as a silent watcher"


# -------------------------------------------------------------------- harness


def _probe(tmp_path: pathlib.Path, down: set[str]) -> list[dict]:
    """Run the real probe once; `down` names the targets whose connect is refused."""
    run = tmp_path / f"run-{len(list(tmp_path.iterdir()))}"
    fake, bin_dir = run / "fake", run / "bin"
    fake.mkdir(parents=True)
    bin_dir.mkdir()
    (bin_dir / "nc").write_text(FAKE_NC)
    (bin_dir / "nc").chmod(0o755)
    for node in down:
        (fake / f"{TARGETS[node]}.down").touch()
    targets = run / "targets.txt"
    targets.write_text("".join(f"{node} {address} 22\n" for node, address in TARGETS.items()))
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_DIR": str(fake),
        "EDGE_TARGETS": str(targets),
        "REACH_TIMEOUT": "1",
        "NC": str(bin_dir / "nc"),
    }
    proc = subprocess.run(["sh", str(PROBE)], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


@pytest.fixture(scope="module")
def loki() -> Iterator[Loki]:
    yield from run_loki()


class Case:
    """One scenario in its own time slot and its own streams, so cases never meet."""

    def __init__(self, loki: Loki, tmp_path: pathlib.Path) -> None:
        self.loki, self.tmp_path = loki, tmp_path
        self.start = slot(next(_case))

    def run(self, index: int, down: set[str] = frozenset()) -> None:
        """Probe run `index` (0, 1, ...) at its scheduled time; each run is a new Job pod."""
        at = self.start + index * PROBE_INTERVAL
        labels = stream_labels(namespace="kubelab", container=CONTAINER, pod=f"{CONTAINER}-{at}", node=K8S_NODE)
        self.loki.push({**labels, "case": str(self.start)}, [(at, r) for r in _probe(self.tmp_path, set(down))])

    def value(self, uid: str, after_run: int, plus: int = 60) -> dict[str, float]:
        result = self.loki.query(rule_expr(uid), self.start + after_run * PROBE_INTERVAL + plus)
        return {dict(labels).get("edge_node", dict(labels).get("namespace", "")): v for labels, v in result.items()}

    def firing(self, after_run: int) -> set[str]:
        return {node for node, v in self.value(TARGET_DOWN, after_run).items() if v < 1}


@pytest.fixture
def case(loki: Loki, tmp_path: pathlib.Path) -> Case:
    return Case(loki, tmp_path)


def test_every_target_that_answers_is_normal(case: Case) -> None:
    case.run(0)
    assert case.value(TARGET_DOWN, 0) == {"rpi3": 1.0, "rpi4": 1.0}
    assert case.value(SILENT, 0)["kubelab"] >= 1


def test_a_dead_uplink_takes_both_targets_down(case: Case) -> None:
    case.run(0)
    for index in (1, 2):
        case.run(index, {"rpi3", "rpi4"})
    assert case.firing(2) == {"rpi3", "rpi4"}


def test_a_stopped_rpi3_fires_while_the_edge_still_answers(case: Case) -> None:
    """The case AC12 names: one target failing while another answers is not resolved."""
    case.run(0)
    for index in (1, 2):
        case.run(index, {"rpi3"})
    assert case.value(TARGET_DOWN, 2) == {"rpi3": 0.0, "rpi4": 1.0}


@pytest.mark.parametrize(
    "runs",
    [
        pytest.param([set(), {"rpi4"}], id="one-down-probe"),
        pytest.param([{"rpi4"}, set(), {"rpi4"}], id="flap"),
        pytest.param([{"rpi4"}, {"rpi4"}, set()], id="recovered"),
    ],
)
def test_one_up_line_in_the_window_keeps_a_target_normal(case: Case, runs: list[set[str]]) -> None:
    for index, down in enumerate(runs):
        case.run(index, down)
    assert case.firing(len(runs) - 1) == set()


def test_a_watcher_that_stopped_is_no_data_for_both_rules(case: Case) -> None:
    """No data is what `noDataState: Alerting` turns into a page, for each rule."""
    case.run(0)
    after_the_window = max(_window(TARGET_DOWN), _window(SILENT)) // PROBE_INTERVAL + 1
    assert case.value(TARGET_DOWN, after_the_window) == {}
    assert case.value(SILENT, after_the_window) == {}
