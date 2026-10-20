"""The generic product receiver: the registry decides, the payload carries only a tag (IDP-042 PR 6).

`product-image-receiver.yml` replaces one receiver per product. A product's CI
publishes `sha-<short>` and fires a `repository_dispatch`; the event type, mapped
by `infra/config/products.yaml`, says which app it is, and the registry says which
repository its contract (`kubelab.yaml`) is fetched from. Nothing in the payload
or the contract can change either.

These tests EXECUTE the shipped steps with `gh` and the toolkit stubbed. The
workflow runs only on a dispatch from another repository, so CI cannot exercise it
on the branch that changes it. The toolkit stub answers what the real CLI answers
for the fixture registry, computed in-process, so the stub cannot drift from the
CLI's shape. The fetch step runs the real `toolkit product validate`.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest
import yaml
from typer.testing import CliRunner

from toolkit.features import product_registry, promotion
from toolkit.main import app as toolkit_app

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
RECEIVER = REPO_ROOT / ".github/workflows/product-image-receiver.yml"
FIXTURE_REGISTRY = REPO_ROOT / "tests/fixtures/product/registry.yaml"
WEB_CONTRACT = REPO_ROOT / "tests/fixtures/product/web.kubelab.yaml"

SHORT = "b9874f2"
FULL = "b9874f2f693dd41ee4e1985cb88b0645ac59f996"

_needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="the steps are bash scripts")
_needs_jq = pytest.mark.skipif(shutil.which("jq") is None, reason="the resolve step parses the toolkit's JSON with jq")


def _workflow() -> dict:
    return yaml.safe_load(RECEIVER.read_text(encoding="utf-8"))


def _triggers() -> dict:
    workflow = _workflow()
    # PyYAML reads the bare key `on` as the boolean True.
    return workflow.get("on", workflow.get(True))


def _steps(job: str) -> list[dict]:
    return _workflow()["jobs"][job]["steps"]


def _step(job: str, step_id: str) -> dict:
    """A step by its `id:`; a rename makes these tests error instead of skip their subject."""
    return next(s for s in _steps(job) if s.get("id") == step_id)


# --- the triggers and the shape -----------------------------------------------


def test_every_dispatch_reaches_the_registry() -> None:
    """Q5: no `types` list, so the registry decides and a new product needs no workflow edit."""
    assert _triggers()["repository_dispatch"] in (None, {}), "a `types` list makes the workflow decide, not the registry"
    assert set(_triggers()["workflow_dispatch"]["inputs"]) == {"app", "tag", "dry_run"}


def test_only_the_job_that_writes_is_serialised_and_per_app() -> None:
    """A manual run and a dispatch of one app must share a group: both force-push its branch.

    The group is per app, which only a job after the resolve can know. A group on
    `github.event.action` is empty on `workflow_dispatch`, so a manual re-promote
    and a dispatch of the same app would race `deploy/staging-<app>`.
    """
    jobs = _workflow()["jobs"]
    assert "concurrency" not in _workflow(), "a workflow-level group would serialise every product behind one another"
    assert "concurrency" not in jobs["resolve"]
    assert jobs["promote"]["needs"] == "resolve"
    assert jobs["promote"]["concurrency"] == {
        "group": "product-receiver-${{ needs.resolve.outputs.app }}",
        "cancel-in-progress": False,
    }


def test_the_resolve_job_cannot_write() -> None:
    """AC7's "before any file is written" holds by construction: the job that decides holds no write grant."""
    jobs = _workflow()["jobs"]
    assert _workflow()["permissions"] == {"contents": "read"}
    assert "permissions" not in jobs["resolve"]
    assert jobs["promote"]["permissions"] == {"contents": "write", "pull-requests": "write"}


def test_no_step_interpolates_the_payload_into_its_shell() -> None:
    """`${{ }}` inside `run:` is textual substitution before bash sees the script."""
    for job in _workflow()["jobs"]:
        for step in _steps(job):
            assert "${{" not in str(step.get("run", "")), (
                f"step {step.get('name')!r} interpolates an expression into its script; pass it through `env:`"
            )


def test_the_app_is_never_taken_from_the_payload() -> None:
    """AC1: the event type says which app it is; a payload `app` would let the sender choose."""
    text = RECEIVER.read_text(encoding="utf-8")
    assert "client_payload.app" not in text
    payload_reads = set(re.findall(r"client_payload\.(\w+)", text))
    assert payload_reads == {"tag"}, f"the payload surface is exactly one field, read: {payload_reads}"


def test_the_tag_guard_is_the_shape_the_promotion_accepts() -> None:
    guard = re.search(r"=~ (\S+) \]\]", _step("resolve", "target")["run"])
    assert guard, "the resolve step no longer checks the tag with [[ =~ ]]"
    assert guard.group(1) == promotion._SHA_TAG.pattern


