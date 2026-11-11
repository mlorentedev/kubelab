"""The receiver's decisions as toolkit commands (IDP-053 AC9).

`product-image-receiver.yml` decides, in inline shell, which app a dispatch means, whether
this run may act, which commit the tag names and where its contract is read. The workflow
asks the toolkit for each of those now, so each is observable here: `gh` is replaced by a
scripted runner that logs every call, and a test that says "nothing was asked" asserts the
log is empty rather than trusting the code's say-so.
"""

from __future__ import annotations

import json
import pathlib
import subprocess

import pytest
from typer.testing import CliRunner

from toolkit.cli.product import app
from toolkit.features import forge_adapter, product_registry

FULL = "b9874f2f693dd41ee4e1985cb88b0645ac59f996"
SHORT = FULL[:7]
TAG = f"sha-{SHORT}"
CONTRACT = "schema_version: 1\nname: web\n"

REGISTRY = """\
products:
  api:
    forge: in-tree
  web:
    forge: github
    repository: acme/web
    receiver: generic
    events: {staging: web-image-published, prod: web-release-published}
  oldie:
    forge: github
    repository: acme/oldie
    receiver: legacy
    events: {staging: oldie-image-published, prod: oldie-release-published}
  gadget:
    forge: gitea
    repository: acme/gadget
    receiver: generic
    events: {staging: gadget-image-published}
"""


class FakeRunner:
    """Answers each `gh` call from a script keyed by a substring of its argv, and logs it."""

    def __init__(self) -> None:
        self.answers: dict[str, tuple[int, str, str]] = {
            "/commits/": (0, FULL, ""),
            "/compare/": (0, "behind", ""),
            "/contents/": (0, CONTRACT, ""),
            "repos/acme/web": (0, "master", ""),
            "repos/acme/oldie": (0, "master", ""),
        }
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        for needle, (code, out, err) in self.answers.items():
            if any(needle in arg for arg in args):
                return subprocess.CompletedProcess(list(args), code, out, err)
        raise AssertionError(f"unscripted gh call: {args}")


