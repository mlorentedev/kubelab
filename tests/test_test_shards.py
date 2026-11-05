"""CI splits the suite across runners by whole test file (#3111).

Each runner collects the whole suite and keeps the files the plan gives it, so
the plan is only correct if every shard computes the same one and, between them,
they run every file exactly once. A file is never cut in two: a module-scoped
fixture shared by its tests would then be built twice, the failure `--dist
loadfile` was chosen to prevent (lesson-710).
"""

from __future__ import annotations

import json
import random
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from tests import sharding

ROOT = Path(__file__).resolve().parents[1]
UNKNOWN = "tests/test_zz_a_file_the_record_does_not_know.py"


def _suite_files() -> list[str]:
    tests = ROOT / "tests"
    found = {*tests.rglob("test_*.py"), *tests.rglob("*_test.py")}
    return sorted(p.relative_to(ROOT).as_posix() for p in found)


def _record() -> dict[str, float]:
    return sharding.load_durations(ROOT / sharding.DEFAULT_DURATIONS)


def _ci() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))


def test_the_shard_option_reads_index_over_count() -> None:
    assert sharding.parse_shard("2/3") == (2, 3)
    for bad in ("0/3", "4/3", "3", "a/b", "1/0"):
        with pytest.raises(ValueError):
            sharding.parse_shard(bad)


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_every_file_runs_on_exactly_one_shard(count: int) -> None:
    files = [*_suite_files(), UNKNOWN]
    plan = sharding.assign(files, _record(), count)
    assert sorted(plan) == sorted(files)
    assert set(plan.values()) <= set(range(1, count + 1))
    shards = [{f for f, s in plan.items() if s == i} for i in range(1, count + 1)]
    assert set().union(*shards) == set(files)
    assert sum(len(s) for s in shards) == len(files)


def test_the_plan_does_not_depend_on_collection_order() -> None:
    files = _suite_files()
    shuffled = files[:]
    random.Random(3111).shuffle(shuffled)
    assert sharding.assign(files, _record(), 3) == sharding.assign(shuffled, _record(), 3)


def test_shards_differ_by_no_more_than_the_heaviest_file() -> None:
    record = _record()
    files = _suite_files()
    plan = sharding.assign(files, record, 3)
    weight = sharding.weights(files, record)
    loads = [sum(weight[f] for f, s in plan.items() if s == i) for i in (1, 2, 3)]
    assert max(loads) - min(loads) <= max(weight.values()), loads


def test_the_record_holds_only_paths_and_positive_seconds() -> None:
    record = _record()
    assert len(record) > 100, "the record looks truncated"
    for path, seconds in record.items():
        assert re.fullmatch(r"tests/[\w/]+\.py", path), path
        assert isinstance(seconds, (int, float)) and seconds > 0, (path, seconds)


def test_the_plugin_deselects_other_shards_and_runs_unknown_files(tmp_path: Path) -> None:
    """The wiring, end to end: two shards over a suite whose record misses a file."""
    suite = tmp_path / "tests"
    suite.mkdir()
    names = ["test_a.py", "test_b.py", "test_c.py", "test_d.py", "test_new.py"]
    for name in names:
        (suite / name).write_text("def test_one():\n    pass\n\ndef test_two():\n    pass\n", encoding="utf-8")
    record = tmp_path / "durations.json"
    seconds = {f"tests/{n}": s for n, s in zip(names[:4], (9, 5, 4, 1), strict=True)}
    record.write_text(json.dumps(seconds), encoding="utf-8")
    ran: list[str] = []
    for index in (1, 2):
        run = subprocess.run(
            [sys.executable, "-m", "pytest", "-c", "/dev/null", "--rootdir", str(tmp_path), "-p", "tests.sharding"]
            + ["-q", "-p", "no:cacheprovider", "--collect-only", f"--shard={index}/2"]
            + [f"--shard-durations={record}", "tests"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin"},
            timeout=120,
        )
        assert run.returncode == 0, run.stdout[-800:] + run.stderr[-800:]
        collected = [line for line in run.stdout.splitlines() if "::" in line]
        # xdist dispatches files in collection order, so the heaviest go first: one
        # started last would run on alone after every other worker finished.
        order = list(dict.fromkeys(line.split("::")[0] for line in collected))
        weight = sharding.weights(order, json.loads(record.read_text(encoding="utf-8")))
        assert order == sorted(order, key=lambda f: (-weight[f], f)), order
        assert all(line.endswith(("test_one", "test_two")) for line in collected)
        ran += collected
    assert sorted(ran) == sorted(f"tests/{n}::{t}" for n in names for t in ("test_one", "test_two"))


def test_stored_durations_are_summed_per_file(tmp_path: Path) -> None:
    (tmp_path / "test_x.py").write_text(
        textwrap.dedent("""
            import time

            def test_one():
                time.sleep(0.05)

            def test_two():
                time.sleep(0.05)
        """),
        encoding="utf-8",
    )
    out = tmp_path / "stored.json"
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-c", "/dev/null", "--rootdir", str(tmp_path), "-p", "tests.sharding"]
        + ["-q", "-p", "no:cacheprovider", f"--store-shard-durations={out}", "test_x.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin"},
        timeout=120,
    )
    assert run.returncode == 0, run.stdout[-800:]
    stored = json.loads(out.read_text(encoding="utf-8"))
    assert list(stored) == ["test_x.py"] and stored["test_x.py"] >= 0.1


