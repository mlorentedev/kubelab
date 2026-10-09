"""Every break-glass entry an Ansible file names exists in the declaration.

#2142 renamed `break_glass.open_webui` to `open-webui`, and the toolkit's
readers moved with it. `provision-ace2.yml` still read the old key, and nothing
rendered it before a prod provision. That provision failed on the undefined key
after Authelia had already taken the new redirect, so SSO stayed down until a
hotfix landed. A playbook reads the declaration through Jinja, which no test
resolves, so this one reads the names it uses.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
ANSIBLE = REPO / "infra/ansible"
COMMON = REPO / "infra/config/values/common.yaml"

# `authelia.break_glass.name`, or by subscript; a registered result named `*_break_glass` is not one.
REF = re.compile(r"""authelia\.break_glass(?:\.([A-Za-z_][\w]*)|\[\s*['"]([^'"]+)['"]\s*\])""")


def _declared() -> set[str]:
    common = yaml.safe_load(COMMON.read_text())
    return set(common["apps"]["services"]["security"]["authelia"]["break_glass"])


def _references() -> list[tuple[Path, str]]:
    found = []
    for path in sorted(ANSIBLE.rglob("*")):
        if path.suffix not in {".yml", ".yaml", ".j2"} or not path.is_file():
            continue
        for match in REF.finditer(path.read_text()):
            found.append((path.relative_to(REPO), match.group(1) or match.group(2)))
    return found


def test_the_scan_finds_the_reference_it_exists_for() -> None:
    assert any(name == "open-webui" for _, name in _references())


def test_every_break_glass_name_ansible_reads_is_declared() -> None:
    declared = _declared()
    missing = [f"{path}: {name}" for path, name in _references() if name not in declared]
    assert not missing, f"undeclared break-glass entries: {missing}"


def test_a_hyphenated_name_is_never_read_by_attribute() -> None:
    """`break_glass.open-webui` parses as a subtraction, so a hyphenated entry
    must be read by subscript."""
    for path in ANSIBLE.rglob("*.yml"):
        assert not re.search(r"authelia\.break_glass\.[\w]+-", path.read_text()), path
