"""The `deploy-shape` predicate: a PR is a mechanical staging deploy, or it is not.

DELIVERY-004 (#1619), operator conditions (a) and (c). The predicate is what lets a
staging deploy PR skip review, and later merge without a click, so every condition
it checks has a test that breaks it on its own. The "before" side of each fixture
is the committed `values/staging.yaml` and generated overlay, not a hand-written
miniature: a fixture that only resembles the real file proves only that the two
agree with each other.

Version-only shapes measured on #2576 (web sha-f55a8c0) and #2581 (web
sha-9d79e52): exactly two files, each +1/-1.
"""

from __future__ import annotations

import pathlib
import re
from typing import Any

import pytest
import yaml

from toolkit.features.deploy_shape import (
    DeclarationError,
    classify_diff,
    evaluate,
    load_declaration,
)
from toolkit.features.product_registry import load_registry as load_products
from toolkit.features.review_attestation import DEFAULT_REGISTRY

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / DEFAULT_REGISTRY
VALUES = "infra/config/values/staging.yaml"
OVERLAY = "infra/k8s/overlays/staging/generated/deployments.yaml"
CONTRACT = "infra/config/products/contracts/web.yaml"
# A tag no pin carries: a real one (#2581's sha-9d79e52, as this file first used)
# lands on master, the bump becomes a no-op, and every fixture reads "0 values
# changed" on the merge commit CI tests.
SHORT = "0ddba11"
NEW = f"sha-{SHORT}"


@pytest.fixture(scope="module")
def decl():
    return load_declaration(REGISTRY_PATH)


@pytest.fixture(scope="module")
def apps() -> tuple[str, ...]:
    return tuple(load_products(REPO_ROOT / "infra/config/products.yaml").products)


