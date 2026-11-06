"""Split the suite across CI runners by whole test file (#3111).

`--shard=I/N` keeps the files the plan gives shard I and deselects the rest. The
plan is a longest-first greedy over per-file seconds measured on CI
(`tests/shard_durations.json`); a file the record does not know weighs the
record's mean. Every shard collects the whole suite before filtering, so all of
them plan from the same input and, between them, run every file exactly once.

Whole files, never single tests: a module-scoped fixture would otherwise be built
on two runners (lesson-710). Refresh the record with `make test-durations`.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

import pytest

DEFAULT_DURATIONS = "tests/shard_durations.json"


def parse_shard(value: str) -> tuple[int, int]:
    index, sep, count = value.partition("/")
    if not sep or not index.isdigit() or not count.isdigit() or not 1 <= int(index) <= int(count):
        raise ValueError(f"--shard takes INDEX/COUNT with 1 <= INDEX <= COUNT, got {value!r}")
    return int(index), int(count)


def load_durations(path: Path) -> dict[str, float]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def weights(files: Iterable[str], durations: dict[str, float]) -> dict[str, float]:
    default = sum(durations.values()) / len(durations) if durations else 1.0
    return {f: durations.get(f, default) for f in files}


def assign(files: Iterable[str], durations: dict[str, float], count: int) -> dict[str, int]:
    """File to shard (1-based). Depends on the set of files, not on their order."""
    weight = weights(set(files), durations)
    loads = [0.0] * count
    plan: dict[str, int] = {}
    for f in sorted(weight, key=lambda f: (-weight[f], f)):
        lightest = loads.index(min(loads))
        loads[lightest] += weight[f]
        plan[f] = lightest + 1
    return plan


def _file(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("shard", "split the suite across runners by file (#3111)")
    group.addoption("--shard", default=None, help="run shard INDEX/COUNT of the suite, e.g. 2/3")
    group.addoption("--shard-durations", default=DEFAULT_DURATIONS, help="per-file seconds the plan balances on")
    group.addoption("--store-shard-durations", default=None, help="write per-file seconds of this run to PATH")


def pytest_configure(config: pytest.Config) -> None:
    # xdist's `loadfile` reorders files by test count unless told not to, which
    # would undo the heaviest-first order below (measured on CI: the 259s file
    # still started last). Only when sharding: a plain `make test` is unchanged.
    if config.getoption("--shard") and hasattr(config.option, "loadscopereorder"):
        config.option.loadscopereorder = False


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    value = config.getoption("--shard")
    if not value:
        return
    index, count = parse_shard(value)
    record = load_durations(Path(config.rootpath, config.getoption("--shard-durations")))
    files = {_file(i.nodeid) for i in items}
    plan = assign(files, record, count)
    weight = weights(files, record)
    keep = [i for i in items if plan[_file(i.nodeid)] == index]
    dropped = [i for i in items if plan[_file(i.nodeid)] != index]
    if dropped:
        config.hook.pytest_deselected(items=dropped)
    # Heaviest file first: xdist hands files out in collection order, so a heavy
    # file collected late runs on alone after the other workers have finished
    # (measured on CI: 501s of wall for 945s of work on 4 workers). The sort is
    # stable, so a file's own tests keep their order.
    keep.sort(key=lambda i: (-weight[_file(i.nodeid)], _file(i.nodeid)))
    items[:] = keep


_seconds: defaultdict[str, float] = defaultdict(float)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    _seconds[_file(report.nodeid)] += report.duration


def pytest_sessionfinish(session: pytest.Session) -> None:
    out = session.config.getoption("--store-shard-durations")
    if not out or hasattr(session.config, "workerinput"):
        return
    stored = {f: max(round(s, 2), 0.01) for f, s in sorted(_seconds.items())}
    Path(out).write_text(json.dumps(stored, indent=1) + "\n", encoding="utf-8")


def merge_records(paths: Iterable[Path]) -> dict[str, float]:
    """One record from each shard's stored durations; shards hold disjoint files."""
    merged: dict[str, float] = {}
    for path in paths:
        merged.update(load_durations(path))
    return dict(sorted(merged.items()))


if __name__ == "__main__":
    import sys

    out, *inputs = sys.argv[1:]
    Path(out).write_text(json.dumps(merge_records(map(Path, inputs)), indent=1) + "\n", encoding="utf-8")
