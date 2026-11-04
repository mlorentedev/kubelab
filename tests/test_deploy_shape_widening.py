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

from toolkit.features.deploy_merge import ALLOWED_UNSTABLE, MERGE_STATES_OK
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
    # The merge step's switch, ON since PR 4 (2026-11-03, evidence on #1619).
    # Changing it here and in the registry is one reviewed diff, never a test fix.
    "merge": True,
}

# Every way a workflow can merge a pull request. Auto-merge has its own guard
# (tests/test_no_auto_merge.py); this one is about an explicit merge call.
MERGE_CALLS = {
    "gh pr merge": re.compile(r"\bgh\s+pr\s+merge\b"),
    "REST merge endpoint": re.compile(r"pulls/[^\s/]+/merge\b"),
    "GraphQL mergePullRequest": re.compile(r"\bmergePullRequest\b"),
}

# Workflow files allowed to merge, with the exact merge line each may run. The
# sha pin is the condition: without it, a head pushed after the judging merges.
MERGERS: dict[str, str] = {
    "deploy-merge.yml": 'if gh pr merge "$n" --squash --match-head-commit "$sha"; then',
}


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
        for tag in (
            "1.4.0",
            "v1.4.0",
            "latest",
            "main",
            "sha-9d79e5",
            "sha-9D79E52",
            "xsha-9d79e52",
            "sha-" + "a" * 41,
        ):
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
        # Exact kinds, not just names: a REST merge in a declared merger would skip the head pin.
        assert found == {workflow: ["gh pr merge"] for workflow in MERGERS}, (
            f"workflows that merge pull requests: {found}; declared: {sorted(MERGERS)}. A new merger is {DECIDED}."
        )

    def test_the_contexts_unstable_may_excuse_are_the_approved_ones(self) -> None:
        """#2983: option B on #1619 was approved for `add-to-project` only. Each added name
        is a context the merger stops enforcing."""
        assert ALLOWED_UNSTABLE == frozenset({"add-to-project"}), f"unstable excuses {set(ALLOWED_UNSTABLE)}: {DECIDED}"

    def test_the_merge_states_the_judge_accepts_are_the_approved_ones(self) -> None:
        """`unstable` was added on #1619 (2026-11-01): only contexts that are not required fail
        there, and the judge checks every required one itself. Anything else here is a widening."""
        assert MERGE_STATES_OK == frozenset({"clean", "unstable"}), (
            f"the judge accepts {set(MERGE_STATES_OK)}: {DECIDED}"
        )

    @pytest.mark.parametrize("workflow", sorted(MERGERS))
    def test_each_merger_runs_exactly_its_declared_line(self, workflow: str) -> None:
        text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
        lines = [line.strip() for line in text.splitlines() if MERGE_CALLS["gh pr merge"].search(line)]
        assert lines == [MERGERS[workflow]], f"{workflow} merges with {lines}: {DECIDED}"

    def test_writes_happen_only_behind_the_switch_and_only_the_merge_holds_the_pat(self) -> None:
        """deploy-merge.yml: a step that merges or closes runs only when the judge read the
        switch as on, and the PAT (whose merges start push workflows) reaches the merge alone."""
        import yaml

        steps = yaml.safe_load((WORKFLOWS / "deploy-merge.yml").read_text(encoding="utf-8"))["jobs"]["merge"]["steps"]
        writers = [s for s in steps if re.search(r"gh pr merge|-X (PATCH|POST)", s.get("run", ""))]
        assert len(writers) == 2, [s.get("name") for s in writers]
        for step in writers:
            assert step.get("if") == "steps.judge.outputs.enabled == 'true'", f"{step['name']}: {DECIDED}"
        holders = [s["name"] for s in steps if "RELEASE_PLEASE_TOKEN" in str(s)]
        merger = [s["name"] for s in writers if "gh pr merge" in s["run"]]
        assert holders == merger, f"RELEASE_PLEASE_TOKEN reaches {holders}, not only the merge: {DECIDED}"

    # What feeds the merge and close loops: the judge's decisions, filtered to exactly
    # one action, each carrying the sha the judge read. Widening the filter (say to
    # `!= "skip"`) or feeding anything but `.head_sha` as the sha leaves the merge line
    # above intact and still widens what merges (adversarial review of #1619).
    FEEDS = {
        "merge": """done < <(jq -r '.decisions[] | select(.action == "merge") | "\\(.pr) \\(.head_sha)"' """
        """"$RUNNER_TEMP/decisions.json")""",
        "close": """jq -r '.decisions[] | select(.action == "close") | "\\(.pr) \\(.head_sha)"' """
        """"$RUNNER_TEMP/decisions.json" |""",
    }

    def test_the_merge_and_close_loops_read_only_their_own_decisions_and_the_judged_sha(self) -> None:
        text = (WORKFLOWS / "deploy-merge.yml").read_text(encoding="utf-8")
        feeds = [line.strip() for line in text.splitlines() if "decisions.json" in line and "select(" in line]
        writers = [line for line in feeds if "would " not in line]
        assert sorted(writers) == sorted(self.FEEDS.values()), (
            f"deploy-merge.yml feeds its writes with {writers}: {DECIDED}"
        )

    def test_the_triggers_and_the_token_scope_are_the_approved_ones(self) -> None:
        """When the merger runs and what its GITHUB_TOKEN may do. A wildcard
        workflow_run or a `contents: write` grant changes the actor, not the class."""
        import yaml

        wf = yaml.safe_load((WORKFLOWS / "deploy-merge.yml").read_text(encoding="utf-8"))
        triggers = wf.get("on", wf.get(True))  # PyYAML reads the bare key `on` as True
        assert triggers == {
            "workflow_run": {"workflows": ["CI", "review-attestation", "deploy-shape"], "types": ["completed"]},
            "schedule": [{"cron": "17,47 * * * *"}],
            "workflow_dispatch": None,
        }, f"deploy-merge.yml triggers on {triggers}: {DECIDED}"
        assert wf["permissions"] == {
            "contents": "read",
            "pull-requests": "write",
            "checks": "read",
            "statuses": "read",
        }, f"deploy-merge.yml's token scope is {wf['permissions']}: {DECIDED}"
        granted = sorted(name for name, job in wf["jobs"].items() if "permissions" in job)
        assert not granted, f"jobs {granted} carry their own grant, which overrides the pinned one: {DECIDED}"


