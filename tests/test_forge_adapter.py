"""The forge adapter: one interface over where a product's repository lives (IDP-053 AC8).

The receiver, `product ready` and `product release-contract` each used to call `gh api`
by hand and refuse any forge but GitHub by comparing a string. They now ask a
`ForgeAdapter`, and the factory is the only place that knows which forges exist. The
GitHub implementation must make exactly the calls those callers made, so each test
pins the argv the runner receives. The runner is injected: no `gh`, no network.
"""

from __future__ import annotations

import json
import subprocess

import pytest
from typer.testing import CliRunner

from toolkit.cli.product import app
from toolkit.features import forge_adapter, product_registry
from toolkit.features.forge_adapter import ForgeAdapter, ForgeError, GitHubForge, adapter_for
from toolkit.features.product_contract import ContractError

FULL = "b9874f2f693dd41ee4e1985cb88b0645ac59f996"
SHORT = FULL[:7]
REPO = "acme/widget"


class FakeRunner:
    """Answers each call from a script keyed by the first argv entry it contains, and logs it."""

    def __init__(self, answers: dict[str, tuple[int, str, str]]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        for needle, (code, out, err) in self.answers.items():
            if any(needle in arg for arg in args):
                return subprocess.CompletedProcess(list(args), code, out + "\n" if out else "", err)
        raise AssertionError(f"unscripted gh call: {args}")


def _forge(answers: dict[str, tuple[int, str, str]]) -> tuple[GitHubForge, FakeRunner]:
    runner = FakeRunner(answers)
    return GitHubForge(REPO, runner), runner


def test_the_github_implementation_is_a_forge_adapter() -> None:
    assert isinstance(GitHubForge(REPO, FakeRunner({})), ForgeAdapter)


def test_resolve_commit_makes_the_receivers_call_and_returns_the_full_sha() -> None:
    forge, runner = _forge({"/commits/": (0, FULL, "")})

    assert forge.resolve_commit(SHORT) == FULL
    assert runner.calls == [("api", f"repos/{REPO}/commits/{SHORT}", "--jq", ".sha")]


@pytest.mark.parametrize(
    ("answer", "detail"),
    [
        ((1, "", "gh: No commit found for SHA (HTTP 422)"), "HTTP 422"),
        ((0, "0" * 40, ""), "0" * 40),
        ((0, SHORT, ""), SHORT),
    ],
    ids=["unresolvable", "another-commit", "not-a-full-sha"],
)
def test_resolve_commit_refuses_what_is_not_one_commit_starting_with_the_short_sha(
    answer: tuple[int, str, str], detail: str
) -> None:
    forge, _ = _forge({"/commits/": answer})

    with pytest.raises(ForgeError, match=detail):
        forge.resolve_commit(SHORT)


def test_resolve_tag_asks_for_the_commit_a_tag_names() -> None:
    forge, runner = _forge({"/commits/": (0, FULL, "")})

    assert forge.resolve_tag("v1.16.1") == FULL
    assert runner.calls == [("api", f"repos/{REPO}/commits/v1.16.1", "--jq", ".sha")]


@pytest.mark.parametrize(
    "answer", [(1, "", "gh: Not Found (HTTP 404)"), (0, "v1.16.1", "")], ids=["absent", "not-a-sha"]
)
def test_resolve_tag_refuses_a_tag_that_names_no_commit(answer: tuple[int, str, str]) -> None:
    forge, _ = _forge({"/commits/": answer})

    with pytest.raises(ForgeError):
        forge.resolve_tag("v1.16.1")


def test_read_file_asks_for_the_raw_bytes_at_the_ref() -> None:
    forge, runner = _forge({"/contents/": (0, "schema_version: 1", "")})

    assert forge.read_file("kubelab.yaml", FULL).strip() == "schema_version: 1"
    assert runner.calls == [
        ("api", "-H", "Accept: application/vnd.github.raw", f"repos/{REPO}/contents/kubelab.yaml?ref={FULL}")
    ]


def test_read_file_refuses_a_missing_file_with_what_the_forge_said() -> None:
    forge, _ = _forge({"/contents/": (1, "", "gh: Not Found (HTTP 404)")})

    with pytest.raises(ForgeError, match="HTTP 404"):
        forge.read_file("kubelab.yaml", FULL)


@pytest.mark.parametrize(
    ("status", "on_default"), [("identical", True), ("behind", True), ("ahead", False), ("diverged", False)]
)
def test_a_commit_is_on_the_default_branch_when_the_branch_has_it_or_has_moved_past_it(
    status: str, on_default: bool
) -> None:
    forge, runner = _forge({f"repos/{REPO}/compare/": (0, status, ""), f"repos/{REPO}": (0, "trunk", "")})

    assert forge.is_on_default_branch(FULL) is on_default
    assert runner.calls == [
        ("api", f"repos/{REPO}", "--jq", ".default_branch"),
        ("api", f"repos/{REPO}/compare/trunk...{FULL}", "--jq", ".status"),
    ]


def test_an_unreadable_default_branch_is_an_error_not_a_verdict() -> None:
    forge, runner = _forge({f"repos/{REPO}": (1, "", "gh: Bad gateway (HTTP 502)")})

    with pytest.raises(ForgeError, match="HTTP 502"):
        forge.is_on_default_branch(FULL)
    assert len(runner.calls) == 1, "a comparison against an unknown branch was asked"


def test_a_failed_comparison_is_an_error_not_a_verdict() -> None:
    forge, _ = _forge(
        {f"repos/{REPO}/compare/": (1, "", "gh: Not Found (HTTP 404)"), f"repos/{REPO}": (0, "trunk", "")}
    )

    with pytest.raises(ForgeError, match="HTTP 404"):
        forge.is_on_default_branch(FULL)


def test_the_factory_selects_the_implementation_by_the_entrys_forge() -> None:
    entry = product_registry.product("web")
    assert entry.forge == "github"

    forge = adapter_for("web", entry, FakeRunner({}))

    assert isinstance(forge, GitHubForge)
    assert forge.repository == entry.repository


@pytest.mark.parametrize("forge", ["gitea", "in-tree"])
def test_the_factory_refuses_a_forge_with_no_implementation_before_asking_anything(forge: str) -> None:
    runner = FakeRunner({})
    entry = product_registry.product("web").model_copy(update={"forge": forge})

    with pytest.raises(ContractError) as refused:
        adapter_for("web", entry, runner)

    assert f"forge: {forge}" in refused.value.error
    assert refused.value.why and refused.value.fix
    assert runner.calls == []


def test_the_default_runner_names_a_missing_gh_instead_of_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "")

    with pytest.raises(ContractError, match="gh CLI is not installed"):
        forge_adapter.run_gh("api", "repos/acme/widget")


