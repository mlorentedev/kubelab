"""``resources:`` in the product contract (RES-HOST-001 slice B, ADR-073 D3 shape).

A claim is ``{<name>: {type, class?, params}}``: a union on ``type``, each member closed.
A v1 contract without ``resources:`` keeps validating (D1). The cross-field rule, a job's
``volume`` must name a declared volume claim, is a guard (``check_resources``), because the
schema cannot express it. Names here are fixtures, not any real product's.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.features import product_render
from toolkit.features.product_contract import Contract, ContractError, validate_contract
from toolkit.features.product_guards import check_resources

FIXTURE = Path(__file__).parent / "fixtures" / "product" / "web.kubelab.yaml"

CLAIMS: dict[str, Any] = {
    "data": {"type": "volume", "params": {"size": "1Gi", "mount_path": "/app/data", "fs_group": 10001}},
    "daily": {
        "type": "job",
        "params": {"schedule": "15 6 * * *", "command": ["resume", "daily"], "volume": "data"},
    },
}


def _with(resources: Any) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    data["resources"] = resources
    return data


def _write(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "kubelab.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8", newline="\n")
    return path


def _refused(tmp_path: Path, resources: Any) -> ContractError:
    with pytest.raises(ContractError) as excinfo:
        validate_contract(_write(tmp_path, _with(resources)))
    return excinfo.value


def _claims(**changes: Any) -> dict[str, Any]:
    """CLAIMS with ``<claim>__<key>`` set inside params (or on the claim for type/class)."""
    claims = copy.deepcopy(CLAIMS)
    for dotted, value in changes.items():
        name, key = dotted.split("__")
        target = claims[name] if key in {"type", "class"} else claims[name]["params"]
        target[key] = value
    return claims


def test_a_contract_without_resources_validates_and_declares_none() -> None:
    assert validate_contract(FIXTURE).resources == {}


def test_a_volume_and_a_job_validate_with_their_defaults(tmp_path: Path) -> None:
    contract = validate_contract(_write(tmp_path, _with(CLAIMS)))

    volume, job = contract.resources["data"], contract.resources["daily"]
    assert (volume.type, volume.class_, volume.params.size, volume.params.fs_group) == ("volume", "local", "1Gi", 10001)
    assert (job.type, job.class_, job.params.active_deadline_seconds) == ("job", "cron", 3600)
    check_resources(contract)


def test_the_class_may_be_given_explicitly(tmp_path: Path) -> None:
    validate_contract(_write(tmp_path, _with(_claims(data__class="local", daily__class="cron"))))


@pytest.mark.parametrize(
    ("resources", "field"),
    [
        (_claims(data__type="bucket"), "resources.data"),
        (_claims(data__class="nfs"), "resources.data.volume.class"),
        (_claims(daily__class="every-hour"), "resources.daily.job.class"),
        (_claims(data__sizee="1Gi"), "resources.data.volume.params.sizee"),
        (_claims(daily__retries=3), "resources.daily.job.params.retries"),
        (_claims(data__size="lots"), "resources.data.volume.params.size"),
        (_claims(data__size="0"), "resources.data.volume.params.size"),
        (_claims(data__size="0Gi"), "resources.data.volume.params.size"),
        (_claims(data__size="0.5Gi"), "resources.data.volume.params.size"),
        (_claims(data__mount_path="app/data"), "resources.data.volume.params.mount_path"),
        (_claims(data__mount_path="/"), "resources.data.volume.params.mount_path"),
        (_claims(data__mount_path="/app//data"), "resources.data.volume.params.mount_path"),
        (_claims(data__mount_path="/app/data/"), "resources.data.volume.params.mount_path"),
        (_claims(data__mount_path="/app/../etc"), "resources.data.volume.params.mount_path"),
        (_claims(data__fs_group=0), "resources.data.volume.params.fs_group"),
        (_claims(data__fs_group=2**31), "resources.data.volume.params.fs_group"),
        (_claims(data__fs_group="10001"), "resources.data.volume.params.fs_group"),
        (_claims(daily__schedule="every day"), "resources.daily.job.params.schedule"),
        (_claims(daily__schedule="15 6 * *"), "resources.daily.job.params.schedule"),
        (_claims(daily__command=[]), "resources.daily.job.params.command"),
        (_claims(daily__command="resume daily"), "resources.daily.job.params.command"),
        (_claims(daily__active_deadline_seconds=0), "resources.daily.job.params.active_deadline_seconds"),
        ({"Data": CLAIMS["data"]}, "resources.Data"),
        ({"-data": CLAIMS["data"]}, "resources.-data"),
        ({"d" * 32: CLAIMS["data"]}, "resources." + "d" * 32),
        ({"data": {"type": "volume"}}, "resources.data.volume.params"),
        ([CLAIMS["data"]], "resources"),
    ],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_a_malformed_claim_is_refused_naming_the_field(tmp_path: Path, resources: Any, field: str) -> None:
    err = _refused(tmp_path, resources)

    assert f"field '{field}'" in err.error


def test_a_resource_name_declared_twice_is_refused(tmp_path: Path) -> None:
    head = yaml.safe_dump({k: v for k, v in _with({}).items() if k != "resources"})
    path = tmp_path / "kubelab.yaml"
    path.write_text(head + "resources:\n  data: {type: volume}\n  data: {type: job}\n", encoding="utf-8", newline="\n")

    with pytest.raises(ContractError, match="'data' is declared twice"):
        validate_contract(path)


@pytest.mark.parametrize("volume", ["cache", "daily"], ids=["undeclared", "not-a-volume"])
def test_a_job_must_mount_a_declared_volume_claim(tmp_path: Path, volume: str) -> None:
    contract = validate_contract(_write(tmp_path, _with(_claims(daily__volume=volume))))

    with pytest.raises(ContractError) as excinfo:
        check_resources(contract)
    err = excinfo.value
    assert "field 'resources.daily.params.volume'" in err.error
    assert f"'{volume}'" in err.error
    assert "data" in err.fix


def test_the_admins_auth_level_validates_and_renders_as_forwardauth(tmp_path: Path) -> None:
    data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    data["auth"] = "forwardauth-admins"
    contract = Contract.model_validate(data)

    assert {key: product_render.CONTRACT_KEYS[key](contract, "staging") for key in ("enable_auth", "auth_level")} == {
        "enable_auth": True,
        "auth_level": "one_factor",
    }


def test_rendering_refuses_a_job_without_its_volume(tmp_path: Path) -> None:
    contract = Contract.model_validate(_with(_claims(daily__volume="cache")))

    with pytest.raises(ContractError, match="resources.daily.params.volume"):
        product_render.rendered(contract, "web", "staging")
