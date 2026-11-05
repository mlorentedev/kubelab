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
    # The squash message is the judge's, built from what it judged (#3062 F6).
    "deploy-merge.yml": (
        'if gh pr merge "$n" --squash --match-head-commit "$sha" --subject "$subject" --body "$body"; then'
    ),
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

    def test_the_pause_reads_deploy_verify(self) -> None:
        """#3062 F11: a red deploy-verify on master pauses every merge. Pointing the
        pause at another workflow would silently stop it."""
        import yaml

        from toolkit.features.deploy_merge import CONTEXT_PREFIX, DEPLOY_VERIFY, VERDICT_WINDOW

        assert DEPLOY_VERIFY == "deploy-verify.yml", f"the pause reads {DEPLOY_VERIFY}: {DECIDED}"
        assert VERDICT_WINDOW == 100, f"the pause reads {VERDICT_WINDOW} runs for a verdict: {DECIDED}"
        text = (WORKFLOWS / DEPLOY_VERIFY).read_text(encoding="utf-8")
        # The prefix the judge matches is the one deploy-verify reacts to.
        assert f"startsWith(github.event.context, '{CONTEXT_PREFIX}')" in text, f"{CONTEXT_PREFIX}: {DECIDED}"
        # Every job names the context it judged, or the judge cannot tell staging from prod.
        jobs = yaml.safe_load(text)["jobs"]
        for job_id, job in jobs.items():
            name = job.get("name", "")
            assert name.endswith(")") and f"({CONTEXT_PREFIX}" in name or "(${{ github.event.context }})" in name, (
                f"deploy-verify job {job_id} is named {name!r}, which does not carry its context: {DECIDED}"
            )

    def test_a_refused_close_does_not_stop_the_merges(self) -> None:
        """#3062 F7: under `set -e` one refused close stopped the job before the merge
        step, on every run while it kept failing."""
        import yaml

        steps = yaml.safe_load((WORKFLOWS / "deploy-merge.yml").read_text(encoding="utf-8"))["jobs"]["merge"]["steps"]
        close = next(s for s in steps if s.get("id") == "close")
        # The default shell is `bash -e`; only an explicit `set +e` clears it.
        assert re.search(r"^set \+e$", close["run"], re.M), "the close step stops at its first failure"
        assert not re.search(r"^\s*set -\w*e", close["run"], re.M), "the close step stops at its first failure"
        names = [s.get("name") for s in steps]
        assert names.index("Fail on a refused close") > names.index("Merge mechanical deploys at the judged sha")

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
        "merge": """done < <(jq -r '.decisions[] | select(.action == "merge") | [.pr, .head_sha, .subject, .body] | """
        """@tsv' "$RUNNER_TEMP/decisions.json")""",
        "close": """done < <(jq -r '.decisions[] | select(.action == "close") | "\\(.pr) \\(.head_sha)"' """
        """"$RUNNER_TEMP/decisions.json")""",
    }

    def test_the_merge_and_close_loops_read_only_their_own_decisions_and_the_judged_sha(self) -> None:
        # A continued line is one shell line.
        text = re.sub(r"\\\n\s*", "", (WORKFLOWS / "deploy-merge.yml").read_text(encoding="utf-8"))
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
            "actions": "read",
        }, f"deploy-merge.yml's token scope is {wf['permissions']}: {DECIDED}"
        granted = sorted(name for name, job in wf["jobs"].items() if "permissions" in job)
        assert not granted, f"jobs {granted} carry their own grant, which overrides the pinned one: {DECIDED}"