@pytest.fixture
def gh(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> FakeRunner:
    """A registry of four products, and a `gh` every call of which is observed."""
    registry = tmp_path / "products.yaml"
    registry.write_text(REGISTRY, encoding="utf-8")
    monkeypatch.setattr(product_registry, "registry_path", lambda: registry)
    runner = FakeRunner()
    monkeypatch.setattr(forge_adapter, "run_gh", runner)
    return runner


def _run(*argv: str) -> tuple[int, dict]:
    result = CliRunner().invoke(app, [*argv, "--json"])
    return result.exit_code, json.loads(result.stdout)


def _receive(*argv: str) -> tuple[int, dict]:
    return _run("resolve", *argv)


DISPATCH = ("--event", "repository_dispatch", "--event-type", "web-image-published", "--tag", TAG)
MANUAL = ("--event", "workflow_dispatch", "--app", "web", "--tag", TAG)
WRITE = (*MANUAL, "--dry-run", "false", "--ref", "refs/heads/master", "--default-branch", "master")


# `product resolve --event`: the workflow's resolve step, decision for decision.


def test_a_dispatch_resolves_to_the_six_outputs_the_workflow_builds_and_asks_github_what_it_asked(
    gh: FakeRunner,
) -> None:
    code, answer = _receive(*DISPATCH)

    assert code == 0, answer
    assert answer == {
        "skip": False,
        "app": "web",
        "repository": "acme/web",
        "tag": TAG,
        "sha": FULL,
        "dry_run": False,
    }
    assert gh.calls == [
        ("api", f"repos/acme/web/commits/{SHORT}", "--jq", ".sha"),
        ("api", "repos/acme/web", "--jq", ".default_branch"),
        ("api", f"repos/acme/web/compare/master...{FULL}", "--jq", ".status"),
    ]


def test_a_prod_lane_event_is_skipped_before_the_forge_is_asked(gh: FakeRunner) -> None:
    code, answer = _receive("--event", "repository_dispatch", "--event-type", "web-release-published", "--tag", "v1")

    assert code == 0 and answer["skip"] is True and "prod lane" in answer["reason"]
    assert gh.calls == []


def test_an_event_type_no_product_claims_is_refused(gh: FakeRunner) -> None:
    code, answer = _receive("--event", "repository_dispatch", "--event-type", "ghost-image-published", "--tag", TAG)

    assert code == 1 and answer["ok"] is False and "ghost-image-published" in answer["error"]
    assert answer["why"] and answer["fix"]
    assert gh.calls == []


def test_a_legacy_products_dispatch_is_skipped_before_its_tag_is_read_or_the_forge_asked(gh: FakeRunner) -> None:
    code, answer = _receive(
        "--event", "repository_dispatch", "--event-type", "oldie-image-published", "--tag", "latest"
    )

    assert code == 0 and answer["skip"] is True and "legacy" in answer["reason"]
    assert gh.calls == []


def test_a_manual_run_is_a_dry_run_unless_it_says_otherwise(gh: FakeRunner) -> None:
    code, answer = _receive(*MANUAL)

    assert code == 0 and answer["dry_run"] is True and answer["skip"] is False


@pytest.mark.parametrize("value", ["true", "", "False", "0", "no"])
def test_only_the_word_false_makes_a_manual_run_a_write_run(gh: FakeRunner, value: str) -> None:
    code, answer = _receive(*MANUAL, "--dry-run", value, "--ref", "refs/heads/master", "--default-branch", "master")

    assert code == 0 and answer["dry_run"] is True


def test_a_manual_write_run_from_the_default_branch_proceeds(gh: FakeRunner) -> None:
    code, answer = _receive(*WRITE)

    assert code == 0 and answer["dry_run"] is False


@pytest.mark.parametrize(
    "ref",
    ["refs/heads/feature", "refs/tags/master", "refs/heads/master-2", ""],
    ids=["branch", "tag", "prefix", "none"],
)
def test_a_manual_write_run_from_any_other_ref_is_refused_before_the_forge_is_asked(gh: FakeRunner, ref: str) -> None:
    code, answer = _receive(*MANUAL, "--dry-run", "false", "--ref", ref, "--default-branch", "master")

    assert code == 1 and "must start from master" in answer["error"]
    assert answer["why"] and answer["fix"]
    assert gh.calls == []


def test_a_manual_dry_run_may_start_from_any_ref(gh: FakeRunner) -> None:
    code, answer = _receive(*MANUAL, "--ref", "refs/heads/feature", "--default-branch", "master")

    assert code == 0 and answer["dry_run"] is True


def test_a_manual_run_of_a_legacy_product_may_only_be_a_dry_run(gh: FakeRunner) -> None:
    legacy = ("--event", "workflow_dispatch", "--app", "oldie", "--tag", TAG)

    dry_code, dry = _receive(*legacy)
    code, refused = _receive(*legacy, "--dry-run", "false", "--ref", "refs/heads/master", "--default-branch", "master")

    assert dry_code == 0 and dry["dry_run"] is True and dry["skip"] is False
    assert code == 1 and "legacy" in refused["error"] and refused["why"] and refused["fix"]


def test_an_unexpected_trigger_is_refused(gh: FakeRunner) -> None:
    code, answer = _receive("--event", "push", "--tag", TAG)

    assert code == 1 and "push" in answer["error"] and answer["why"] and answer["fix"]
    assert gh.calls == []


@pytest.mark.parametrize("name", ["api", "ghost", "gadget"], ids=["in-tree", "unregistered", "no-adapter-yet"])
def test_a_product_with_no_repository_the_toolkit_can_read_is_refused_before_the_forge_is_asked(
    gh: FakeRunner, name: str
) -> None:
    code, answer = _receive("--event", "workflow_dispatch", "--app", name, "--tag", TAG)

    assert code == 1 and answer["ok"] is False and answer["why"] and answer["fix"]
    assert gh.calls == []


@pytest.mark.parametrize("tag", ["latest", "sha-abc12", "sha-ABCDEF1", "", "sha-b9874f2; rm -rf /", f"{TAG}\n"])
def test_a_tag_that_is_not_an_immutable_sha_tag_is_refused_before_the_forge_is_asked(gh: FakeRunner, tag: str) -> None:
    code, answer = _receive("--event", "repository_dispatch", "--event-type", "web-image-published", "--tag", tag)

    assert code == 1 and "unexpected tag" in answer["error"]
    assert gh.calls == []


def test_a_commit_the_product_never_merged_is_refused_naming_its_repository(gh: FakeRunner) -> None:
    gh.answers["/compare/"] = (0, "ahead", "")

    code, answer = _receive(*DISPATCH)

    assert code == 1 and FULL in answer["error"] and "acme/web" in answer["error"]
    assert answer["why"] and answer["fix"]


def test_a_tag_that_resolves_to_no_commit_is_refused_with_what_the_forge_said(gh: FakeRunner) -> None:
    gh.answers["/commits/"] = (1, "", "No commit found for SHA (HTTP 422)")

    code, answer = _receive(*DISPATCH)

    assert code == 1 and "does not resolve" in answer["error"] and "HTTP 422" in answer["why"]


def test_the_text_form_prints_each_output_on_its_own_line_for_the_workflow_to_append(gh: FakeRunner) -> None:
    result = CliRunner().invoke(app, ["resolve", *DISPATCH])

    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        "skip=false",
        "app=web",
        "repository=acme/web",
        f"tag={TAG}",
        f"sha={FULL}",
        "dry_run=false",
    ]


