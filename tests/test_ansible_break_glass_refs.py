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

# `authelia.break_glass.name`, or by subscript, then the field read from it. A
# registered result named `*_break_glass` is not one, and a call (`.get(`) is
# not a name.
REF = re.compile(
    r"""authelia\.break_glass(?:\.([A-Za-z_]\w*)(?![\w(])|\[\s*['"]([^'"]+)['"]\s*\])"""
    r"""(?:\.([A-Za-z_]\w*)(?![\w(]))?"""
)


def _declared() -> dict:
    common = yaml.safe_load(COMMON.read_text())
    return common["apps"]["services"]["security"]["authelia"]["break_glass"]


def _files() -> list[Path]:
    return [p for p in sorted(ANSIBLE.rglob("*")) if p.suffix in {".yml", ".yaml", ".j2"} and p.is_file()]


def _references() -> list[tuple[Path, str, str | None]]:
    found = []
    for path in _files():
        for match in REF.finditer(path.read_text()):
            found.append((path.relative_to(REPO), match.group(1) or match.group(2), match.group(3)))
    return found


def test_the_scan_finds_the_reference_it_exists_for() -> None:
    assert ("open-webui", "email") in {(name, field) for _, name, field in _references()}


def test_the_pattern_reads_both_forms_and_skips_what_is_not_a_name() -> None:
    def read(text: str) -> list[tuple[str, str | None]]:
        return [(m.group(1) or m.group(2), m.group(3)) for m in REF.finditer(text)]

    assert read("authelia.break_glass.gitea.login") == [("gitea", "login")]
    assert read("authelia.break_glass['open-webui'].email") == [("open-webui", "email")]
    assert read("authelia.break_glass.get('open-webui', {})") == []
    assert read("authelia.break_glass['open-webui'].get('email')") == [("open-webui", None)]
    assert read("_agent_stack_webui_break_glass.status") == []


def test_every_break_glass_entry_and_field_ansible_reads_is_declared() -> None:
    declared = _declared()
    missing = [
        f"{path}: {name}{'.' + field if field else ''}"
        for path, name, field in _references()
        if name not in declared or (field is not None and field not in declared[name])
    ]
    assert not missing, f"undeclared break-glass entries or fields: {missing}"


def test_a_hyphenated_name_is_never_read_by_attribute() -> None:
    """`break_glass.open-webui` parses as a subtraction, so a hyphenated entry
    must be read by subscript."""
    for path in _files():
        assert not re.search(r"authelia\.break_glass\.[\w]+-", path.read_text()), path