class TestTheJudgeIsMasters:
    """Every workflow that decides on the class runs master's code and declarations,
    never a PR's head: a PR that could choose its judge could choose its verdict
    (review-2 F1). Pinned per checkout and per invocation."""

    MASTER = "${{ github.event.repository.default_branch }}"
    CHECKOUT = {"ref": MASTER, "fetch-depth": 1}
    # The whole `run:` of each judge step, so nothing can be prepended to it.
    JUDGES = {
        "deploy-merge.yml": (
            "set -euo pipefail\n"
            'poetry run toolkit tools deploy-merge --out "$RUNNER_TEMP/decisions.json"\n'
            'echo "enabled=$(jq -r .enabled "$RUNNER_TEMP/decisions.json")" >> "$GITHUB_OUTPUT"\n'
        ),
        "deploy-shape.yml": (
            "set +e\n"
            'poetry run toolkit tools deploy-shape --pr "$NUMBER" --out "$RUNNER_TEMP/deploy-shape.json"\n'
            'echo "code=$?" >> "$GITHUB_OUTPUT"\n'
        ),
        "review-attestation.yml": (
            'poetry run toolkit tools deploy-shape --pr "$NUMBER" --out "$RUNNER_TEMP/deploy-shape.json" || true\n'
        ),
    }
    # Commands that would swap the checked-out code after the checkout step.
    RESWAP = ("git checkout", "git switch", "git fetch", "git reset", "git worktree", "PYTHONPATH")

    @staticmethod
    def _steps(workflow: str) -> list[dict]:
        import yaml

        wf = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))
        return [step for job in wf["jobs"].values() for step in job.get("steps", [])]

    @pytest.mark.parametrize("workflow", sorted(JUDGES))
    def test_every_checkout_is_the_default_branch(self, workflow: str) -> None:
        """The whole `with:`, so no `repository:`, `token:` or `ssh-key:` can sit
        beside a pinned `ref` and check out a fork's branch of the same name."""
        checkouts = [s for s in self._steps(workflow) if str(s.get("uses", "")).startswith("actions/checkout@")]
        assert checkouts, f"{workflow} has no checkout; this test lost its subject"
        for step in checkouts:
            assert step.get("with") == self.CHECKOUT, f"{workflow} checks out {step.get('with')}: {DECIDED}"

    @pytest.mark.parametrize("workflow", sorted(JUDGES))
    def test_the_judge_runs_with_its_declared_arguments(self, workflow: str) -> None:
        tool = "deploy-merge" if workflow == "deploy-merge.yml" else "deploy-shape"
        runs = [s["run"] for s in self._steps(workflow) if f"poetry run toolkit tools {tool}" in s.get("run", "")]
        assert runs == [self.JUDGES[workflow]], f"{workflow} runs {runs}: {DECIDED}"

    @pytest.mark.parametrize("workflow", sorted(JUDGES))
    def test_no_step_swaps_the_checked_out_code(self, workflow: str) -> None:
        swaps = [
            (step.get("name") or step.get("id"), cmd)
            for step in self._steps(workflow)
            for cmd in self.RESWAP
            if cmd in step.get("run", "")
        ]
        assert not swaps, f"{workflow} swaps master's code after checkout: {swaps}: {DECIDED}"


# Who opened a PR, or what its branch is called, is something anyone with push
# access can choose. The granting side therefore reads neither (global rule:
# never match a branch name to GRANT). pr-agent.yml may FORFEIT a review by
# branch name; that direction is safe, and is not scanned here (review-2 F2).
#
# Read from the AST, not by regex, so every access form counts: `["ref"]`,
# `.get("ref")`, a constant bound to a name first. `review_attestation.py` reads
# authors to recognise REVIEWS, which is its job, so only the code that decides
# the exemption is scanned there: `exempt_signature` and `classify`'s exempt block.
NAME_KEYS = frozenset({"login", "user", "actor", "author", "head_ref", "headRefName", "sender"})


def _granting_code() -> dict[str, list]:
    import ast

    def parse(rel: str):
        return ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))

    attestation = parse("toolkit/features/review_attestation.py")
    exempt_fn = next(n for n in attestation.body if isinstance(n, ast.FunctionDef) and n.name == "exempt_signature")
    classify_fn = next(n for n in attestation.body if isinstance(n, ast.FunctionDef) and n.name == "classify")
    # The exempt block: every `if` in classify whose body returns an "exempt" verdict.
    exempt_ifs = [
        node
        for node in ast.walk(classify_fn)
        if isinstance(node, ast.If)
        and any(isinstance(c, ast.Constant) and c.value == "exempt" for c in ast.walk(ast.Module(node.body, [])))
    ]
    assert exempt_ifs, "classify's exempt block was not found; this test lost its subject"
    # A helper the exempt block delegates to decides the exemption too: follow
    # calls to module-level functions, transitively.
    functions = {n.name: n for n in attestation.body if isinstance(n, ast.FunctionDef)}
    scanned, pending = [exempt_fn, *exempt_ifs], [exempt_fn, *exempt_ifs]
    while pending:
        for node in ast.walk(pending.pop()):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                helper = functions.get(node.func.id)
                if helper is not None and helper not in scanned and helper is not classify_fn:
                    scanned.append(helper)
                    pending.append(helper)
    return {
        "toolkit/features/deploy_merge.py": [parse("toolkit/features/deploy_merge.py")],
        "toolkit/features/deploy_shape.py": [parse("toolkit/features/deploy_shape.py")],
        "toolkit/features/review_attestation.py (exemption)": scanned,
    }


