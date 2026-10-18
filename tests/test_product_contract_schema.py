"""The published JSON Schema is generated from the contract model (IDP-042 PR 1, Q3).

Product authors validate against the JSON file; kubelab validates against the
pydantic model. One is generated from the other, and this keeps them equal.
Regenerate with ``poetry run python -m toolkit.features.product_contract --write-schema``.
"""

from __future__ import annotations

import json
from importlib.resources import files

from toolkit.features.product_contract import SCHEMA_ID, Contract

SCHEMA = files("toolkit") / "schemas" / "kubelab-product.schema.json"


def test_committed_schema_equals_the_model() -> None:
    expected = json.dumps(Contract.model_json_schema(), indent=2, sort_keys=True) + "\n"

    assert SCHEMA.read_text() == expected, "regenerate: python -m toolkit.features.product_contract --write-schema"


def test_schema_carries_its_public_id() -> None:
    schema = json.loads(SCHEMA.read_text())

    assert schema["$id"] == SCHEMA_ID
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_schema_is_closed_at_every_level() -> None:
    """``additionalProperties: false`` is what refuses a contract naming its own repository."""
    schema = json.loads(SCHEMA.read_text())

    assert schema["additionalProperties"] is False
    assert all(d["additionalProperties"] is False for d in schema["$defs"].values())
