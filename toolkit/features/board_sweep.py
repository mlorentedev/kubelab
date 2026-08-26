"""Apply a reviewed In Progress sweep to the bitácora board (GOV-005, #1417).

`harness/board-inprogress-sweep.yaml` is the recorded decision for a fixed set
of issues: `stays` keeps Status at "In Progress" and writes the Priority the
issue was missing; `parked` moves Status to "Backlog" and leaves Priority
alone. The decision itself — which issue had a real thread behind it and which
had none since filing — was made once, by hand, against each issue's body and
comment history; this module only makes it true on the board and only for the
issues the registry names.

Unlike `board_streams`, this is not a classifier meant to run forever: the
registry is a one-time list, and `plan()` only ever touches those numbers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from toolkit.core import gh_graphql

DEFAULT_REGISTRY = Path("harness/board-inprogress-sweep.yaml")

_STAYS_STATUS = "In Progress"
_PARKED_STATUS = "Backlog"


class RegistryError(Exception):
    """The sweep registry is missing, unparseable, or contradicts itself."""


class GitHubError(Exception):
    """`gh api graphql` failed or returned errors."""


@dataclass(frozen=True)
class Registry:
    owner: str
    number: int
    repo: str
    status_field: str
    priority_field: str
    #: issue number -> priority to write if the issue lacks one (None = don't touch priority)
    stays: dict[int, str | None]
    parked: tuple[int, ...]


def load_registry(path: Path = DEFAULT_REGISTRY) -> Registry:
    """Load and validate the sweep registry. An issue in both `stays` and `parked` is an error."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RegistryError(f"registry not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise RegistryError(f"registry is not valid YAML: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RegistryError(f"registry root must be a mapping: {path}")

    project = raw.get("project") or {}
    for key in ("owner", "number", "repo"):
        if key not in project:
            raise RegistryError(f"registry: project.{key} is required")

    status_field = raw.get("status_field")
    priority_field = raw.get("priority_field")
    if not isinstance(status_field, str) or not status_field.strip():
        raise RegistryError("registry: status_field must be a non-empty string")
    if not isinstance(priority_field, str) or not priority_field.strip():
        raise RegistryError("registry: priority_field must be a non-empty string")

    stays: dict[int, str | None] = {}
    for key, value in (raw.get("stays") or {}).items():
        try:
            number = int(key)
        except (TypeError, ValueError) as exc:
            raise RegistryError(f"registry: stays key is not an issue number: {key!r}") from exc
        priority = (value or {}).get("priority") if isinstance(value, dict) else None
        stays[number] = priority

    parked: list[int] = []
    for entry in raw.get("parked") or []:
        try:
            parked.append(int(entry))
        except (TypeError, ValueError) as exc:
            raise RegistryError(f"registry: parked entry is not an issue number: {entry!r}") from exc

    overlap = set(stays) & set(parked)
    if overlap:
        raise RegistryError(f"registry: issue(s) listed in both stays and parked: {sorted(overlap)}")

    return Registry(
        owner=str(project["owner"]),
        number=int(project["number"]),
        repo=str(project["repo"]),
        status_field=status_field.strip(),
        priority_field=priority_field.strip(),
        stays=stays,
        parked=tuple(parked),
    )


@dataclass(frozen=True)
class Item:
    item_id: str
    number: int
    status: str | None
    priority: str | None


@dataclass(frozen=True)
class Change:
    item: Item
    status: str | None  # None = leave Status untouched
    priority: str | None  # None = leave Priority untouched


@dataclass(frozen=True)
class Plan:
    changes: tuple[Change, ...]
    unchanged: int
    missing: tuple[int, ...]  # registry numbers not found on the board


def plan(items: dict[int, Item], registry: Registry) -> Plan:
    """Decide what to write for every issue the registry names. Pure; safe to call often."""
    changes: list[Change] = []
    unchanged = 0
    missing: list[int] = []

    for number, desired_priority in registry.stays.items():
        item = items.get(number)
        if item is None:
            missing.append(number)
            continue
        status_change = None if item.status == _STAYS_STATUS else _STAYS_STATUS
        priority_change = desired_priority if item.priority is None and desired_priority else None
        if status_change is None and priority_change is None:
            unchanged += 1
        else:
            changes.append(Change(item=item, status=status_change, priority=priority_change))

    for number in registry.parked:
        item = items.get(number)
        if item is None:
            missing.append(number)
            continue
        if item.status == _PARKED_STATUS:
            unchanged += 1
        else:
            changes.append(Change(item=item, status=_PARKED_STATUS, priority=None))

    return Plan(changes=tuple(changes), unchanged=unchanged, missing=tuple(missing))


# --- GitHub -------------------------------------------------------------------


def _gh_graphql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return gh_graphql.run(query, variables)
    except gh_graphql.GraphQLError as exc:
        raise GitHubError(str(exc)) from exc


@dataclass(frozen=True)
class FieldInfo:
    field_id: str
    options: dict[str, str]  # option name -> option id


_FIELDS_QUERY = """
query($owner: String!, $number: Int!, $after: String) {
  user(login: $owner) {
    projectV2(number: $number) {
      id
      fields(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          ... on ProjectV2SingleSelectField { id name options { id name } }
        }
      }
    }
  }
}
"""


def fetch_fields(registry: Registry) -> tuple[str, dict[str, FieldInfo]]:
    """The project id, and Status/Priority field ids + options. Walks every field page."""
    wanted = {registry.status_field, registry.priority_field}
    found: dict[str, FieldInfo] = {}
    after: str | None = None
    project_id: str | None = None
    while True:
        data = _gh_graphql(_FIELDS_QUERY, {"owner": registry.owner, "number": registry.number, "after": after})
        project = (data.get("user") or {}).get("projectV2")
        if not project:
            raise GitHubError(f"project {registry.owner}/{registry.number} not found")
        project_id = project["id"]
        for node in project["fields"]["nodes"]:
            if node and node.get("name") in wanted:
                found[node["name"]] = FieldInfo(
                    field_id=node["id"],
                    options={opt["name"]: opt["id"] for opt in node["options"]},
                )
        page = project["fields"]["pageInfo"]
        if not page["hasNextPage"] or len(found) == len(wanted):
            break
        after = page["endCursor"]
    missing = wanted - found.keys()
    if missing:
        raise GitHubError(f"field(s) not found on the board: {sorted(missing)}")
    return project_id, found


def _issue_alias(number: int) -> str:
    return f"i{number}"


def fetch_items(registry: Registry, numbers: list[int]) -> dict[int, Item]:
    """Current Status/Priority + the board item id, for these specific issue numbers.

    Per-issue lookup through `issue.projectItems`, not a full project scan: cheap
    for the handful of issues a one-time sweep touches, unlike a registry meant
    to classify the whole board.
    """
    if not numbers:
        return {}
    owner, name = registry.repo.split("/", 1)
    lines = "\n".join(
        f"{_issue_alias(n)}: issue(number: {n}) {{\n"
        f"  number\n"
        f"  projectItems(first: 10) {{\n"
        f"    nodes {{\n"
        f"      id\n"
        f"      project {{ number }}\n"
        f"      status: fieldValueByName(name: {json.dumps(registry.status_field)}) "
        f"{{ ... on ProjectV2ItemFieldSingleSelectValue {{ name }} }}\n"
        f"      priority: fieldValueByName(name: {json.dumps(registry.priority_field)}) "
        f"{{ ... on ProjectV2ItemFieldSingleSelectValue {{ name }} }}\n"
        f"    }}\n"
        f"  }}\n"
        f"}}"
        for n in numbers
    )
    query = f"query {{ repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{\n{lines}\n}} }}"
    data = _gh_graphql(query)
    items: dict[int, Item] = {}
    for node in data["repository"].values():
        if not node:
            continue
        number = int(node["number"])
        for project_item in node["projectItems"]["nodes"]:
            if project_item["project"]["number"] != registry.number:
                continue
            status = (project_item.get("status") or {}).get("name")
            priority = (project_item.get("priority") or {}).get("name")
            items[number] = Item(item_id=project_item["id"], number=number, status=status, priority=priority)
            break
    return items


def _set_value_mutation(index: int, project_id: str, item_id: str, field_id: str, option_id: str) -> str:
    return (
        f"m{index}: updateProjectV2ItemFieldValue(input: {{"
        f"projectId: {json.dumps(project_id)}, itemId: {json.dumps(item_id)}, "
        f"fieldId: {json.dumps(field_id)}, "
        f"value: {{ singleSelectOptionId: {json.dumps(option_id)} }}"
        f"}}) {{ projectV2Item {{ id }} }}"
    )


def apply(
    project_id: str,
    fields: dict[str, FieldInfo],
    registry: Registry,
    changes: tuple[Change, ...],
    batch_size: int = 25,
) -> int:
    """Write every change; returns how many field values were written."""
    writes: list[tuple[str, str, str]] = []  # (item_id, field_id, option_id)
    for change in changes:
        if change.status is not None:
            status_field = fields[registry.status_field]
            writes.append((change.item.item_id, status_field.field_id, status_field.options[change.status]))
        if change.priority is not None:
            priority_field = fields[registry.priority_field]
            writes.append((change.item.item_id, priority_field.field_id, priority_field.options[change.priority]))
    written = 0
    for start in range(0, len(writes), batch_size):
        batch = writes[start : start + batch_size]
        mutations = [
            _set_value_mutation(i, project_id, item_id, field_id, option_id)
            for i, (item_id, field_id, option_id) in enumerate(batch)
        ]
        _gh_graphql("mutation {\n" + "\n".join(mutations) + "\n}")
        written += len(batch)
    return written