def test_without_an_event_resolve_keeps_the_form_it_had(gh: FakeRunner) -> None:
    code, answer = _run("resolve", "--app", "web", "--tag", TAG)

    assert code == 0
    assert answer == {
        "ok": True,
        "app": "web",
        "repository": "acme/web",
        "tag": TAG,
        "sha": FULL,
        "on_default_branch": True,
    }


@pytest.mark.parametrize("missing", [("--app", "web"), ("--tag", TAG)], ids=["no-tag", "no-app"])
def test_without_an_event_resolve_needs_both_an_app_and_a_tag(gh: FakeRunner, missing: tuple[str, str]) -> None:
    result = CliRunner().invoke(app, ["resolve", *missing])

    assert result.exit_code != 0
    assert gh.calls == []


# `product fetch-contract`: read kubelab.yaml at the commit through the adapter.


def test_fetch_contract_writes_the_bytes_the_forge_holds_at_the_commit(gh: FakeRunner, tmp_path: pathlib.Path) -> None:
    out = tmp_path / "fetched.yaml"

    code, answer = _run("fetch-contract", "--app", "web", "--sha", FULL, "--out", str(out))

    assert code == 0, answer
    assert out.read_text(encoding="utf-8") == CONTRACT
    assert answer == {"ok": True, "app": "web", "repository": "acme/web", "sha": FULL, "contract": str(out)}
    assert gh.calls == [
        ("api", "-H", "Accept: application/vnd.github.raw", f"repos/acme/web/contents/kubelab.yaml?ref={FULL}")
    ]


def test_fetch_contract_leaves_nothing_behind_when_the_forge_has_no_contract(
    gh: FakeRunner, tmp_path: pathlib.Path
) -> None:
    gh.answers["/contents/"] = (1, "", "gh: Not Found (HTTP 404)")
    out = tmp_path / "fetched.yaml"

    code, answer = _run("fetch-contract", "--app", "web", "--sha", FULL, "--out", str(out))

    assert code == 1 and "acme/web has no readable kubelab.yaml" in answer["error"] and FULL in answer["error"]
    assert "ADR-067" in answer["why"] and answer["fix"]
    assert not out.exists()