def test_the_branch_is_keyed_on_the_app() -> None:
    body = _step("promote", "open-pr")["run"]
    assert 'BRANCH="deploy/staging-${APP}"' in body
    assert "${TAG}" not in body.split('BRANCH="', 1)[1].split('"', 1)[0], "a branch per tag is #1645"


# --- the resolve step, executed -------------------------------------------------

_GH_STUB = """#!/usr/bin/env bash
echo "$*" >> "$GH_CALLS"
case "$*" in
  *"/commits/"*)
      if [ -n "${STUB_COMMIT_ERROR:-}" ]; then
        echo "gh: ${STUB_COMMIT_ERROR} (HTTP 422)" >&2; exit 1
      fi
      printf '%s\\n' "$STUB_SHA" ;;
  *"/compare/"*) printf '%s\\n' "$STUB_COMPARE" ;;
  *"--jq .default_branch"*) printf '%s\\n' "$STUB_DEFAULT" ;;
  *"/contents/kubelab.yaml"*)
      if [ -z "${STUB_CONTRACT:-}" ]; then echo "gh: Not Found (HTTP 404)" >&2; exit 1; fi
      cat "$STUB_CONTRACT" ;;
  *) echo "unexpected gh call: $*" >&2; exit 1 ;;
esac
"""

_TOOLKIT_QUESTIONS = [
    ["product", "app-for-event", event, "--json"]
    for event in ("web-image-published", "web-release-published", "third-image-published", "ghost-image-published")
] + [["product", "show", name, "--json"] for name in ("api", "web", "third", "ghost")]


@pytest.fixture
def toolkit_stub(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A toolkit that answers exactly what the real CLI answers for the fixture registry."""
    monkeypatch.setattr(product_registry, "registry_path", lambda: FIXTURE_REGISTRY)
    answers = {}
    for argv in _TOOLKIT_QUESTIONS:
        result = CliRunner().invoke(toolkit_app, argv)
        answers[" ".join(argv)] = {"stdout": result.stdout, "code": result.exit_code}
    table = tmp_path / "toolkit-answers.json"
    table.write_text(json.dumps(answers))
    stub = tmp_path / "toolkit-stub"
    stub.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        f"answer = json.load(open({str(table)!r})).get(' '.join(sys.argv[1:]))\n"
        "if answer is None:\n"
        "    sys.exit(f'unexpected toolkit call: {sys.argv[1:]}')\n"
        "sys.stdout.write(answer['stdout'])\n"
        "sys.exit(answer['code'])\n"
    )
    stub.chmod(0o755)
    return str(stub)


def _run(
    tmp_path: pathlib.Path, job: str, step_id: str, cwd: pathlib.Path | None = None, **env_overrides: str
) -> tuple[int, dict[str, str], str, list[str]]:
    """Run one step as the job would; return its exit code, outputs, log and `gh` calls.

    Every variable the step declares is seeded empty first, because that is what
    GitHub renders for a context key the event does not carry.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "gh").write_text(_GH_STUB)
    (bindir / "gh").chmod(0o755)
    calls = tmp_path / "gh_calls"
    calls.touch()
    output = tmp_path / "github_output"
    output.touch()
    work = cwd or tmp_path / "work"
    work.mkdir(exist_ok=True)
    step = _step(job, step_id)
    env = {
        "PATH": os.pathsep.join([str(bindir), str(pathlib.Path(sys.executable).parent), os.environ["PATH"]]),
        "GITHUB_OUTPUT": str(output),
        "RUNNER_TEMP": str(tmp_path / "runner-temp"),
        "GH_CALLS": str(calls),
        **{key: "" for key in (step.get("env") or {})},
        "STUB_SHA": FULL,
        "STUB_DEFAULT": "master",
        "STUB_COMPARE": "identical",
        **env_overrides,
    }
    (tmp_path / "runner-temp").mkdir(exist_ok=True)
    proc = subprocess.run(  # noqa: S603
        ["bash", "-e", "-c", step["run"]], cwd=work, env=env, capture_output=True, text=True, timeout=60
    )
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines() if "=" in line)
    return proc.returncode, outputs, proc.stdout + proc.stderr, calls.read_text().splitlines()


def _dispatch(tmp_path: pathlib.Path, toolkit: str, event: str = "third-image-published", **env: str):
    return _run(
        tmp_path,
        "resolve",
        "target",
        **{"EVENT": "repository_dispatch", "EVENT_TYPE": event, "PAYLOAD_TAG": f"sha-{SHORT}", "TOOLKIT": toolkit, **env},
    )


