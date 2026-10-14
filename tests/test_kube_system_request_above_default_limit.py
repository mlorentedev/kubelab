"""#2163 (OBS-032): the live check for a kube-system workload the LimitRange would
reject at admission goes red on that shape.

The live test (`tests/infra/test_k3s.py`) reads the cluster; this one feeds its
judgement fixtures, so CI proves it can fail without a cluster.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from tests.infra.test_k3s import _bytes, _requests_above_default_limit

DEFAULT_LIMIT = "384Mi"


def _workload(resources: dict[str, Any], *, init: bool = False) -> dict[str, Any]:
    container = {"name": "c", "resources": resources}
    key = "initContainers" if init else "containers"
    return {"kind": "Deployment", "metadata": {"name": "w"}, "spec": {"template": {"spec": {key: [container]}}}}


@pytest.mark.parametrize("init", [False, True], ids=["container", "initContainer"])
def test_a_request_above_the_default_with_no_limit_is_caught(init: bool) -> None:
    found = _requests_above_default_limit([_workload({"requests": {"memory": "512Mi"}}, init=init)], DEFAULT_LIMIT)
    assert found == ["Deployment/w/c requests 512Mi"]


@pytest.mark.parametrize(
    "resources",
    [
        {"requests": {"memory": "512Mi"}, "limits": {"memory": "1Gi"}},
        {"requests": {"memory": "384Mi"}},
        {"requests": {"memory": "400M"}},
        {"requests": {"cpu": "2"}},
        {},
    ],
    ids=["own-limit", "equal-to-default", "decimal-below", "no-memory-request", "no-resources"],
)
def test_an_admissible_container_is_not_reported(resources: dict[str, Any]) -> None:
    assert _requests_above_default_limit([_workload(resources)], DEFAULT_LIMIT) == []


@pytest.mark.parametrize(
    ("quantity", "expected"),
    [("384Mi", 384 * 2**20), ("1Gi", 2**30), ("400M", 400 * 10**6), ("1.5Gi", Decimal("1.5") * 2**30), ("1e9", 10**9)],
)
def test_quantities_are_read_in_bytes(quantity: str, expected: int | Decimal) -> None:
    assert _bytes(quantity) == expected
