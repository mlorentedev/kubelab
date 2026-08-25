"""Classify the bitácora board by stream (GOV-002, #823).

The board had no field that answers "which area of work is this?". Measured on
2026-08-24: 492 open issues, 84 title-prefix families, 24 of them holding a single
issue, and every board field either unset or set to one value for two thirds of
the backlog (Priority: 339 `P2` + 131 empty; Type: 334 `chore` + 139 empty). The
prefix in the title was the only signal, and a title is not filterable.

This module makes the stream a board field and keeps it true:

- `harness/board-streams.yaml` is the registry: which title prefixes belong to
  which stream, plus per-issue overrides for titles that carry no prefix or a
  misleading one. Every prefix maps to exactly one stream; the loader refuses a
  registry that says otherwise.
- `plan()` is pure: given the open items and the registry it says which items
  need which value and which it cannot place. Nothing is written until the
  caller asks for it, and only the items whose value differs are written.
- `check` is the mode a hook can run: it exits non-zero while any open issue is
  unplaced, so the field cannot decay the way Priority and Type did.

Titles are never rewritten. The prefix is the ticket's historical identifier;
renumbering `VPNACL-001` into the `VPN-ACL` family would collide with closed
issues and break every reference in docs and lessons. The field carries the
classification; the title keeps the identity.

GitHub is reached through `gh api graphql` so the operator's existing auth is
reused and no token lives in this repository. Enumerating the project once
(~30 pages for ~2,600 items) is the cheap direction for a full pass; per-issue
lookups are the cheap direction for a single issue and are not what this does.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_REGISTRY = Path("harness/board-streams.yaml")

#: `OBS-018`, `IDP-005b`, `OPS-D004`, `PROD-K3S-000e`, `BACKUP-EPIC`.
_PREFIX = re.compile(r"^\s*([A-Z][A-Z0-9]*(?:-[A-Z][A-Z0-9]*)*?)-(?:D?\d{1,4}[a-z]?|EPIC)\b")
#: `DOCS: ...`, `CI: ...` — a bare family word used as a label, no number.
_WORD = re.compile(r"^\s*([A-Z][A-Z0-9]{1,12}):")

#: Options are created with these; GitHub requires a colour per option.
_OPTION_COLOR = "GRAY"


class RegistryError(Exception):
    """The stream registry is missing, unparseable, or contradicts itself."""


class GitHubError(Exception):
    """`gh api graphql` failed or returned errors."""


@dataclass(frozen=True)
class Registry:
    owner: str
    number: int
    repo: str
    field: str
    streams: tuple[str, ...]
    prefix_to_stream: dict[str, str]
    overrides: dict[int, str]
    #: Sequencing ticket -> the issues it orders. Becomes GitHub parent/sub-issue links.
    parts: dict[int, tuple[int, ...]] = dc_field(default_factory=dict)


def load_registry(path: Path = DEFAULT_REGISTRY) -> Registry:
    """Load and validate the registry. A prefix in two streams is an error."""
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
    field = raw.get("field")
    if not isinstance(field, str) or not field.strip():
        raise RegistryError("registry: field must be a non-empty string")

    streams: list[str] = []
    prefix_to_stream: dict[str, str] = {}
    for entry in raw.get("streams") or []:
        name = entry.get("name") if isinstance(entry, dict) else None
        if not name:
            raise RegistryError("registry: every stream needs a name")
        if name in streams:
            raise RegistryError(f"registry: stream declared twice: {name}")
        streams.append(name)
        for prefix in entry.get("prefixes") or []:
            if prefix in prefix_to_stream:
                raise RegistryError(f"registry: prefix {prefix} is in both {prefix_to_stream[prefix]!r} and {name!r}")
            prefix_to_stream[prefix] = name
    if not streams:
        raise RegistryError("registry: no streams declared")

    overrides: dict[int, str] = {}
    for key, value in (raw.get("overrides") or {}).items():
        try:
            number = int(key)
        except (TypeError, ValueError) as exc:
            raise RegistryError(f"registry: override key is not an issue number: {key!r}") from exc
        if value not in streams:
            raise RegistryError(f"registry: override #{number} names unknown stream {value!r}")
        overrides[number] = value

    parts: dict[int, tuple[int, ...]] = {}
    child_parent: dict[int, int] = {}
    for key, value in (raw.get("parts") or {}).items():
        try:
            parent = int(key)
            children = tuple(int(c) for c in (value or []))
        except (TypeError, ValueError) as exc:
            raise RegistryError(f"registry: parts entry is not issue numbers: {key!r}") from exc
        for child in children:
            if child == parent:
                raise RegistryError(f"registry: #{parent} lists itself as a part")
            if child in child_parent:
                raise RegistryError(f"registry: #{child} is listed under both #{child_parent[child]} and #{parent}")
            child_parent[child] = parent
        parts[parent] = children

    return Registry(
        owner=str(project["owner"]),
        number=int(project["number"]),
        repo=str(project["repo"]),
        field=field.strip(),
        streams=tuple(streams),
        prefix_to_stream=prefix_to_stream,
        overrides=overrides,
        parts=parts,
    )


def title_prefix(title: str) -> str | None:
    """The family a title declares, or None when it declares nothing."""
    match = _PREFIX.match(title) or _WORD.match(title)
    return match.group(1) if match else None


def classify(number: int, title: str, registry: Registry) -> str | None:
    """The stream an issue belongs to. An override beats the title; None means unplaced."""
    if number in registry.overrides:
        return registry.overrides[number]
    prefix = title_prefix(title)
    if prefix is None:
        return None
    return registry.prefix_to_stream.get(prefix)


@dataclass(frozen=True)
class Item:
    item_id: str
    number: int
    title: str
    current: str | None


@dataclass(frozen=True)
class Change:
    item: Item
    desired: str


@dataclass(frozen=True)
class Plan:
    changes: tuple[Change, ...]
    unplaced: tuple[Item, ...]
    unchanged: int

    def counts(self) -> dict[str, int]:
        """Desired stream sizes after the plan is applied."""
        out: dict[str, int] = {}
        for change in self.changes:
            out[change.desired] = out.get(change.desired, 0) + 1
        return out


def plan(items: list[Item], registry: Registry) -> Plan:
    """Decide what to write. Pure; safe to call as often as you like."""
    changes: list[Change] = []
    unplaced: list[Item] = []
    unchanged = 0
    for item in items:
        desired = classify(item.number, item.title, registry)
        if desired is None:
            unplaced.append(item)
        elif desired == item.current:
            unchanged += 1
        else:
            changes.append(Change(item=item, desired=desired))
    return Plan(changes=tuple(changes), unplaced=tuple(unplaced), unchanged=unchanged)


def desired_counts(items: list[Item], registry: Registry) -> dict[str, int]:
    """Stream sizes the registry implies for these items (placed ones only)."""
    out: dict[str, int] = {}
    for item in items:
        stream = classify(item.number, item.title, registry)
        if stream is not None:
            out[stream] = out.get(stream, 0) + 1
    return out


# --- GitHub -----------------------------------------------------------------


def _gh_graphql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run one GraphQL request through `gh`. Raises on transport or GraphQL errors."""
    body = json.dumps({"query": query, "variables": variables or {}})
    try:
        proc = subprocess.run(
            ["gh", "api", "graphql", "-H", "GraphQL-Features: sub_issues", "--input", "-"],
            input=body,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitHubError("gh CLI not found") from exc
    if proc.returncode != 0:
        raise GitHubError(proc.stderr.strip() or proc.stdout.strip() or "gh api graphql failed")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise GitHubError(f"gh returned non-JSON: {proc.stdout[:200]}") from exc
    if data.get("errors"):
        raise GitHubError(json.dumps(data["errors"])[:500])
    return data["data"]


@dataclass(frozen=True)
class ProjectInfo:
    project_id: str
    field_id: str | None
    options: dict[str, str]  # option name -> option id


_PROJECT_QUERY = """
query($owner: String!, $number: Int!) {
  user(login: $owner) {
    projectV2(number: $number) {
      id
      fields(first: 40) {
        nodes {
          ... on ProjectV2SingleSelectField { id name options { id name } }
        }
      }
    }
  }
}
"""


def fetch_project(registry: Registry) -> ProjectInfo:
    data = _gh_graphql(_PROJECT_QUERY, {"owner": registry.owner, "number": registry.number})
    project = (data.get("user") or {}).get("projectV2")
    if not project:
        raise GitHubError(f"project {registry.owner}/{registry.number} not found")
    for node in project["fields"]["nodes"]:
        if node and node.get("name") == registry.field:
            return ProjectInfo(
                project_id=project["id"],
                field_id=node["id"],
                options={opt["name"]: opt["id"] for opt in node["options"]},
            )
    return ProjectInfo(project_id=project["id"], field_id=None, options={})


_ITEMS_QUERY = """
query($owner: String!, $number: Int!, $field: String!, $after: String) {
  user(login: $owner) {
    projectV2(number: $number) {
      items(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          content {
            __typename
            ... on Issue { number title state repository { nameWithOwner } }
          }
          fieldValueByName(name: $field) {
            ... on ProjectV2ItemFieldSingleSelectValue { name }
          }
        }
      }
    }
  }
}
"""


def fetch_open_items(registry: Registry) -> list[Item]:
    """Every OPEN issue of the registry's repo that is on the board."""
    items: list[Item] = []
    after: str | None = None
    while True:
        data = _gh_graphql(
            _ITEMS_QUERY,
            {
                "owner": registry.owner,
                "number": registry.number,
                "field": registry.field,
                "after": after,
            },
        )
        page = data["user"]["projectV2"]["items"]
        for node in page["nodes"]:
            content = node.get("content") or {}
            if content.get("__typename") != "Issue" or content.get("state") != "OPEN":
                continue
            if (content.get("repository") or {}).get("nameWithOwner") != registry.repo:
                continue
            value = node.get("fieldValueByName") or {}
            items.append(
                Item(
                    item_id=node["id"],
                    number=int(content["number"]),
                    title=content["title"],
                    current=value.get("name"),
                )
            )
        if not page["pageInfo"]["hasNextPage"]:
            return items
        after = page["pageInfo"]["endCursor"]


_CREATE_FIELD = """
mutation($projectId: ID!, $name: String!, $options: [ProjectV2SingleSelectFieldOptionInput!]!) {
  createProjectV2Field(input: {
    projectId: $projectId, dataType: SINGLE_SELECT, name: $name, singleSelectOptions: $options
  }) {
    projectV2Field { ... on ProjectV2SingleSelectField { id options { id name } } }
  }
}
"""


def ensure_field(registry: Registry, info: ProjectInfo) -> ProjectInfo:
    """Create the field with every stream as an option, or verify it already has them.

    An existing field with options missing is refused rather than rewritten:
    `updateProjectV2Field` replaces the option list wholesale, and a replaced
    option loses the value on every item that carried it.
    """
    if info.field_id is not None:
        missing = [s for s in registry.streams if s not in info.options]
        if missing:
            raise RegistryError(
                f"field {registry.field!r} exists but lacks options: {missing}. "
                "Add them in the board UI (Settings > Fields), then re-run."
            )
        return info
    options = [{"name": s, "color": _OPTION_COLOR, "description": ""} for s in registry.streams]
    data = _gh_graphql(
        _CREATE_FIELD,
        {"projectId": info.project_id, "name": registry.field, "options": options},
    )
    created = data["createProjectV2Field"]["projectV2Field"]
    return ProjectInfo(
        project_id=info.project_id,
        field_id=created["id"],
        options={opt["name"]: opt["id"] for opt in created["options"]},
    )


def _batch_mutation(project_id: str, field_id: str, batch: list[tuple[str, str]]) -> str:
    """One request carrying several `updateProjectV2ItemFieldValue` calls, aliased."""
    parts = []
    for index, (item_id, option_id) in enumerate(batch):
        parts.append(
            f"m{index}: updateProjectV2ItemFieldValue(input: {{"
            f"projectId: {json.dumps(project_id)}, itemId: {json.dumps(item_id)}, "
            f"fieldId: {json.dumps(field_id)}, "
            f"value: {{ singleSelectOptionId: {json.dumps(option_id)} }}"
            f"}}) {{ projectV2Item {{ id }} }}"
        )
    return "mutation {\n" + "\n".join(parts) + "\n}"


def apply(info: ProjectInfo, changes: tuple[Change, ...], batch_size: int = 25) -> int:
    """Write every change; returns how many items were written."""
    if info.field_id is None:
        raise RegistryError("field does not exist; call ensure_field first")
    pairs = [(c.item.item_id, info.options[c.desired]) for c in changes]
    written = 0
    for start in range(0, len(pairs), batch_size):
        batch = pairs[start : start + batch_size]
        _gh_graphql(_batch_mutation(info.project_id, info.field_id, batch))
        written += len(batch)
    return written


# --- parts: a sequencing ticket becomes the parent of what it orders ---------
#
# Four tickets already order a stream's work in prose ("read before starting
# #N"). Measured 2026-08-25: 3 open issues had a parent, 0 acted as one. Prose
# declares the dependency from one side only — the child never knows — which is
# how #606 was nearly closed as unrelated while gating #395. A parent link is
# visible from both ends and gives the board its `Sub-issues progress` for free.


@dataclass(frozen=True)
class IssueRef:
    number: int
    node_id: str
    state: str
    parent: int | None


def _refs_query(repo: str, numbers: list[int]) -> str:
    owner, name = repo.split("/", 1)
    lines = "\n".join(f"i{n}: issue(number: {n}) {{ id number state parent {{ number }} }}" for n in numbers)
    return f"query {{ repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{\n{lines}\n}} }}"


def fetch_issue_refs(registry: Registry, numbers: list[int], batch_size: int = 50) -> dict[int, IssueRef]:
    """Node ids, state and current parent for these issue numbers."""
    refs: dict[int, IssueRef] = {}
    for start in range(0, len(numbers), batch_size):
        batch = numbers[start : start + batch_size]
        data = _gh_graphql(_refs_query(registry.repo, batch))
        for node in data["repository"].values():
            if not node:
                continue
            parent = node.get("parent")
            refs[int(node["number"])] = IssueRef(
                number=int(node["number"]),
                node_id=node["id"],
                state=node["state"],
                parent=int(parent["number"]) if parent else None,
            )
    return refs


@dataclass(frozen=True)
class Link:
    parent: int
    child: int


@dataclass(frozen=True)
class PartsPlan:
    links: tuple[Link, ...]
    linked: int
    #: (child, its current parent, the parent the registry wants) — never overwritten.
    conflicts: tuple[tuple[int, int, int], ...]
    missing: tuple[int, ...]


def plan_parts(registry: Registry, refs: dict[int, IssueRef]) -> PartsPlan:
    """Which links to add. A child that already has another parent is a conflict, not a write."""
    links: list[Link] = []
    conflicts: list[tuple[int, int, int]] = []
    missing: list[int] = []
    linked = 0
    for parent, children in registry.parts.items():
        if parent not in refs:
            missing.append(parent)
            continue
        for child in children:
            ref = refs.get(child)
            if ref is None:
                missing.append(child)
            elif ref.parent == parent:
                linked += 1
            elif ref.parent is None:
                links.append(Link(parent=parent, child=child))
            else:
                conflicts.append((child, ref.parent, parent))
    return PartsPlan(links=tuple(links), linked=linked, conflicts=tuple(conflicts), missing=tuple(missing))


_ADD_SUB_ISSUE = """
mutation($parent: ID!, $child: ID!) {
  addSubIssue(input: { issueId: $parent, subIssueId: $child }) { issue { id } }
}
"""


def apply_parts(refs: dict[int, IssueRef], links: tuple[Link, ...]) -> int:
    """Add every link; returns how many were added."""
    for link in links:
        _gh_graphql(
            _ADD_SUB_ISSUE,
            {"parent": refs[link.parent].node_id, "child": refs[link.child].node_id},
        )
    return len(links)