# `toolkit product resolve`: the receiver's resolve step as one command.


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch):
    """Replace the default runner; the CLI builds its adapter with it, so every call is observed."""
    runner = FakeRunner(
        {"/commits/": (0, FULL, ""), "/compare/": (0, "behind", ""), "mlorentedev/web": (0, "master", "")}
    )
    monkeypatch.setattr(forge_adapter, "run_gh", runner)
    return runner


def _resolve(*argv: str) -> tuple[int, dict]:
    result = CliRunner().invoke(app, ["resolve", *argv, "--json"])
    return result.exit_code, json.loads(result.stdout)


def test_resolve_prints_the_commit_and_that_it_is_on_the_default_branch(scripted: FakeRunner) -> None:
    code, answer = _resolve("--app", "web", "--tag", f"sha-{SHORT}")

    assert code == 0, answer
    assert answer == {
        "ok": True,
        "app": "web",
        "repository": "mlorentedev/web",
        "tag": f"sha-{SHORT}",
        "sha": FULL,
        "on_default_branch": True,
    }
    assert scripted.calls[0] == ("api", f"repos/mlorentedev/web/commits/{SHORT}", "--jq", ".sha")


def test_resolve_refuses_a_commit_the_product_never_merged(scripted: FakeRunner) -> None:
    scripted.answers["/compare/"] = (0, "ahead", "")

    code, answer = _resolve("--app", "web", "--tag", f"sha-{SHORT}")

    assert code == 1
    assert answer["ok"] is False and answer["on_default_branch"] is False and answer["sha"] == FULL
    assert answer["error"] and answer["why"] and answer["fix"]


def test_resolve_refuses_a_tag_that_is_not_an_immutable_sha_tag_before_asking_the_forge(scripted: FakeRunner) -> None:
    code, answer = _resolve("--app", "web", "--tag", "latest")

    assert code == 1 and answer["ok"] is False
    assert scripted.calls == []


@pytest.mark.parametrize("name", ["api", "ghost"])
def test_resolve_asks_nothing_for_a_product_with_no_forge_to_read(scripted: FakeRunner, name: str) -> None:
    code, answer = _resolve("--app", name, "--tag", f"sha-{SHORT}")

    assert code == 1 and answer["ok"] is False
    assert scripted.calls == []


def test_resolve_text_form_prints_the_commit_on_stdout_and_a_refusal_as_three_lines_on_stderr(
    scripted: FakeRunner,
) -> None:
    ok = CliRunner().invoke(app, ["resolve", "--app", "web", "--tag", f"sha-{SHORT}"])
    assert ok.exit_code == 0 and FULL in ok.stdout and "on the default branch" in ok.stdout

    refused = CliRunner().invoke(app, ["resolve", "--app", "web", "--tag", "latest"])
    assert refused.exit_code == 1 and refused.stdout == ""
    assert [line.split(":", 1)[0] for line in refused.stderr.splitlines()] == ["ERROR", "WHY", "FIX"]
