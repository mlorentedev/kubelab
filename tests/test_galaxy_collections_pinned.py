"""Galaxy collections are pinned exactly, and a run refuses a controller that holds other versions (ANSIBLE-070, #2735).

`requirements.yml` declared floors (`>=`). `ansible-galaxy collection install -r`
does nothing while an installed version satisfies a floor, so each controller
kept whatever it installed first: the operator's ran `ansible.posix` 2.1.0, a
release behind the fix for a local privilege escalation in `authorized_key`
(2.2.1), which `ssh_hardening` runs as root. `make setup-ansible` hid the install
output and printed success either way, and CI's collection cache is keyed on
this file's hash, so it froze too.

An exact pin moves an installed older version to the pinned one with no flag
(measured), Renovate's `ansible-galaxy` manager bumps it, and the run compares
what the controller holds with what the repository declares before it renders
anything with it.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from toolkit.features import provision_freshness

REPO = Path(__file__).resolve().parents[1]
REQUIREMENTS = REPO / "infra/ansible/requirements.yml"


def _declared() -> list[dict[str, Any]]:
    return yaml.safe_load(REQUIREMENTS.read_text(encoding="utf-8"))["collections"]


def test_every_collection_is_pinned_to_one_exact_version() -> None:
    loose = [c["name"] for c in _declared() if not re.fullmatch(r"\d+\.\d+\.\d+", str(c.get("version", "")))]
    assert loose == [], f"pin these to an exact X.Y.Z (a floor never upgrades a controller): {loose}"


def test_renovate_keeps_the_pins_moving() -> None:
    """`enabledManagers` is an allowlist: a manager missing from it tracks nothing, silently."""
    config = json.loads((REPO / "renovate.json").read_text(encoding="utf-8"))
    assert "ansible-galaxy" in config["enabledManagers"]
    # Renovate's default managerFilePatterns for ansible-galaxy; the file must keep a name it matches.
    assert re.search(r"(^|/)(galaxy|requirements)(\.ansible)?\.ya?ml$", REQUIREMENTS.relative_to(REPO).as_posix())


def _galaxy_list(monkeypatch: pytest.MonkeyPatch, paths: dict[str, dict[str, str]], returncode: int = 0) -> None:
    payload = {path: {name: {"version": v} for name, v in found.items()} for path, found in paths.items()}

    def fake(argv: list[str], **_kwargs: Any) -> SimpleNamespace:
        assert argv[:3] == ["ansible-galaxy", "collection", "list"]
        return SimpleNamespace(returncode=returncode, stdout=json.dumps(payload), stderr="boom")

    monkeypatch.setattr(provision_freshness.subprocess, "run", fake)


DECLARED = {"ansible.posix": "2.2.2", "community.docker": "5.0.6"}


def test_a_controller_holding_the_declared_versions_is_current(monkeypatch: pytest.MonkeyPatch) -> None:
    _galaxy_list(monkeypatch, {"/home/u/.ansible/collections/ansible_collections": dict(DECLARED)})
    assert provision_freshness.collections_off_declaration(DECLARED) == []


def test_an_older_installed_version_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    _galaxy_list(monkeypatch, {"/c": {"ansible.posix": "2.1.0", "community.docker": "5.0.6"}})
    assert provision_freshness.collections_off_declaration(DECLARED) == ["ansible.posix 2.1.0 at /c (declared 2.2.2)"]


def test_a_missing_collection_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    _galaxy_list(monkeypatch, {"/c": {"ansible.posix": "2.2.2"}})
    assert provision_freshness.collections_off_declaration(DECLARED) == ["community.docker missing (declared 5.0.6)"]


def test_a_stale_second_copy_is_named_because_the_listing_does_not_say_which_one_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ansible-galaxy collection list` walks its search paths as a set, so its order is not load precedence.

    The stale copy's path is named: `make setup-ansible` installs into the user path
    and does not touch a copy elsewhere, such as one the full `ansible` package bundles.
    """
    _galaxy_list(monkeypatch, {"/a": dict(DECLARED), "/b": {"ansible.posix": "2.1.0"}})
    expected = ["ansible.posix 2.1.0 at /b, 2.2.2 (declared 2.2.2)"]
    assert provision_freshness.collections_off_declaration(DECLARED) == expected


def test_a_listing_that_fails_is_an_error_not_a_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    _galaxy_list(monkeypatch, {}, returncode=1)
    with pytest.raises(provision_freshness.FreshnessError):
        provision_freshness.collections_off_declaration(DECLARED)


def _galaxy_stdout(monkeypatch: pytest.MonkeyPatch, stdout: str) -> None:
    def fake(argv: list[str], **_kwargs: Any) -> SimpleNamespace:
        assert argv[:3] == ["ansible-galaxy", "collection", "list"]
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(provision_freshness.subprocess, "run", fake)


@pytest.mark.parametrize(
    ("stdout", "why"),
    [
        ("not json at all", "the listing is not JSON"),
        ('["a list"]', "the listing is not a mapping"),
        ('{"/c": "not a mapping"}', "a search path maps to something other than a mapping"),
        ('{"/c": {"ansible.posix": "2.2.2"}}', "a collection maps to something other than a mapping"),
    ],
)
def test_a_listing_it_cannot_read_is_a_refusal_not_a_crash(
    monkeypatch: pytest.MonkeyPatch, stdout: str, why: str
) -> None:
    """`ansible-galaxy` output is parsed on the same path that renders a run.

    A `JSONDecodeError` or an `AttributeError` here escaped as a traceback out of
    both `make deploy` and `toolkit infra ansible doctor`, which is a crash where
    the contract is "refuse and say why" -- and it left `FORCE=1` unreachable.
    """
    _galaxy_stdout(monkeypatch, stdout)

    with pytest.raises(provision_freshness.FreshnessError, match="ansible-galaxy"):
        provision_freshness.collections_off_declaration(DECLARED)


