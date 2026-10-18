"""The `area:*` labels ADR-066 D6 promises: declared once, created by the reconciler (APP-CONFIG-021)."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from toolkit.features.vikunja_client import VikunjaClient
from toolkit.features.vikunja_reconciler import (
    AREA_COLOR,
    DEFAULT_LABELS,
    ReconcileError,
    VikunjaDeclaration,
    VikunjaReconciler,
    declaration_from_config,
)

COMMON = Path(__file__).resolve().parents[1] / "infra/config/values/common.yaml"
#: The AREA segment of the spec `idPattern` (cli/internal/spec/spec.go): upper-case segments, digits allowed.
AREA_SEGMENT = re.compile(r"^[A-Z]+[0-9]*(-[A-Z]+[0-9]*)*$")


def _declared(areas: tuple[str, ...]) -> VikunjaDeclaration:
    return VikunjaDeclaration(("Bitacora",), "kubelab", "write", ("manu",), areas=areas)


@pytest.fixture
def client() -> MagicMock:
    c = MagicMock(spec=VikunjaClient)
    c.get_projects.return_value = [{"id": 2, "title": "Bitacora"}]
    c.get_teams.return_value = [{"id": 5, "name": "kubelab"}]
    c.get_team.return_value = {"id": 5, "members": [{"username": "manu"}]}
    c.get_project_teams.return_value = [{"id": 5, "permission": 1}]
    c.get_labels.return_value = [{"title": t} for t in DEFAULT_LABELS]
    return c


def test_each_declared_area_becomes_one_labelled_area(client: MagicMock) -> None:
    res = VikunjaReconciler(client=client).reconcile(_declared(("OPS", "APP-CONFIG")))
    assert res.labels_created == 2
    titles = {c.kwargs["title"] for c in client.create_label.call_args_list}
    assert titles == {"area:OPS", "area:APP-CONFIG"}
    assert {c.kwargs["hex_color"] for c in client.create_label.call_args_list} == {AREA_COLOR}


def test_an_area_that_already_exists_is_left_alone(client: MagicMock) -> None:
    client.get_labels.return_value = [{"title": t} for t in DEFAULT_LABELS] + [{"title": "area:OPS"}]
    res = VikunjaReconciler(client=client).reconcile(_declared(("OPS",)))
    assert res.changed is False
    client.create_label.assert_not_called()


def test_no_declared_area_changes_nothing(client: MagicMock) -> None:
    assert VikunjaReconciler(client=client).reconcile(_declared(())).changed is False


def _config(areas: object) -> dict:
    return {
        "apps": {
            "auth": {"identities": {"owner": "manu"}},
            "services": {
                "core": {
                    "vikunja": {
                        "projects": ["Bitacora"],
                        "team": {"name": "kubelab", "right": "write", "members": ["owner"]},
                        "labels": {"areas": areas},
                    }
                }
            },
        }
    }


def test_the_declaration_reads_the_areas() -> None:
    assert declaration_from_config(_config(["OPS", "TF"])).areas == ("OPS", "TF")


@pytest.mark.parametrize("bad", ["ops", "OPS NNN", "OPS-", "area:OPS", "", "OPS\n"])
def test_a_value_that_is_not_an_area_segment_is_refused(bad: str) -> None:
    with pytest.raises(ReconcileError, match="not an AREA segment"):
        declaration_from_config(_config([bad]))


def test_an_empty_areas_key_is_refused_not_a_traceback() -> None:
    config = _config([])
    config["apps"]["services"]["core"]["vikunja"]["labels"]["areas"] = None
    with pytest.raises(ReconcileError, match="declared but empty"):
        declaration_from_config(config)


@pytest.mark.parametrize("scalar", ["OPS", 7])
def test_a_scalar_areas_value_is_refused_not_split_into_characters(scalar: object) -> None:
    config = _config([])
    config["apps"]["services"]["core"]["vikunja"]["labels"]["areas"] = scalar
    with pytest.raises(ReconcileError, match="must be a list"):
        declaration_from_config(config)


def test_a_duplicate_area_is_refused() -> None:
    with pytest.raises(ReconcileError, match="twice"):
        declaration_from_config(_config(["OPS", "OPS"]))


def test_common_yaml_declares_valid_areas() -> None:
    """The committed vocabulary is non-empty and every entry is an AREA the ticket ids can carry."""
    config = yaml.safe_load(COMMON.read_text(encoding="utf-8"))
    declared = declaration_from_config(config)
    assert len(declared.areas) >= 20
    assert all(AREA_SEGMENT.match(a) for a in declared.areas)
