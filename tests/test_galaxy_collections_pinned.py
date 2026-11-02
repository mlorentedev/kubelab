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


def test_the_declaration_read_is_the_repository_file() -> None:
    declared = provision_freshness.declared_collections(REPO)
    assert declared == {c["name"]: str(c["version"]) for c in _declared()}


def test_the_refusal_names_the_collections_the_cause_and_the_way_out() -> None:
    message = provision_freshness.collections_refusal_message(["ansible.posix 2.1.0 at /c (declared 2.2.2)"])
    assert "ansible.posix 2.1.0 at /c (declared 2.2.2)" in message
    assert "full `ansible` package" in message, "a copy setup-ansible does not replace needs its own way out"
    assert "WHY:" in message
    assert "make setup-ansible" in message
    assert "FORCE=1" in message


def test_setup_ansible_shows_the_install_and_fails_with_it() -> None:
    recipe = subprocess.run(
        ["make", "-n", "-C", str(REPO), "setup-ansible"], capture_output=True, text=True, check=True
    ).stdout
    install = next(line for line in recipe.splitlines() if "collection install" in line)
    assert "/dev/null" not in install, "the install output is the only report of what it did"
    assert re.search(r"collection install -r \S+requirements\.yml\s*&&", install), "success must follow the install"