@pytest.mark.parametrize("sha", [SHORT, "HEAD", f"{FULL}/../x", FULL.upper()], ids=["short", "ref", "path", "upper"])
def test_fetch_contract_takes_only_a_full_commit_sha_and_asks_nothing_otherwise(
    gh: FakeRunner, tmp_path: pathlib.Path, sha: str
) -> None:
    out = tmp_path / "fetched.yaml"

    code, answer = _run("fetch-contract", "--app", "web", "--sha", sha, "--out", str(out))

    assert code == 1 and "full commit sha" in answer["error"]
    assert gh.calls == [] and not out.exists()


@pytest.mark.parametrize("name", ["api", "ghost"])
def test_fetch_contract_asks_nothing_for_a_product_with_no_repository_to_read(
    gh: FakeRunner, tmp_path: pathlib.Path, name: str
) -> None:
    code, answer = _run("fetch-contract", "--app", name, "--sha", FULL, "--out", str(tmp_path / "x.yaml"))

    assert code == 1 and answer["ok"] is False
    assert gh.calls == []


def test_fetch_contract_text_form_names_what_it_wrote(gh: FakeRunner, tmp_path: pathlib.Path) -> None:
    out = tmp_path / "fetched.yaml"

    result = CliRunner().invoke(app, ["fetch-contract", "--app", "web", "--sha", FULL, "--out", str(out)])

    assert result.exit_code == 0 and f"{out}" in result.stdout and "acme/web" in result.stdout


# `product route`: which runner a product's forge reads need, from the registry alone.


def test_route_gives_a_github_product_the_hosted_default_without_asking_any_forge(gh: FakeRunner) -> None:
    code, answer = _run("route", "--app", "web")

    assert code == 0 and answer == {"forge": "github", "runs_on": ["ubuntu-latest"]}
    assert gh.calls == []


def test_route_gives_a_gitea_product_the_self_hosted_runner_that_reaches_it(gh: FakeRunner) -> None:
    code, answer = _run("route", "--app", "gadget")

    assert code == 0 and answer == {"forge": "gitea", "runs_on": ["self-hosted", "linux", "docker"]}
    assert gh.calls == []


@pytest.mark.parametrize(
    ("given", "expected"),
    [('["self-hosted","x"]', ["self-hosted", "x"]), ('"ubuntu-24.04"', ["ubuntu-24.04"]), ("", ["ubuntu-latest"])],
    ids=["list", "string", "unset"],
)
def test_route_lets_a_github_product_keep_the_runner_the_repository_variable_names(
    gh: FakeRunner, given: str, expected: list[str]
) -> None:
    code, answer = _run("route", "--app", "web", "--hosted-runner", given)

    assert code == 0 and answer["runs_on"] == expected


def test_route_never_lets_that_variable_move_a_gitea_product_off_its_self_hosted_runner(gh: FakeRunner) -> None:
    code, answer = _run("route", "--app", "gadget", "--hosted-runner", '["ubuntu-latest"]')

    assert code == 0 and answer["runs_on"] == ["self-hosted", "linux", "docker"]


@pytest.mark.parametrize("given", ["[", "7", "[1]", '[""]', "[]", "{}"])
def test_route_refuses_a_runner_variable_that_is_not_a_runs_on_value(gh: FakeRunner, given: str) -> None:
    code, answer = _run("route", "--app", "web", "--hosted-runner", given)

    assert code == 1 and answer["ok"] is False and "RUNNER_DOCKER" in answer["error"]
    assert answer["why"] and answer["fix"]


@pytest.mark.parametrize("name", ["api", "ghost"], ids=["in-tree", "unregistered"])
def test_route_refuses_a_product_that_receives_no_image(gh: FakeRunner, name: str) -> None:
    code, answer = _run("route", "--app", name)

    assert code == 1 and answer["ok"] is False and answer["why"] and answer["fix"]


def test_route_text_form_prints_each_output_on_its_own_line_for_the_workflow_to_append(gh: FakeRunner) -> None:
    result = CliRunner().invoke(app, ["route", "--app", "gadget"])

    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["forge=gitea", 'runs_on=["self-hosted", "linux", "docker"]']
