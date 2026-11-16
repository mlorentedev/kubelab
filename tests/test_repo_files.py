"""Tests that read `infra/ansible` read what git would commit, never what a run left there.

A walk of `infra/ansible` also read the gitignored `generated/`, where an old
generator had left playbooks that no longer parse, so six tests in three files
failed on one machine and passed in CI. `tests/repo_files.py` lists by git instead.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from tests.repo_files import REPO, repo_files

ANSIBLE = REPO / "infra/ansible"
# A recursive walk rooted at the Ansible tree, under the names the tests give it:
# `ANSIBLE.rglob(`, `ANSIBLE_DIR.rglob(`, `(REPO / "infra/ansible").rglob(`,
# `ansible.glob("**/...`, `ANSIBLE.glob(f"**/{x}")`. A glob under a subdirectory,
# `glob("roles/*/tasks/**/...")`, never reaches `generated/` and is left alone. Not
# seen: a root under another name, or a pattern held in a variable.
WALK = re.compile(r"""ansible\w*["']?\)?\.(?:rglob\(|glob\(f?["']\*\*)""", re.IGNORECASE)


def _planted(tmp_path: Path, rel: str, text: str) -> tuple[bool, bool]:
    """Plant `rel` in a throwaway repository; say whether `repo_files` lists it with and without a matching pattern.

    Never in this checkout: under `pytest -n` another worker lists `infra/ansible` while a probe
    is there, and reads it after it is gone (#3445). The throwaway repository carries the real
    `infra/ansible/.gitignore`, so what is ignored there is what is ignored here.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    ansible = tmp_path / "infra/ansible"
    ansible.mkdir(parents=True)
    shutil.copyfile(ANSIBLE / ".gitignore", ansible / ".gitignore")
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return (
        path in repo_files(ansible, "*.yml", repo=tmp_path),
        path in repo_files(ansible, "*.j2", repo=tmp_path),
    )


def test_a_file_git_ignores_is_not_listed(tmp_path: Path) -> None:
    listed, _ = _planted(tmp_path, "infra/ansible/generated/_repo_files_probe/play.yml", "- {{ not yaml\n")
    assert not listed, "repo_files listed gitignored output"


def test_a_file_written_for_a_change_is_listed_before_it_is_added(tmp_path: Path) -> None:
    listed, by_other_pattern = _planted(tmp_path, "infra/ansible/_repo_files_probe.yml", "---\n")
    assert listed, "repo_files missed an untracked file git would add"
    assert not by_other_pattern, "repo_files ignored the name pattern"


def test_no_test_walks_the_ansible_tree() -> None:
    walks = [
        f"{path.relative_to(REPO)}:{text.count(chr(10), 0, match.start()) + 1}"
        for path in repo_files(REPO / "tests", "*.py")
        if path != Path(__file__).resolve()  # this file spells the shapes out
        for text in [path.read_text(encoding="utf-8")]
        for match in WALK.finditer(text)
    ]
    assert not walks, f"list infra/ansible with tests.repo_files.repo_files, not a walk: {walks}"


def test_the_walk_pattern_sees_each_shape_the_tests_used() -> None:
    for shape in (
        'ANSIBLE.rglob("*.yml")',
        'ANSIBLE_DIR.rglob("*.j2")',
        'ansible.rglob("*.service")',
        '(REPO / "infra/ansible").rglob("*")',
        'ANSIBLE.glob("**/*.yml")',
        'ANSIBLE.glob(f"**/{suffix}")',
    ):
        assert WALK.search(shape), shape
    for shape in ('ROLES.rglob("*.j2")', 'ANSIBLE.glob(f"roles/*/tasks/**/{suffix}")'):
        assert not WALK.search(shape), shape
