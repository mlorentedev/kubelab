"""APP-CONFIG-015 (#1712) AC3: every v2 filter-type node carries the v2 filter shape.

An n8n IF node at `typeVersion >= 2` declares `conditions` as a `filter` parameter.
n8n 2.12.3 evaluates it through `extractValueFilter`, which starts with
`if (!isFilterValue(value)) return value;`, and `isFilterValue` only asks whether
the value has `conditions` AND `combinator` (n8n-workflow `type-guards.js`). A node
carrying v1-shaped parameters (`conditions.boolean[]`) fails that check, so the IF
receives the parameter object itself as `pass`. An object is truthy, so EVERY item
goes to the TRUE branch, whatever the condition says. Nothing errors, and the
editor renders the node as if it were fine.

Four gates had that shape, two of them the public signature gates of
`multi-forge-sync` and `slack-task-capture`, which is how an unsigned request
reached the Vikunja write nodes (lesson-467). v1 IF nodes read
`conditions.boolean` correctly and are left alone.

The shape asserted here is n8n's own `FilterValueSchema` (n8n-workflow
`schemas.js`), not a guess at what the editor exports. A correct shape that tests
the wrong field would pass it, so each original gate is also pinned to the field
it gated on before the migration.
"""

from __future__ import annotations

import json
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / "infra" / "n8n" / "workflows"

#: Node types whose `conditions` parameter is a `filter` from typeVersion 2 on.
FILTER_NODE_TYPES = {
    "n8n-nodes-base.if",
    "n8n-nodes-base.filter",
}

#: `FilterTypeCombinatorSchema`.
COMBINATORS = {"and", "or"}

#: `FilterOptionsValueSchema.typeValidation`.
TYPE_VALIDATIONS = {"strict", "loose"}

#: The four gates that carried v1 parameters at v2, and the boolean each gated on.
#: Pinned so the migration cannot change WHAT a gate tests while fixing its shape.
MIGRATED_GATES = {
    ("agent-dispatcher.json", "Is Delegable?"): "isDelegable",
    ("multi-forge-sync.json", "Has Task Key & Valid Sig?"): "hasTask",
    ("multi-forge-sync.json", "Found Matched Task in Vikunja?"): "hasMatchedTask",
    ("slack-task-capture.json", "Is Slack Valid?"): "isValidSlack",
}


def _v2_filter_nodes() -> list[tuple[str, dict]]:
    found = []
    for path in sorted(WORKFLOW_DIR.glob("*.json")):
        for node in json.loads(path.read_text())["nodes"]:
            if node["type"] in FILTER_NODE_TYPES and node.get("typeVersion", 1) >= 2:
                found.append((path.name, node))
    return found


def _shape_errors(conditions: object) -> list[str]:
    """Where `conditions` departs from n8n's `FilterValueSchema`, as readable lines."""
    if not isinstance(conditions, dict):
        return ["`conditions` is not an object"]
    errors = []
    # The two keys `isFilterValue` checks. Missing either one = unconditionally TRUE.
    if conditions.get("combinator") not in COMBINATORS:
        errors.append(f"`combinator` is {conditions.get('combinator')!r}, not one of {sorted(COMBINATORS)}")
    rows = conditions.get("conditions")
    if not isinstance(rows, list) or not rows:
        errors.append("`conditions.conditions` is not a non-empty list")
        rows = []
    options = conditions.get("options")
    if not isinstance(options, dict):
        errors.append("`conditions.options` is missing")
    else:
        if not isinstance(options.get("caseSensitive"), bool):
            errors.append("`options.caseSensitive` is not a boolean")
        if options.get("typeValidation") not in TYPE_VALIDATIONS:
            errors.append(f"`options.typeValidation` is not one of {sorted(TYPE_VALIDATIONS)}")
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"condition {i} is not an object")
            continue
        for key in ("id", "leftValue", "rightValue", "operator"):
            if key not in row:
                errors.append(f"condition {i} has no `{key}`")
        operator = row.get("operator")
        if not isinstance(operator, dict) or not operator.get("type") or not operator.get("operation"):
            errors.append(f"condition {i} has no `operator.type` and `operator.operation`")
    return errors


def test_there_are_v2_filter_nodes_to_check() -> None:
    # Guard against the parametrised test below silently collecting nothing.
    assert len(_v2_filter_nodes()) >= len(MIGRATED_GATES)


@pytest.mark.parametrize(
    ("workflow", "node"),
    _v2_filter_nodes(),
    ids=lambda v: v if isinstance(v, str) else v["name"],
)
def test_v2_filter_node_carries_the_v2_filter_shape(workflow: str, node: dict) -> None:
    errors = _shape_errors(node["parameters"].get("conditions"))
    assert not errors, (
        f"{workflow} / {node['name']!r} is typeVersion {node['typeVersion']} but its "
        "`conditions` is not an n8n v2 filter, so n8n routes EVERY item to TRUE:\n  "
        + "\n  ".join(errors)
        + "\nRebuild it in the n8n editor, or write the v2 shape (lesson-467). "
        "Do not pin the node back to typeVersion 1."
    )


@pytest.mark.parametrize(("key", "field"), MIGRATED_GATES.items(), ids=[k[1] for k in MIGRATED_GATES])
def test_migrated_gate_still_tests_its_original_field_for_true(key: tuple[str, str], field: str) -> None:
    workflow, name = key
    nodes = json.loads((WORKFLOW_DIR / workflow).read_text())["nodes"]
    node = next(n for n in nodes if n["name"] == name)
    rows = node["parameters"]["conditions"]["conditions"]
    assert len(rows) == 1, f"{name!r} should test exactly one condition, has {len(rows)}"
    (row,) = rows
    assert row["leftValue"] == f"={{{{ $json.{field} }}}}"
    assert row["operator"]["type"] == "boolean"
    assert row["operator"]["operation"] == "true"
