"""The mechanical class must not widen without someone deciding it (DELIVERY-004, #1619).

Operator conditions (c) and (d) of the "diff nobody wrote" exception: committed
tests go red if EITHER the class definition OR the merging actor's own condition
widens, and prod stays unreachable. A definition that can grow by a one-line
edit to a JSON file is a permission anyone with write access can extend, so
each field is pinned here. The message on failure names who decides: widening
this class widens what merges without a human, which is the operator's call on
#1619, never a test update made to get CI green.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from toolkit.features.deploy_shape import load_declaration
from toolkit.features.review_attestation import DEFAULT_REGISTRY

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / DEFAULT_REGISTRY
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

DECIDED = "decided by the operator on #1619; changing it widens what merges without a human"

# The class as approved, field for field. Narrowing it is also a change and is
# also caught: the point is that the declaration and this file move together,
# in one reviewed diff.
APPROVED = {
    "name": "staging deploy (single app)",
    "check": "deploy-shape",
    "env": "staging",
    "values_file": "infra/config/values/staging.yaml",
    "overlay_files": ["infra/k8s/overlays/staging/generated/deployments.yaml"],
    "version_path": ["apps", "platform", "{app}", "version"],
    "tag_pattern": "^sha-[0-9a-f]{7,40}$",
}

# Every way a workflow can merge a pull request. Auto-merge has its own guard
# (tests/test_no_auto_merge.py); this one is about an explicit merge call.
MERGE_CALLS = {
    "gh pr merge": re.compile(r"\bgh\s+pr\s+merge\b"),
    "REST merge endpoint": re.compile(r"pulls/[^\s/]+/merge\b"),
    "GraphQL mergePullRequest": re.compile(r"\bmergePullRequest\b"),
}

# Workflow files allowed to merge, with the exact merge line each may run.
# Empty until the merge step lands, switched off (spec PR 3).
MERGERS: dict[str, str] = {}


@pytest.fixture(scope="module")
def block() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))["mechanical"]


class TestDefinitionDoesNotWiden:
    @pytest.mark.parametrize("field", sorted(APPROVED))
    def test_each_field_is_the_approved_one(self, block: dict, field: str) -> None:
        assert block.get(field) == APPROVED[field], f"mechanical.{field} changed: {DECIDED}"

    def test_no_field_was_added(self, block: dict) -> None:
        """A new key the module does not read yet is a widening waiting for code."""
        extra = set(block) - set(APPROVED) - {"why"}
        assert not extra, f"mechanical gained {sorted(extra)}: {DECIDED}"

    def test_the_tag_pattern_is_anchored_and_immutable_only(self) -> None:
        pattern = load_declaration(REGISTRY_PATH).tag_pattern
        for tag in ("sha-9d79e52", "sha-" + "a" * 40):
            assert pattern.fullmatch(tag), tag
        for tag in ("1.4.0", "v1.4.0", "latest", "main", "sha-9d79e5", "sha-9D79E52", "xsha-9d79e52", "sha-" + "a" * 41):
            assert not pattern.fullmatch(tag), f"{tag!r} admitted: {DECIDED}"


class TestProdIsUnreachable:
    """Condition (d): the class cannot reach prod, by its own declaration."""

    def test_the_class_is_staging_only(self) -> None:
        decl = load_declaration(REGISTRY_PATH)
        assert decl.env == "staging"
        for path in decl.files:
            assert "prod" not in pathlib.PurePosixPath(path).parts, path
            assert "prod" not in pathlib.PurePosixPath(path).name, path
            assert "staging" in path, path

    def test_no_prod_version_is_a_tag_the_class_admits(self) -> None:
        """Prod tracks released semver (ADR-046); not one of its pins may match."""
        pattern = load_declaration(REGISTRY_PATH).tag_pattern
        prod = (REPO_ROOT / "infra/config/values/prod.yaml").read_text(encoding="utf-8")
        versions = re.findall(r"^\s+version:\s*\"?([^\s\"#]+)", prod, flags=re.MULTILINE)
        assert versions, "no version pins found in values/prod.yaml; this test lost its subject"
        for version in versions:
            assert not pattern.fullmatch(version), f"prod pin {version!r} matches the staging class"


class TestMergingActorDoesNotWiden:
    """The merge job's own condition is pinned as tightly as the definition."""

    def test_only_declared_workflows_merge(self) -> None:
        found: dict[str, list[str]] = {}
        for wf in sorted(WORKFLOWS.glob("*.y*ml")):
            text = wf.read_text(encoding="utf-8")
            hits = [name for name, rx in MERGE_CALLS.items() if rx.search(text)]
            if hits:
                found[wf.name] = hits
        assert set(found) == set(MERGERS), (
            f"workflows that merge pull requests: {found}; declared: {sorted(MERGERS)}. A new merger is "
            f"{DECIDED}."
        )

    @pytest.mark.parametrize("workflow", sorted(MERGERS))
    def test_each_merger_runs_exactly_its_declared_line(self, workflow: str) -> None:
        text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
        lines = [line.strip() for line in text.splitlines() if MERGE_CALLS["gh pr merge"].search(line)]
        assert lines == [MERGERS[workflow]], f"{workflow} merges with {lines}: {DECIDED}"
