"""The backup playbooks target a group derived from `backup.sources` (BACKUP-062, #1943).

`make backup-node NODE=all ENV=prod` exited 2 on every run: the playbook targeted
`hosts: all`, so it reached ace1, ace2, gcp1 and jetson, which do not run the
pipeline. Which nodes do is declared once, as the keys of `backup.sources`, and
three places restated it by hand (`backup.yml`'s literal host lists, `hosts: all`,
the Makefile usage strings).

The inventory generator now derives `node_backup` from those keys, and
`always_on` / `on_demand` from each host's ADR-028 `location`. These tests pin:
- the groups equal what the SSOT says, read from common.yaml, never restated here;
- a misdeclaration fails generation instead of thinning a group, because a play
  whose pattern matches nothing is a warning and exit 0;
- no backup playbook names a host or targets `all`.

A stale inventory without the group would turn a run into a silent no-op; that
is closed for every playbook by `ansible run` generating its own inventory
(TOOL-090, tests/test_ansible_run_generates_inventory.py).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.features.generator_ansible import BACKUP_GROUP, LOCATION_GROUPS, AnsibleGenerator

_ROOT = Path(__file__).resolve().parents[1]
_COMMON = _ROOT / "infra" / "config" / "values" / "common.yaml"
_PLAYBOOKS = _ROOT / "infra" / "ansible" / "playbooks"

_DERIVED = {BACKUP_GROUP, *LOCATION_GROUPS.values()}


def _common() -> dict[str, Any]:
    return yaml.safe_load(_COMMON.read_text())


def _inventory(networking: dict[str, Any] | None = None, sources: dict[str, Any] | None = None) -> dict[str, Any]:
    common = _common()
    return AnsibleGenerator()._build_inventory(
        networking if networking is not None else common["networking"],
        backup_sources=sources if sources is not None else common["backup"]["sources"],
    )


def _group(inventory: dict[str, Any], name: str) -> set[str]:
    return set((inventory["all"]["children"].get(name) or {}).get("hosts", {}))


def _hostname(networking: dict[str, Any], key: str) -> str:
    """The inventory hostname a SSOT key resolves to, the way the generator does."""
    if key in ("vps", "aws", "gcp"):
        return networking[key]["hostname"]
    return networking["nodes"][key].get("hostname", key)


class TestDerivedGroups:
    def test_node_backup_is_exactly_the_backup_sources_keys(self) -> None:
        common = _common()
        expected = {_hostname(common["networking"], key) for key in common["backup"]["sources"]}
        assert expected, "backup.sources is empty; the group would be empty too"
        assert _group(_inventory(), BACKUP_GROUP) == expected

    def test_every_host_has_exactly_one_availability_class(self) -> None:
        inventory = _inventory()
        every_host = {h for group in inventory["all"]["children"].values() for h in group["hosts"]}
        always_on = _group(inventory, "always_on")
        on_demand = _group(inventory, "on_demand")
        assert always_on | on_demand == every_host
        assert not always_on & on_demand

    def test_the_class_follows_the_declared_location(self) -> None:
        networking = _common()["networking"]
        inventory = _inventory()
        for key, node in networking["nodes"].items():
            if node.get("retired"):
                continue
            group = LOCATION_GROUPS[node["location"]]
            assert node.get("hostname", key) in _group(inventory, group), key


class TestMisdeclarationFailsGeneration:
    def test_a_backup_source_naming_no_host_fails(self) -> None:
        sources = dict(_common()["backup"]["sources"])
        sources["nonexistent"] = {}
        with pytest.raises(ValueError, match=r"backup\.sources\.nonexistent names no inventory host"):
            _inventory(sources=sources)

    def test_a_backup_source_on_a_retired_host_fails(self) -> None:
        networking = _common()["networking"]
        assert networking["aws"].get("retired"), "fixture assumption: aws1 is retired"
        with pytest.raises(ValueError, match=r"backup\.sources\.aws names no inventory host"):
            _inventory(sources={"aws": {}})

    def test_a_backup_host_without_a_location_fails(self) -> None:
        common = _common()
        networking = common["networking"]
        key = next(k for k in common["backup"]["sources"] if k in networking["nodes"])
        networking["nodes"][key].pop("location")
        with pytest.raises(ValueError, match=rf"backup\.sources\.{key}: .* declares no location"):
            _inventory(networking=networking)

    def test_an_unknown_location_fails(self) -> None:
        networking = _common()["networking"]
        networking["nodes"]["ace1"]["location"] = "sometimes"
        with pytest.raises(ValueError, match=r"networking\.ace1\.location is 'sometimes'"):
            _inventory(networking=networking)


def _backup_playbooks() -> list[Path]:
    return sorted(_PLAYBOOKS.glob("backup*.yml"))


class TestPlaybooksNameNoHost:
    def test_the_backup_playbooks_exist(self) -> None:
        names = {p.name for p in _backup_playbooks()}
        assert {"backup.yml", "backup-node.yml", "backup-schedule.yml", "backup-repo-reinit.yml"} <= names

    @pytest.mark.parametrize("playbook", _backup_playbooks(), ids=lambda p: p.name)
    def test_every_play_targets_node_backup_through_derived_groups_only(self, playbook: Path) -> None:
        plays = [p for p in yaml.safe_load(playbook.read_text()) if "hosts" in p]
        assert plays, playbook.name
        for play in plays:
            pattern = str(play["hosts"])
            terms = {t.lstrip("&!") for t in re.split(r"[:,]", pattern) if t}
            assert terms <= _DERIVED, f"{playbook.name}: '{pattern}' names {sorted(terms - _DERIVED)}"
            assert BACKUP_GROUP in terms, f"{playbook.name}: '{pattern}' is not narrowed to {BACKUP_GROUP}"