def _manual(tmp_path: pathlib.Path, toolkit: str, app: str, dry_run: str = "false", **env: str):
    return _run(
        tmp_path,
        "resolve",
        "target",
        EVENT="workflow_dispatch",
        INPUT_APP=app,
        INPUT_TAG=f"sha-{SHORT}",
        INPUT_DRY_RUN=dry_run,
        TOOLKIT=toolkit,
        **env,
    )


@_needs_bash
@_needs_jq
def test_a_dispatch_resolves_the_app_its_repository_and_the_commit(tmp_path: pathlib.Path, toolkit_stub: str) -> None:
    code, out, log, calls = _dispatch(tmp_path, toolkit_stub)

    assert code == 0, log
    assert out == {
        "skip": "false",
        "app": "third",
        "repository": "mlorentedev/third",
        "tag": f"sha-{SHORT}",
        "sha": FULL,
        "dry_run": "false",
    }
    assert calls and all(" repos/mlorentedev/third" in call for call in calls), calls
    assert os.listdir(tmp_path / "work") == [], "the resolve step wrote a file"


@_needs_bash
@_needs_jq
def test_an_unmapped_event_fails_with_error_why_fix(tmp_path: pathlib.Path, toolkit_stub: str) -> None:
    code, out, log, calls = _dispatch(tmp_path, toolkit_stub, event="ghost-image-published")

    assert code != 0
    assert [line.split(":", 1)[0] for line in log.splitlines() if line[:5] in ("ERROR", "WHY: ", "FIX: ")] == [
        "ERROR",
        "WHY",
        "FIX",
    ], log
    assert "ghost-image-published" in log
    assert out == {} and calls == []


@_needs_bash
@_needs_jq
def test_a_prod_lane_event_is_not_this_lane(tmp_path: pathlib.Path, toolkit_stub: str) -> None:
    code, out, log, calls = _dispatch(tmp_path, toolkit_stub, event="web-release-published")

    assert code == 0, log
    assert out == {"skip": "true"}
    assert "not this lane" in log and calls == []


@_needs_bash
@_needs_jq
def test_a_legacy_product_dispatch_is_left_to_its_own_receiver(tmp_path: pathlib.Path, toolkit_stub: str) -> None:
    """Design point 10: while web is `receiver: legacy`, only the old workflow acts on its event."""
    code, out, log, calls = _dispatch(tmp_path, toolkit_stub, event="web-image-published")

    assert code == 0, log
    assert out == {"skip": "true"}
    assert "legacy" in log and calls == []


@_needs_bash
@_needs_jq
def test_a_manual_dry_run_of_a_legacy_product_proceeds(tmp_path: pathlib.Path, toolkit_stub: str) -> None:
    """The cutover's rehearsal: validate and render web while its old receiver still owns the branch."""
    code, out, log, _ = _manual(tmp_path, toolkit_stub, "web", dry_run="true")

    assert code == 0, log
    assert out["app"] == "web" and out["repository"] == "mlorentedev/web" and out["dry_run"] == "true"


def test_a_manual_run_is_a_dry_run_unless_told_otherwise() -> None:
    """A manual run that omits the box, or sends anything but `false`, writes nothing."""
    assert _triggers()["workflow_dispatch"]["inputs"]["dry_run"]["default"] is True


@_needs_bash
@_needs_jq
@pytest.mark.parametrize("value", ["", "True", "no"])
def test_only_an_explicit_false_leaves_dry_run(tmp_path: pathlib.Path, toolkit_stub: str, value: str) -> None:
    code, out, log, _ = _manual(tmp_path, toolkit_stub, "third", dry_run=value)

    assert code == 0, log
    assert out["dry_run"] == "true"


@_needs_bash
@_needs_jq
def test_a_manual_run_that_would_write_a_legacy_product_is_refused(tmp_path: pathlib.Path, toolkit_stub: str) -> None:
    code, out, log, calls = _manual(tmp_path, toolkit_stub, "web")

    assert code != 0
    assert "ERROR: " in log and "dry_run" in log
    assert out == {} and calls == []


@_needs_bash
@_needs_jq
@pytest.mark.parametrize("app", ["ghost", "api"], ids=["unregistered", "in-tree"])
def test_a_manual_run_of_no_receivable_product_is_refused(tmp_path: pathlib.Path, toolkit_stub: str, app: str) -> None:
    code, out, log, calls = _manual(tmp_path, toolkit_stub, app, dry_run="true")

    assert code != 0
    assert "ERROR: " in log and "FIX: " in log
    assert out == {} and calls == []


