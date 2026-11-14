"""The Windows known-failure list marks what it names and refuses what names nothing (#3409)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, cast

import pytest

from tests import windows_known_failures as known

REPO = Path(__file__).resolve().parents[1]

LIST = """
# comment
[shell] runs a shell script
tests/test_a.py::test_one
tests/test_b.py

[sep] path separator
tests/test_a.py::test_two[x-y]
"""


class _Item:
    def __init__(self, nodeid: str) -> None:
        self.nodeid = nodeid
        self.markers: list[Any] = []

    def add_marker(self, marker: Any) -> None:
        self.markers.append(marker)


def _items(*nodeids: str) -> list[pytest.Item]:
    return cast(list[pytest.Item], [_Item(n) for n in nodeids])


def _tree(tmp_path: Path) -> Path:
    for name in ("test_a.py", "test_b.py", "test_c.py"):
        (tmp_path / "tests").mkdir(exist_ok=True)
        (tmp_path / "tests" / name).write_text("", encoding="utf-8", newline="\n")
    return tmp_path


def test_each_entry_takes_its_sections_reason() -> None:
    assert known.parse(LIST) == {
        "tests/test_a.py::test_one": "shell: runs a shell script",
        "tests/test_b.py": "shell: runs a shell script",
        "tests/test_a.py::test_two[x-y]": "sep: path separator",
    }


@pytest.mark.parametrize(
    "text",
    ["tests/test_a.py::test_one\n[shell] x\n", "[shell] x\ntests/test_a.py\ntests/test_a.py\n"],
    ids=["outside-a-section", "listed-twice"],
)
def test_a_malformed_list_is_refused(text: str) -> None:
    with pytest.raises(ValueError):
        known.parse(text)


def test_listed_tests_and_whole_files_are_marked_xfail_and_nothing_else(tmp_path: Path) -> None:
    items = _items(
        "tests/test_a.py::test_one",
        "tests/test_a.py::test_two[x-y]",
        "tests/test_a.py::test_three",
        "tests/test_b.py::test_any",
        "tests/test_b.py::TestK::test_other",
    )
    known.apply(items, known.parse(LIST))
    assert known.stale(known.parse(LIST), [i.nodeid for i in items], _tree(tmp_path)) == []
    marked = {cast(_Item, i).nodeid: cast(_Item, i).markers for i in items}
    assert not marked["tests/test_a.py::test_three"]
    for nodeid in set(marked) - {"tests/test_a.py::test_three"}:
        (marker,) = marked[nodeid]
        assert marker.name == "xfail"
        assert marker.kwargs["strict"] is False
        assert marker.kwargs["reason"].startswith("Windows (")


def test_an_entry_that_names_nothing_in_a_collected_file_is_stale(tmp_path: Path) -> None:
    nodeids = ["tests/test_a.py::test_one_renamed", "tests/test_b.py::test_any"]
    stale = known.stale(known.parse(LIST), nodeids, _tree(tmp_path))
    assert stale == ["tests/test_a.py::test_one", "tests/test_a.py::test_two[x-y]"]


def test_an_entry_for_a_missing_file_is_stale_even_when_not_collected(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    (root / "tests" / "test_b.py").unlink()
    assert known.stale(known.parse(LIST), ["tests/test_c.py::test_x"], root) == ["tests/test_b.py"]


def test_a_subset_run_leaves_other_files_entries_alone(tmp_path: Path) -> None:
    assert known.stale(known.parse(LIST), ["tests/test_c.py::test_x"], _tree(tmp_path)) == []


def test_the_committed_list_parses_and_every_file_it_names_exists() -> None:
    entries = known.parse(known.LIST.read_text(encoding="utf-8"))
    assert entries, "an empty list would make the Windows job pass on nothing"
    missing = sorted({e.split("::", 1)[0] for e in entries if not (REPO / e.split("::", 1)[0]).exists()})
    assert not missing, f"{known.LIST.name} names files that do not exist: {missing}"


@pytest.mark.skipif(sys.platform != "win32", reason="the list describes the Windows collection")
def test_every_entry_names_a_collected_test(request: pytest.FixtureRequest) -> None:
    """A renamed or removed test must leave the list too, or the list stops describing anything.

    Under `--dist loadfile` each worker collects the whole suite, so the session's
    items are the full collection; a subset run judges only the files it collected,
    and a test `-k`/`-m` deselected still counts as collected.
    """
    deselected: list[str] = request.config.stash.get(known.DESELECTED, [])
    nodeids = [item.nodeid for item in request.session.items] + deselected
    stale = known.stale(known.parse(known.LIST.read_text(encoding="utf-8")), nodeids, REPO)
    assert not stale, f"{known.LIST.name} lists tests that do not exist (renamed or removed?):\n" + "\n".join(stale)