def committed(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def current_version(app: str) -> str:
    """The version pinned for `app` in the committed staging values."""
    lines = committed(VALUES).splitlines()
    start = lines.index(f"    {app}:")
    for line in lines[start + 1 :]:
        if line.startswith("      version: "):
            return line.split(": ", 1)[1].strip()
    raise AssertionError(f"no version line under apps.platform.{app}")


def bump(app: str, new: str, *, values_extra=None, overlay_extra=None) -> tuple[dict, dict]:
    """The before/after pair `toolkit deployment promote` writes, plus optional damage."""
    old = current_version(app)
    before = {VALUES: committed(VALUES), OVERLAY: committed(OVERLAY)}
    lines = before[VALUES].splitlines(keepends=True)
    start = lines.index(f"    {app}:\n")
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("      version: "):
            lines[i] = f"      version: {new}\n"
            break
    values = "".join(lines)
    overlay = re.sub(rf"(kubelab-{app}):{re.escape(old)}\b", rf"\1:{new}", before[OVERLAY])
    if values_extra:
        values = values_extra(values)
    if overlay_extra:
        overlay = overlay_extra(overlay)
    return before, {VALUES: values, OVERLAY: overlay}


def changes(*paths: str, status: str = "modified") -> list[dict]:
    return [{"filename": p, "status": status} for p in paths]


# --------------------------------------------------------------------------- #
# The shapes that are mechanical
# --------------------------------------------------------------------------- #


class TestMechanical:
    @pytest.mark.parametrize("app", ["web", "api"])
    def test_the_fixture_tag_is_not_a_committed_pin(self, app: str) -> None:
        assert current_version(app) != NEW, f"{app} is pinned to {NEW}; pick another SHORT"

    @pytest.mark.parametrize("app", ["web", "api"])
    def test_a_version_only_bump_is_mechanical(self, decl, apps, app: str) -> None:
        before, after = bump(app, NEW)
        shape = classify_diff(changes(VALUES, OVERLAY), before, after, apps, decl)
        assert shape.verdict == "mechanical", shape.reason
        assert (shape.app, shape.old, shape.new) == (app, current_version(app), NEW)


# --------------------------------------------------------------------------- #
# Each condition refused on its own
# --------------------------------------------------------------------------- #


class TestFileSet:
    def test_a_contract_snapshot_makes_it_reviewable(self, decl, apps) -> None:
        """The contract-change path: reviewable, so not mechanical, and never red."""
        before, after = bump("web", NEW)
        before[CONTRACT], after[CONTRACT] = "a: 1\n", "a: 2\n"
        shape = classify_diff(changes(VALUES, OVERLAY, CONTRACT), before, after, apps, decl)
        assert shape.verdict == "not-mechanical"

    def test_values_alone_is_not_mechanical(self, decl, apps) -> None:
        before, after = bump("web", NEW)
        shape = classify_diff(changes(VALUES), before, after, apps, decl)
        assert shape.verdict == "not-mechanical"

    @pytest.mark.parametrize("status", ["added", "removed", "renamed"])
    def test_only_modified_files_count(self, decl, apps, status: str) -> None:
        before, after = bump("web", NEW)
        shape = classify_diff(changes(VALUES, OVERLAY, status=status), before, after, apps, decl)
        assert shape.verdict == "not-mechanical"

    def test_an_empty_diff_is_not_mechanical(self, decl, apps) -> None:
        assert classify_diff([], {}, {}, apps, decl).verdict == "not-mechanical"

    def test_the_prod_pair_is_not_mechanical(self, decl, apps) -> None:
        """Operator condition (d): the declaration admits staging only."""
        prod = ("infra/config/values/prod.yaml", "infra/k8s/overlays/prod/generated/deployments.yaml")
        before, after = bump("web", NEW)
        moved = {prod[0]: before[VALUES], prod[1]: before[OVERLAY]}
        moved_after = {prod[0]: after[VALUES], prod[1]: after[OVERLAY]}
        shape = classify_diff(changes(*prod), moved, moved_after, apps, decl)
        assert shape.verdict == "not-mechanical"


class TestValues:
    def test_a_second_changed_key_ends_it(self, decl, apps) -> None:
        """The gap the file-only signature left: any key in the two files rode along."""
        before, after = bump(
            "web", NEW, values_extra=lambda t: t.replace("enable_blog: false", "enable_blog: true", 1)
        )
        shape = classify_diff(changes(VALUES, OVERLAY), before, after, apps, decl)
        assert shape.verdict == "not-mechanical"

    def test_a_change_after_the_version_ends_it_too(self, decl, apps) -> None:
        """The leaf walk meets the version first here, so only a count catches this."""
        before, after = bump("web", NEW, values_extra=lambda t: t + "zz_rides_along: true\n")
        shape = classify_diff(changes(VALUES, OVERLAY), before, after, apps, decl)
        assert shape.verdict == "not-mechanical"

    def test_an_app_the_registry_does_not_admit_is_refused(self, decl) -> None:
        before, after = bump("web", NEW)
        shape = classify_diff(changes(VALUES, OVERLAY), before, after, ("api",), decl)
        assert shape.verdict == "not-mechanical"

    @pytest.mark.parametrize("tag", ["1.4.0", "v1.4.0", "sha-9D79E52", "sha-9d79e5", "latest"])
    def test_only_an_immutable_sha_tag_is_mechanical(self, decl, apps, tag: str) -> None:
        """A semver tag is the prod lane's; staging tracks sha tags only (ADR-046)."""
        before, after = bump("web", tag)
        shape = classify_diff(changes(VALUES, OVERLAY), before, after, apps, decl)
        assert shape.verdict == "not-mechanical", f"{tag!r} classified as mechanical"

    def test_no_values_change_is_not_mechanical(self, decl, apps) -> None:
        before, after = bump("web", current_version("web"))
        shape = classify_diff(changes(VALUES, OVERLAY), before, after, apps, decl)
        assert shape.verdict == "not-mechanical"


class TestOverlay:
    def test_a_changed_image_repository_ends_it(self, decl, apps) -> None:
        before, after = bump(
            "web", NEW, overlay_extra=lambda t: t.replace("mlorentedev/kubelab-web:", "attacker/kubelab-web:")
        )
        shape = classify_diff(changes(VALUES, OVERLAY), before, after, apps, decl)
        assert shape.verdict == "not-mechanical"

    def test_a_tag_other_than_the_values_change_ends_it(self, decl, apps) -> None:
        before, after = bump("web", NEW, overlay_extra=lambda t: t.replace(f"kubelab-web:{NEW}", "kubelab-web:sha-0000000"))
        shape = classify_diff(changes(VALUES, OVERLAY), before, after, apps, decl)
        assert shape.verdict == "not-mechanical"

    def test_any_other_overlay_leaf_ends_it(self, decl, apps) -> None:
        before, after = bump(
            "web", NEW, overlay_extra=lambda t: t.replace("imagePullPolicy: IfNotPresent", "imagePullPolicy: Always", 1)
        )
        shape = classify_diff(changes(VALUES, OVERLAY), before, after, apps, decl)
        assert shape.verdict == "not-mechanical"

    def test_an_overlay_that_did_not_move_ends_it(self, decl, apps) -> None:
        """The values moved and nothing deploys it: the drift gate's case, not a deploy."""
        before, after = bump("web", NEW)
        after[OVERLAY] = before[OVERLAY] + "\n"
        shape = classify_diff(changes(VALUES, OVERLAY), before, after, apps, decl)
        assert shape.verdict == "not-mechanical"


class TestFailsClosed:
    def test_unparseable_yaml_is_unknown(self, decl, apps) -> None:
        before, after = bump("web", NEW)
        after[VALUES] = "apps: [unclosed\n"
        assert classify_diff(changes(VALUES, OVERLAY), before, after, apps, decl).verdict == "unknown"

    def test_a_missing_content_is_unknown(self, decl, apps) -> None:
        before, after = bump("web", NEW)
        del after[OVERLAY]
        assert classify_diff(changes(VALUES, OVERLAY), before, after, apps, decl).verdict == "unknown"


# --------------------------------------------------------------------------- #
# The declaration
# --------------------------------------------------------------------------- #


class TestDeclaration:
    def test_the_committed_declaration_is_staging_only(self, decl) -> None:
        assert decl.env == "staging"
        assert set(decl.files) == {VALUES, OVERLAY}

    @pytest.mark.parametrize(
        "block",
        [None, {}, {"env": "staging"}, {"env": "staging", "values_file": "", "overlay_files": [], "version_path": [], "tag_pattern": ""}],
    )
    def test_a_malformed_declaration_refuses(self, tmp_path: pathlib.Path, block: Any) -> None:
        import json

        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        if block is None:
            data.pop("mechanical", None)
        else:
            data["mechanical"] = block
        path = tmp_path / "r.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(DeclarationError):
            load_declaration(path)

    def test_an_undecodable_declaration_refuses(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "r.json"
        path.write_bytes(b'{"mechanical": "\xff"}')
        with pytest.raises(DeclarationError):
            load_declaration(path)

    @pytest.mark.parametrize("which", ["registry", "products"])
    def test_any_load_failure_exits_unknown_not_a_verdict(self, tmp_path: pathlib.Path, which: str) -> None:
        """Exit 1 publishes neutral; a file the CLI cannot read must never read as one."""
        import json

        from typer.testing import CliRunner

        from toolkit.cli.tools import app

        broken = tmp_path / "broken"
        broken.write_bytes(b"\xff\xfe not text")
        args = {"registry": str(REGISTRY_PATH), "products": str(REPO_ROOT / "infra/config/products.yaml")}
        args[which] = str(broken)
        out = tmp_path / "v.json"
        result = CliRunner().invoke(
            app,
            ["deploy-shape", "--pr", "7", "--repo", REPO, "--registry", args["registry"],
             "--products", args["products"], "--out", str(out)],
        )
        assert result.exit_code == 2, result.output
        assert json.loads(out.read_text())["verdict"] == "unknown"

    def test_the_module_names_no_declared_path(self) -> None:
        """The paths live in the declaration; a copy in code is how the two drift."""
        source = (REPO_ROOT / "toolkit/features/deploy_shape.py").read_text(encoding="utf-8")
        for path in (VALUES, OVERLAY, "values/staging", "overlays/staging"):
            assert path not in source, f"{path} is hardcoded in deploy_shape.py"


# --------------------------------------------------------------------------- #
# evaluate(): the PR read through the API, provenance, and the verified sha
# --------------------------------------------------------------------------- #

REPO = "mlorentedev/kubelab"
HEAD = "a" * 40
BASE = "b" * 40
FULL = SHORT + "c" * 33


class FakeApi:
    def __init__(self, routes: dict[str, Any], heads: list[str] | None = None) -> None:
        self.routes = routes
        self.heads = list(heads or [HEAD])

    def json(self, path: str) -> Any:
        if path == f"repos/{REPO}/pulls/7":
            head = self.heads.pop(0) if len(self.heads) > 1 else self.heads[0]
            return {"state": "open", "head": {"sha": head}, "base": {"ref": "master", "repo": {"default_branch": "master"}}}
        if path not in self.routes:
            raise RuntimeError(f"unexpected API call: {path}")
        value = self.routes[path]
        if isinstance(value, Exception):
            raise value
        return value

    def raw(self, path: str) -> str:
        return self.json(path)


def routes_for(app: str, product_repo: str, compare: str = "behind") -> dict[str, Any]:
    before, after = bump(app, NEW)
    r: dict[str, Any] = {
        f"repos/{REPO}/pulls/7/files?per_page=100": changes(VALUES, OVERLAY),
        f"repos/{REPO}/compare/master...{HEAD}": {"merge_base_commit": {"sha": BASE}},
        f"repos/{product_repo}/commits/{SHORT}": {"sha": FULL},
        f"repos/{product_repo}": {"default_branch": "master"},
        f"repos/{product_repo}/compare/master...{FULL}": {"status": compare},
    }
    for path in (VALUES, OVERLAY):
        r[f"repos/{REPO}/contents/{path}?ref={BASE}"] = before[path]
        r[f"repos/{REPO}/contents/{path}?ref={HEAD}"] = after[path]
    return r


@pytest.fixture(scope="module")
def products():
    return load_products(REPO_ROOT / "infra/config/products.yaml").products


class TestEvaluate:
    def test_a_generic_product_bump_is_mechanical_at_the_verified_sha(self, decl, products) -> None:
        shape = evaluate(7, REPO, FakeApi(routes_for("web", "mlorentedev/web")), decl, products)
        assert shape.verdict == "mechanical", shape.reason
        assert shape.head_sha == HEAD

    def test_an_in_tree_product_is_proven_against_this_repository(self, decl, products) -> None:
        shape = evaluate(7, REPO, FakeApi(routes_for("api", REPO)), decl, products)
        assert shape.verdict == "mechanical", shape.reason

    @pytest.mark.parametrize("status", ["ahead", "diverged"])
    def test_a_commit_the_product_never_merged_is_refused(self, decl, products, status: str) -> None:
        shape = evaluate(7, REPO, FakeApi(routes_for("web", "mlorentedev/web", status)), decl, products)
        assert shape.verdict == "not-mechanical"

    def test_a_tag_resolving_to_another_commit_is_refused(self, decl, products) -> None:
        routes = routes_for("web", "mlorentedev/web")
        routes[f"repos/mlorentedev/web/commits/{SHORT}"] = {"sha": "f" * 40}
        assert evaluate(7, REPO, FakeApi(routes), decl, products).verdict == "not-mechanical"

    def test_an_api_failure_is_unknown(self, decl, products) -> None:
        routes = routes_for("web", "mlorentedev/web")
        routes[f"repos/mlorentedev/web/commits/{SHORT}"] = RuntimeError("HTTP 502")
        assert evaluate(7, REPO, FakeApi(routes), decl, products).verdict == "unknown"

    def test_a_head_that_moved_while_reading_is_unknown(self, decl, products) -> None:
        """The verdict names one sha; a push mid-read means it names none."""
        api = FakeApi(routes_for("web", "mlorentedev/web"), heads=[HEAD, "d" * 40])
        assert evaluate(7, REPO, api, decl, products).verdict == "unknown"

    def test_a_file_set_mismatch_reads_no_content(self, decl, products) -> None:
        """Human PRs are the common case: they cost one API call, not six."""
        routes = {f"repos/{REPO}/pulls/7/files?per_page=100": changes("README.md")}
        assert evaluate(7, REPO, FakeApi(routes), decl, products).verdict == "not-mechanical"


class TestRequiredContext:
    """AC3 (a): branch protection requires the published check by its exact name.

    A required context is matched by name, so the declaration and the name the
    workflow publishes must be the same string, or no PR on master ever merges.
    """

    WORKFLOW = REPO_ROOT / ".github/workflows/deploy-shape.yml"

    def test_the_published_check_run_name_is_required_on_master(self) -> None:
        config = yaml.safe_load((REPO_ROOT / "infra/config/values/common.yaml").read_text(encoding="utf-8"))
        required = config["ci"]["branch_protection"]["mlorentedev/kubelab"]["master"]["required_contexts"]
        published = re.findall(r'-f name="([^"]+)"', self.WORKFLOW.read_text(encoding="utf-8"))
        assert published == ["deploy-shape"], f"the workflow publishes {published}, expected one check-run"
        assert published[0] in required, (
            "deploy-shape is not a required context on master: without it a not-mechanical "
            "verdict is advisory and an unknown one blocks nothing (DELIVERY-004 AC3)"
        )

    def test_the_check_runs_on_every_pull_request_to_master(self) -> None:
        """A required context that is never created blocks every merge, forever.

        So the workflow must trigger on every PR to master: no paths filter, and
        every event that gives a PR a new head.
        """
        workflow = yaml.safe_load(self.WORKFLOW.read_text(encoding="utf-8"))
        # PyYAML reads the bare key `on` as the boolean True.
        trigger = (workflow.get("on") or workflow.get(True))["pull_request"]
        assert trigger.get("branches") == ["master"], f"pull_request branches: {trigger.get('branches')}"
        assert not {"paths", "paths-ignore", "branches-ignore"} & set(trigger), (
            f"deploy-shape is a required context; a filter in {sorted(trigger)} leaves some PRs "
            "with no check-run and so unmergeable"
        )
        assert {"opened", "synchronize", "reopened"} <= set(trigger.get("types") or [])

    def test_the_job_name_is_not_what_is_required(self) -> None:
        """The job fails only on `unknown`; the check-run carries all three verdicts."""
        config = yaml.safe_load((REPO_ROOT / "infra/config/values/common.yaml").read_text(encoding="utf-8"))
        required = config["ci"]["branch_protection"]["mlorentedev/kubelab"]["master"]["required_contexts"]
        jobs = yaml.safe_load(self.WORKFLOW.read_text(encoding="utf-8"))["jobs"]
        job_names = {job.get("name") or job_id for job_id, job in jobs.items()}
        assert job_names, "deploy-shape.yml declares no job; this test lost its subject"
        assert not job_names & set(required), f"a job name is required: {sorted(job_names & set(required))}"