def test_ci_runs_every_shard_the_plan_names() -> None:
    jobs = _ci()["jobs"]
    shards = jobs["test-shards"]
    matrix = shards["strategy"]["matrix"]["shard"]
    assert matrix == list(range(1, len(matrix) + 1)) and len(matrix) > 1
    assert shards["strategy"]["fail-fast"] is False
    runs = [s.get("run", "") for s in shards["steps"]]
    assert any(f"make test SHARD=${{{{ matrix.shard }}}}/{len(matrix)}" in r for r in runs), runs


def test_the_required_check_fails_when_any_shard_did_not_pass() -> None:
    """A required check that is skipped reads as passed, so `Tests` must run and fail."""
    tests = _ci()["jobs"]["tests"]
    assert tests["name"] == "Tests"
    assert "test-shards" in ([tests["needs"]] if isinstance(tests["needs"], str) else tests["needs"])
    assert tests["if"].strip() == "always()"
    first = tests["steps"][0]
    assert "needs.test-shards.result" in first["run"] and '!= "success"' in first["run"] and "exit 1" in first["run"]


def test_every_shard_uploads_its_coverage_including_the_hidden_data_file() -> None:
    upload = [s for s in _ci()["jobs"]["test-shards"]["steps"] if "upload-artifact" in s.get("uses", "")]
    assert upload and upload[0]["with"]["include-hidden-files"] is True
    assert ".coverage" in upload[0]["with"]["path"]


def test_under_xdist_the_heaviest_file_is_dispatched_first(tmp_path: Path) -> None:
    """xdist's own reorder (by test count) must not undo the plan's order: measured, not collected."""
    log = tmp_path / "ran.log"
    body = f"def test_{{i}}():\n    open({str(log)!r}, 'a').write(__name__ + '\\n')\n"
    (tmp_path / "test_heavy.py").write_text(body.format(i=0), encoding="utf-8")
    (tmp_path / "test_light.py").write_text("".join(body.format(i=i) for i in range(6)), encoding="utf-8")
    record = tmp_path / "durations.json"
    record.write_text(json.dumps({"test_heavy.py": 100, "test_light.py": 1}), encoding="utf-8")
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-c", "/dev/null", "--rootdir", str(tmp_path), "-p", "tests.sharding"]
        + ["-q", "-p", "no:cacheprovider", "-n", "1", "--dist", "loadfile", "--shard=1/1"]
        + [f"--shard-durations={record}", "test_heavy.py", "test_light.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin"},
        timeout=120,
    )
    assert run.returncode == 0, run.stdout[-800:]
    assert log.read_text(encoding="utf-8").splitlines()[0] == "test_heavy"


@pytest.mark.parametrize(("result", "code"), [("success", 0), ("failure", 1), ("cancelled", 1), ("skipped", 1)])
def test_the_gate_step_exits_non_zero_on_every_result_but_success(result: str, code: int) -> None:
    """Runs the step's own script, not a reading of it: the text could be right and the shell wrong."""
    script = _ci()["jobs"]["tests"]["steps"][0]["run"].replace("${{ needs.test-shards.result }}", result)
    assert "${{" not in script, script
    assert subprocess.run(["bash", "-e", "-c", script], capture_output=True, timeout=30).returncode == code


def test_the_record_still_knows_most_of_the_suite() -> None:
    """A file the record lacks weighs the mean: correct, but balance degrades as they pile up.

    When this fails, refresh the record from a recent CI run: `make test-durations RUN=<id>`.
    """
    files = _suite_files()
    unknown = [f for f in files if f not in _record()]
    assert len(unknown) <= len(files) // 10, f"{len(unknown)} files missing from the record: refresh it"