def test_a_missing_ansible_galaxy_is_a_refusal_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ansible-playbook` on PATH does not imply `ansible-galaxy` is, and the
    doctor checks the former before reaching this call."""

    def fake(argv: list[str], **_kwargs: Any) -> SimpleNamespace:
        raise FileNotFoundError(2, "No such file or directory", "ansible-galaxy")

    monkeypatch.setattr(provision_freshness.subprocess, "run", fake)

    with pytest.raises(provision_freshness.FreshnessError, match="ansible-galaxy"):
        provision_freshness.collections_off_declaration(DECLARED)


def test_the_declaration_read_is_the_repository_file() -> None:
    declared = provision_freshness.declared_collections(REPO)
    assert declared == {c["name"]: str(c["version"]) for c in _declared()}


@pytest.mark.parametrize(
    ("content", "why"),
    [
        (None, "the file is absent"),
        ("collections: [\n", "the YAML does not parse"),
        ("- a list, not a mapping\n", "the document is not a mapping"),
        ("galaxy: []\n", "the mapping declares no `collections`"),
        ("collections: ansible.posix\n", "`collections` is not a list"),
        ("collections:\n  - version: 2.2.2\n", "an entry names no collection"),
        ("collections:\n  - name: ansible.posix\n", "an entry pins no version"),
    ],
)
def test_a_declaration_it_cannot_read_is_a_refusal_not_a_crash(tmp_path: Path, content: str | None, why: str) -> None:
    """Every shape below escaped this function as a different exception type.

    `declared_collections` is read on the path that renders a run, before a node is
    touched, by both `make deploy` and `toolkit infra ansible doctor`. A
    `FileNotFoundError`, a `yaml.ParserError`, a `TypeError` or a `KeyError` there is
    a traceback out of a gate whose entire purpose is to refuse and say why -- so a
    controller with a damaged declaration crashed instead of being told what to fix.
    """
    if content is not None:
        path = tmp_path / provision_freshness.REQUIREMENTS
        path.parent.mkdir(parents=True)
        path.write_text(content, encoding="utf-8")

    with pytest.raises(provision_freshness.DeclarationError, match=str(provision_freshness.REQUIREMENTS)):
        provision_freshness.declared_collections(tmp_path)


def test_a_declaration_with_two_documents_says_so(tmp_path: Path) -> None:
    """`safe_load` reads exactly one document, so a second `---` arrives as
    `ComposerError` — not as a syntax error. Reporting it as "is not YAML" sends
    the operator looking for a broken bracket in a file that is perfectly
    well-formed, which is the same class of dead end as a fix naming a flag that
    does not exist."""
    path = tmp_path / provision_freshness.REQUIREMENTS
    path.parent.mkdir(parents=True)
    path.write_text(
        "collections:\n  - name: ansible.posix\n    version: 2.2.2\n---\ncollections: []\n",
        encoding="utf-8",
    )

    with pytest.raises(provision_freshness.DeclarationError, match="more than one YAML document"):
        provision_freshness.declared_collections(tmp_path)


def test_a_listing_that_cannot_be_read_is_not_a_declaration_problem(monkeypatch: pytest.MonkeyPatch) -> None:
    """The two refusals name different repairs -- the file, or `ansible-galaxy` --
    so the types have to differ. They shared one, and that is why a `requirements.yml`
    nothing could parse was answered with "Fix ansible-galaxy": a repair for a file
    the operator was never told was the problem."""
    monkeypatch.setattr(
        provision_freshness.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="not json", stderr=""),
    )

    with pytest.raises(provision_freshness.FreshnessError) as raised:
        provision_freshness.collections_off_declaration(DECLARED)

    assert not isinstance(raised.value, provision_freshness.DeclarationError)


def test_a_well_formed_declaration_still_reads(tmp_path: Path) -> None:
    """The guard must refuse the malformed shapes without refusing the good one:
    a gate that rejects everything is the fail-closed twin of one that accepts
    everything."""
    path = tmp_path / provision_freshness.REQUIREMENTS
    path.parent.mkdir(parents=True)
    path.write_text("collections:\n  - name: ansible.posix\n    version: 2.2.2\n", encoding="utf-8")

    assert provision_freshness.declared_collections(tmp_path) == {"ansible.posix": "2.2.2"}


def test_the_refusal_names_the_collections_the_cause_and_the_way_out() -> None:
    message = provision_freshness.collections_refusal_message(["ansible.posix 2.1.0 at /c (declared 2.2.2)"])
    assert "ansible.posix 2.1.0 at /c (declared 2.2.2)" in message
    assert "full `ansible` package" in message, "a copy setup-ansible does not replace needs its own way out"
    assert "WHY:" in message
    assert "make setup-ansible" in message
    assert "FORCE=1" in message


def test_setup_ansible_shows_the_install_and_fails_with_it() -> None:
    recipe = subprocess.run(
        ["make", "-n", "-C", str(REPO), "setup-ansible"], capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout
    install = next(line for line in recipe.splitlines() if "collection install" in line)
    assert "/dev/null" not in install, "the install output is the only report of what it did"
    assert re.search(r"collection install -r \S+requirements\.yml\s*&&", install), "success must follow the install"