@_needs_bash
@_needs_jq
@pytest.mark.parametrize(
    "tag",
    ["sha-", "sha-abc12", "sha-../x", "sha-ABCDEF1", f"sha-{SHORT}\nsha-bbb2222", f"sha-{SHORT} x", "v1.2.3", ""],
    ids=["empty-hex", "short", "path", "uppercase", "newline", "space", "semver", "absent"],
)
def test_a_tag_that_is_not_an_immutable_sha_is_refused_before_any_call(
    tmp_path: pathlib.Path, toolkit_stub: str, tag: str
) -> None:
    code, out, log, calls = _dispatch(tmp_path, toolkit_stub, PAYLOAD_TAG=tag)

    assert code != 0
    assert out == {} and calls == [], f"a refused tag reached the API: {calls}"


@_needs_bash
@_needs_jq
@pytest.mark.parametrize(
    "scenario",
    [
        {"STUB_COMMIT_ERROR": f"No commit found for SHA: {SHORT}"},
        {"STUB_SHA": "0" * 40},
        {"STUB_SHA": SHORT},
        {"STUB_COMPARE": "ahead"},
        {"STUB_COMPARE": "diverged"},
    ],
    ids=["unknown-or-ambiguous", "another-commit", "not-a-full-sha", "branch-only", "diverged"],
)
def test_a_commit_that_is_not_one_commit_on_the_default_branch_is_refused(
    tmp_path: pathlib.Path, toolkit_stub: str, scenario: dict[str, str]
) -> None:
    """AC7, as the spike measured the API: 422 for unknown and ambiguous alike, `ahead` off the branch."""
    code, out, log, _ = _dispatch(tmp_path, toolkit_stub, **scenario)

    assert code != 0
    assert "ERROR: " in log, log
    assert out == {}


@_needs_bash
@_needs_jq
def test_a_commit_master_has_moved_past_is_accepted(tmp_path: pathlib.Path, toolkit_stub: str) -> None:
    code, out, log, calls = _dispatch(tmp_path, toolkit_stub, STUB_COMPARE="behind", STUB_DEFAULT="trunk")

    assert code == 0, log
    assert any("compare/trunk..." in call for call in calls), "the default branch is read from the API, not assumed"


# --- the fetch step, executed with the real validator ----------------------------


def _fetch(tmp_path: pathlib.Path, body: str | None) -> tuple[int, str, list[str], pathlib.Path]:
    work = tmp_path / "work"
    (work / "infra/config/products/contracts").mkdir(parents=True)
    (work / "infra/config").joinpath("products.yaml").write_text(
        (REPO_ROOT / "infra/config/products.yaml").read_text()
    )
    scenario = {}
    if body is not None:
        (tmp_path / "served.yaml").write_text(body)
        scenario["STUB_CONTRACT"] = str(tmp_path / "served.yaml")
    code, _, log, calls = _run(
        tmp_path,
        "promote",
        "contract",
        cwd=work,
        APP="web",
        REPOSITORY="mlorentedev/web",
        SHA=FULL,
        TOOLKIT=f"{sys.executable} -m toolkit.main",
        **scenario,
    )
    return code, log, calls, work / "infra/config/products/contracts/web.yaml"


@_needs_bash
def test_a_valid_contract_is_snapshotted_verbatim(tmp_path: pathlib.Path) -> None:
    """Design point 9: the reviewer sees the contract diff in the staging PR, byte for byte."""
    body = WEB_CONTRACT.read_text()
    code, log, calls, snapshot = _fetch(tmp_path, body)

    assert code == 0, log
    assert snapshot.read_bytes() == body.encode()
    assert calls == [f"api -H Accept: application/vnd.github.raw repos/mlorentedev/web/contents/kubelab.yaml?ref={FULL}"]


@_needs_bash
def test_an_invalid_contract_fails_with_error_why_fix_and_writes_nothing(tmp_path: pathlib.Path) -> None:
    """AC2: the three labelled lines reach the run page, and no snapshot is left to commit."""
    code, log, _, snapshot = _fetch(tmp_path, WEB_CONTRACT.read_text().replace("port: 8080", "port: 0"))

    assert code != 0
    assert all(f"{label}: " in log for label in ("ERROR", "WHY", "FIX")), log
    assert not snapshot.exists()


@_needs_bash
def test_a_contract_that_names_another_repository_changes_no_fetch(tmp_path: pathlib.Path) -> None:
    """AC6: the registry names where the contract comes from; the contract cannot redirect it."""
    code, log, calls, snapshot = _fetch(tmp_path, WEB_CONTRACT.read_text() + "repository: evil/fork\n")

    assert code != 0, log
    assert all("repos/mlorentedev/web/" in call for call in calls), calls
    assert not snapshot.exists()


@_needs_bash
def test_a_product_without_a_contract_at_the_commit_fails(tmp_path: pathlib.Path) -> None:
    code, log, _, snapshot = _fetch(tmp_path, None)

    assert code != 0
    assert "kubelab.yaml" in log and "ERROR: " in log
    assert not snapshot.exists()