def test_every_exempt_verdict_is_inside_the_scanned_code() -> None:
    """The scan above covers only the exemption's code, so an "exempt" verdict
    produced anywhere else, or through a constant bound to a name, would never be
    scanned. Both are refused here."""
    import ast

    tree = ast.parse((REPO_ROOT / "toolkit/features/review_attestation.py").read_text(encoding="utf-8"))

    def at(n) -> tuple:  # _granting_code parses its own tree, so nodes compare by position
        return (getattr(n, "lineno", None), getattr(n, "col_offset", None))

    inside = {
        at(n) for root in _granting_code()["toolkit/features/review_attestation.py (exemption)"] for n in ast.walk(root)
    }
    outside = [
        n.lineno for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value == "exempt" and at(n) not in inside
    ]
    assert not outside, f'"exempt" outside the scanned exemption code, line(s) {outside}: {DECIDED}'
    aliases = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, (ast.Assign, ast.AnnAssign))
        and isinstance(n.value, ast.Constant)
        and n.value.value == "exempt"
    ]
    assert not aliases, f'"exempt" bound to a name at line(s) {aliases}; the scan cannot follow it: {DECIDED}'


def _name_reads(roots: list) -> list[str]:
    """String constants that name an author or a branch. `"ref"` is allowed only
    under `"base"` (which branch a PR targets is not chosen by its author)."""
    import ast

    hits = []
    for root in roots:
        parents = {child: node for node in ast.walk(root) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(root):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            value = node.value
            if value in NAME_KEYS or value.startswith("deploy/"):
                hits.append(value)
            elif value == "ref":
                holder = parents.get(node)
                if isinstance(holder, ast.Call):  # x.get("ref")
                    holder = holder.func
                target = ast.unparse(getattr(holder, "value", holder))
                if not target.endswith("['base']"):
                    hits.append(f"ref of {target}")
    return hits


@pytest.mark.parametrize("module", sorted(_granting_code()))
def test_the_granting_side_reads_no_branch_name_or_author(module: str) -> None:
    hits = _name_reads(_granting_code()[module])
    assert not hits, f"{module} reads {hits}; a grant keyed on a name anyone can mint: {DECIDED}"


@pytest.mark.parametrize(
    "source",
    [
        'pr["head"].get("ref")',
        'pr["head"]["ref"]',
        'pr["user"]["login"]',
        'pr.get("headRefName")',
        'event["sender"]',
        'ref.startswith("deploy/")',
    ],
)
def test_the_name_detector_fires(source: str) -> None:
    """Positive control: a detector that silently returned nothing would keep
    every scan above green."""
    import ast

    assert _name_reads([ast.parse(source)]), f"{source} was not detected"


def test_the_name_detector_allows_the_base_ref() -> None:
    import ast

    assert not _name_reads([ast.parse('pr["base"]["ref"]; pr["base"].get("ref")')])


def test_the_required_contexts_are_the_approved_ones() -> None:
    """The judge refuses unless every required context passes, so the set is part of
    the merging actor's condition. Dropping `Tests` from it would merge with tests
    red (review-2 F4)."""
    from toolkit.features.deploy_merge import required_contexts

    found = required_contexts(REPO_ROOT / "infra/config/values/common.yaml", "mlorentedev/kubelab", "master")
    assert set(found) == {"Validate", "Detect Changes", "review-attestation", "Tests", "deploy-shape"}, (
        f"master's required contexts are {found}: {DECIDED}"
    )