class TestTheJudgeIsMasters:
    """Every workflow that decides on the class runs master's code and declarations,
    never a PR's head: a PR that could choose its judge could choose its verdict
    (review-2 F1). Pinned per checkout and per invocation."""

    MASTER = "${{ github.event.repository.default_branch }}"
    JUDGES = {
        "deploy-merge.yml": 'poetry run toolkit tools deploy-merge --out "$RUNNER_TEMP/decisions.json"',
        "deploy-shape.yml": (
            'poetry run toolkit tools deploy-shape --pr "$NUMBER" --out "$RUNNER_TEMP/deploy-shape.json"'
        ),
        "review-attestation.yml": (
            'poetry run toolkit tools deploy-shape --pr "$NUMBER" --out "$RUNNER_TEMP/deploy-shape.json" || true'
        ),
    }

    @pytest.mark.parametrize("workflow", sorted(JUDGES))
    def test_every_checkout_is_the_default_branch(self, workflow: str) -> None:
        import yaml

        wf = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))
        checkouts = [
            step
            for job in wf["jobs"].values()
            for step in job.get("steps", [])
            if str(step.get("uses", "")).startswith("actions/checkout@")
        ]
        assert checkouts, f"{workflow} has no checkout; this test lost its subject"
        for step in checkouts:
            ref = step.get("with", {}).get("ref")
            assert ref == self.MASTER, f"{workflow} checks out {step.get('with')}: {DECIDED}"

    @pytest.mark.parametrize("workflow", sorted(JUDGES))
    def test_the_judge_runs_with_its_declared_arguments(self, workflow: str) -> None:
        text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
        tool = "deploy-merge" if workflow == "deploy-merge.yml" else "deploy-shape"
        lines = [line.strip() for line in text.splitlines() if f"poetry run toolkit tools {tool}" in line]
        assert lines == [self.JUDGES[workflow]], f"{workflow} runs {lines}: {DECIDED}"


# Who opened a PR, or what its branch is called, is something anyone with push
# access can choose. The granting side therefore reads neither (global rule:
# never match a branch name to GRANT). pr-agent.yml may FORFEIT a review by
# branch name; that direction is safe, and is not scanned here (review-2 F2).
GRANTING_MODULES = ("toolkit/features/deploy_merge.py", "toolkit/features/deploy_shape.py")
NAME_RULES = {
    "head ref": re.compile(r"""\[\s*["']head["']\s*\]\s*\[\s*["']ref["']\s*\]|head_ref|headRefName"""),
    "author": re.compile(r"""\[\s*["']user["']\s*\]|["']login["']|\bauthor\b"""),
    "branch prefix": re.compile(r"""["']deploy/"""),
}


def _code_only(path: pathlib.Path) -> str:
    """The module without comments or docstrings, which may name what the code never reads."""
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr):
            if isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


@pytest.mark.parametrize("module", GRANTING_MODULES)
def test_the_granting_side_reads_no_branch_name_or_author(module: str) -> None:
    text = _code_only(REPO_ROOT / module)
    hits = {name for name, rx in NAME_RULES.items() if rx.search(text)}
    assert not hits, f"{module} reads {sorted(hits)}; a grant keyed on a name anyone can mint: {DECIDED}"


def test_the_required_contexts_are_the_approved_ones() -> None:
    """The judge refuses unless every required context passes, so the set is part of
    the merging actor's condition. Dropping `Tests` from it would merge with tests
    red (review-2 F4)."""
    from toolkit.features.deploy_merge import required_contexts

    found = required_contexts(REPO_ROOT / "infra/config/values/common.yaml", "mlorentedev/kubelab", "master")
    assert set(found) == {"Validate", "Detect Changes", "review-attestation", "Tests", "deploy-shape"}, (
        f"master's required contexts are {found}: {DECIDED}"
    )
