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
import requests
from typer.testing import CliRunner

from toolkit.cli.product import app
from toolkit.features import forge_adapter, product_ready, product_registry, promotion
from toolkit.features.forge_adapter import (
    ForgeAdapter,
    ForgeError,
    ForgeReadError,
    GiteaForge,
    GitHubForge,
    adapter_for,
)
from toolkit.features.gitea_client import ADMIN_METHODS, SCOPE_BY_METHOD, GiteaClient
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


OLDER = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"


@pytest.mark.parametrize(
    ("status", "forward"), [("ahead", True), ("identical", False), ("behind", False), ("diverged", False)]
)
def test_a_commit_moves_another_forward_only_when_the_comparison_says_ahead(status: str, forward: bool) -> None:
    """Only `ahead` is a descendant: `diverged` shares no history that makes it a successor (#796)."""
    forge, runner = _forge({f"repos/{REPO}/compare/": (0, status, "")})

    assert forge.is_ahead_of(OLDER, FULL) is forward
    assert runner.calls == [("api", f"repos/{REPO}/compare/{OLDER}...{FULL}", "--jq", ".status")]


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


def test_the_factory_refuses_a_forge_with_no_implementation_before_asking_anything() -> None:
    runner = FakeRunner({})
    entry = product_registry.product("web").model_copy(update={"forge": "in-tree"})

    with pytest.raises(ContractError) as refused:
        adapter_for("web", entry, runner)

    assert "forge: in-tree" in refused.value.error
    assert refused.value.why and refused.value.fix
    assert runner.calls == []


def test_the_default_runner_names_a_missing_gh_instead_of_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "")

    with pytest.raises(ContractError, match="gh CLI is not installed"):
        forge_adapter.run_gh("api", "repos/acme/widget")


# The Gitea implementation, against the bodies a Gitea 1.27.3 answered with
# (docs/lessons/toolkit-tooling/lesson-733): no network, one scripted session.

TAG_OBJECT = "2819644632434a7fdc1c7e342cbd3465a5c1ab81"
GIT = f"/repos/{REPO}/git/commits"
NO_COMMIT = (404, '{"message":"commit doesn\'t exist: f765","url":"https://forge.invalid/api/swagger"}')


def _commit_body(sha: str) -> tuple[int, str]:
    return 200, json.dumps({"url": f"https://forge.invalid/api/v1{GIT}/{sha}", "sha": sha, "parents": []})


class ScriptedSession:
    """Stands in for `requests.Session`: answers by exact API path, logs every request."""

    def __init__(self, answers: dict[str, tuple[int, str]], fallback: tuple[int, str] | None = None) -> None:
        self.answers, self.fallback = answers, fallback
        self.calls: list[str] = []

    def request(self, method: str, url: str, **_: object) -> requests.Response:
        path = url.split("/api/v1", 1)[1]
        self.calls.append(f"{method} {path}")
        answer = self.answers.get(path, self.fallback)
        assert answer is not None, f"unscripted Gitea call: {method} {path}"
        resp = requests.Response()
        resp.status_code, resp._content = answer[0], answer[1].encode()
        return resp


def _gitea(
    answers: dict[str, tuple[int, str]],
    fallback: tuple[int, str] | None = None,
    client: type[GiteaClient] = GiteaClient,
) -> tuple[GiteaForge, ScriptedSession]:
    session = ScriptedSession(answers, fallback)
    reader = client("https://forge.invalid", "not-a-real-token")
    reader.session = session  # type: ignore[assignment]
    return GiteaForge(REPO, reader), session


def test_the_gitea_implementation_is_a_forge_adapter() -> None:
    assert isinstance(_gitea({})[0], ForgeAdapter)


def test_gitea_resolve_commit_returns_the_full_sha_of_a_unique_prefix() -> None:
    forge, session = _gitea({f"{GIT}/{SHORT}": _commit_body(FULL)})

    assert forge.resolve_commit(SHORT) == FULL
    assert session.calls == [f"GET {GIT}/{SHORT}"]


def test_gitea_tells_an_unknown_short_sha_from_an_ambiguous_one() -> None:
    """Gitea answers both with the same 404 and body; only the one-digit extensions tell them apart."""
    unknown, _ = _gitea({f"{GIT}/f765": NO_COMMIT}, fallback=NO_COMMIT)
    ambiguous, _ = _gitea({f"{GIT}/f765b": _commit_body("f765b8" + "0" * 34)}, fallback=NO_COMMIT)

    with pytest.raises(ForgeError) as no_such:
        unknown.resolve_commit("f765")
    with pytest.raises(ForgeError) as many:
        ambiguous.resolve_commit("f765")

    assert "no commit" in str(no_such.value) and "more digits" in str(no_such.value)
    assert "more than one" not in str(no_such.value)
    assert "more than one" in str(many.value) and "no commit" not in str(many.value)


def test_gitea_ambiguity_probe_stops_at_the_first_extension_that_resolves() -> None:
    forge, session = _gitea({f"{GIT}/abcd1": _commit_body("abcd1" + "0" * 35)}, fallback=NO_COMMIT)

    with pytest.raises(ForgeError, match="more than one"):
        forge.resolve_commit("abcd")

    assert session.calls == [f"GET {GIT}/abcd"] + [f"GET {GIT}/abcd{d}" for d in "01"]


@pytest.mark.parametrize("suffix", ["\n", " ", "0"])
def test_gitea_resolve_commit_refuses_a_sha_with_anything_after_the_forty_digits(suffix: str) -> None:
    """`$` matches before a trailing newline, so `.match` accepted `<40hex>\\n`; the whole value must be a sha (#3062 F5)."""
    forge, _ = _gitea({f"{GIT}/{SHORT}": _commit_body(FULL + suffix)})

    with pytest.raises(ForgeError, match="resolved to"):
        forge.resolve_commit(SHORT)


@pytest.mark.parametrize("suffix", ["\n", " ", "0"])
def test_gitea_resolve_tag_refuses_a_sha_with_anything_after_the_forty_digits(suffix: str) -> None:
    forge, _ = _gitea({f"/repos/{REPO}/tags/v1": _tag_body("v1", FULL + suffix, FULL)})

    with pytest.raises(ForgeError, match="not a full commit sha"):
        forge.resolve_tag("v1")


def test_gitea_resolve_commit_refuses_a_ref_name_that_resolves_to_a_commit() -> None:
    """`/git/commits/main` answers 200 with the branch head, so the sha must start with what was asked."""
    forge, _ = _gitea({f"{GIT}/main": _commit_body(FULL)})

    with pytest.raises(ForgeError, match="does not start with it"):
        forge.resolve_commit("main")


def test_gitea_resolve_commit_does_not_ask_for_fewer_digits_than_gitea_answers_for() -> None:
    forge, session = _gitea({})

    with pytest.raises(ForgeError, match="at least 4"):
        forge.resolve_commit("b98")

    assert session.calls == []


def test_gitea_resolve_commit_reports_an_outage_as_one_not_as_an_unknown_commit() -> None:
    forge, _ = _gitea({f"{GIT}/{SHORT}": (502, "bad gateway")})

    with pytest.raises(ForgeError, match="502"):
        forge.resolve_commit(SHORT)


def test_gitea_tells_a_read_that_failed_from_an_answer_that_says_no() -> None:
    """The judge reads the first as `unknown` and the second as a refusal (#3288), so the type must differ."""
    down, _ = _gitea({f"{GIT}/{SHORT}": (502, "bad gateway")})
    absent, _ = _gitea({}, fallback=NO_COMMIT)

    with pytest.raises(ForgeReadError):
        down.resolve_commit(SHORT)
    with pytest.raises(ForgeError) as no_such:
        absent.resolve_commit(SHORT)
    assert not isinstance(no_such.value, ForgeReadError)


def _tag_body(name: str, commit: str, object_id: str) -> tuple[int, str]:
    url = f"https://forge.invalid/api/v1{GIT}/{object_id}"
    return 200, json.dumps({"name": name, "id": object_id, "commit": {"url": url, "sha": commit}})


def test_gitea_resolve_tag_returns_the_commit_of_an_annotated_tag_not_the_tag_object() -> None:
    forge, session = _gitea({f"/repos/{REPO}/tags/v1.16.1": _tag_body("v1.16.1", FULL, TAG_OBJECT)})

    assert forge.resolve_tag("v1.16.1") == FULL
    assert session.calls == [f"GET /repos/{REPO}/tags/v1.16.1"]


def test_gitea_resolve_tag_reads_a_lightweight_tag_the_same_way() -> None:
    forge, _ = _gitea({f"/repos/{REPO}/tags/v1.0.0": _tag_body("v1.0.0", FULL, FULL)})

    assert forge.resolve_tag("v1.0.0") == FULL


def test_gitea_resolve_tag_refuses_a_missing_tag_and_a_commit_that_is_not_a_sha() -> None:
    gone = (404, '{"message":"tag doesn\'t exist: v9.9.9"}')
    absent, _ = _gitea({f"/repos/{REPO}/tags/v9.9.9": gone})
    odd, _ = _gitea({f"/repos/{REPO}/tags/v1": _tag_body("v1", "v1", "v1")})

    with pytest.raises(ForgeError, match="names no tag"):
        absent.resolve_tag("v9.9.9")
    with pytest.raises(ForgeError, match="not a full commit sha"):
        odd.resolve_tag("v1")


def test_gitea_resolve_tag_answers_a_body_with_no_commit_as_a_forge_error_not_a_key_error() -> None:
    forge, _ = _gitea({f"/repos/{REPO}/tags/v1": (200, '{"name": "v1", "id": "x"}')})

    with pytest.raises(ForgeError, match="commit"):
        forge.resolve_tag("v1")


def test_gitea_read_file_returns_the_raw_bytes_at_the_commit() -> None:
    contract = "schema_version: 1\n"
    forge, session = _gitea({f"/repos/{REPO}/raw/kubelab.yaml?ref={FULL}": (200, contract)})

    assert forge.read_file("kubelab.yaml", FULL) == contract
    assert session.calls == [f"GET /repos/{REPO}/raw/kubelab.yaml?ref={FULL}"]


def test_gitea_read_file_keeps_an_empty_file_empty_and_encodes_the_path() -> None:
    forge, session = _gitea({f"/repos/{REPO}/raw/a%20b/c.yaml?ref={FULL}": (200, "")})

    assert forge.read_file("a b/c.yaml", FULL) == ""
    assert session.calls == [f"GET /repos/{REPO}/raw/a%20b/c.yaml?ref={FULL}"]


def test_gitea_read_file_refuses_a_missing_file_with_what_the_forge_said() -> None:
    forge, _ = _gitea({f"/repos/{REPO}/raw/kubelab.yaml?ref={FULL}": (404, '{"message":"not found"}')})

    with pytest.raises(ForgeError, match="404.*not found"):
        forge.read_file("kubelab.yaml", FULL)


def test_a_missing_contract_on_gitea_is_refused_with_error_why_and_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    forge, _ = _gitea({f"{GIT}/b9874f2": _commit_body(FULL), f"/repos/{REPO}/raw/kubelab.yaml?ref={FULL}": (404, "{}")})
    monkeypatch.setattr(promotion, "resolve_image_sha", lambda env, name: "sha-b9874f2")
    monkeypatch.setattr(product_ready, "forge_for", lambda app, registry=None: forge)

    with pytest.raises(ContractError) as refused:
        product_ready.check_ready("web")

    assert "kubelab.yaml" in refused.value.error and refused.value.why and refused.value.fix
    assert str(refused.value).startswith("ERROR: ")


def _repo_body(branch: str = "trunk") -> tuple[int, str]:
    return 200, json.dumps({"full_name": REPO, "default_branch": branch})


@pytest.mark.parametrize(("ahead", "on_default"), [(0, True), (1, False)], ids=["merged-or-head", "not-merged"])
def test_gitea_commit_is_on_the_default_branch_when_it_adds_nothing_to_the_branch(ahead: int, on_default: bool) -> None:
    compare = f"/repos/{REPO}/compare/trunk...{FULL}"
    forge, session = _gitea({f"/repos/{REPO}": _repo_body(), compare: (200, json.dumps({"total_commits": ahead}))})

    assert forge.is_on_default_branch(FULL) is on_default
    assert session.calls == [f"GET /repos/{REPO}", f"GET {compare}"]


def test_gitea_compares_from_a_default_branch_whose_name_has_a_slash() -> None:
    compare = f"/repos/{REPO}/compare/rel/next...{FULL}"
    forge, _ = _gitea({f"/repos/{REPO}": _repo_body("rel/next"), compare: (200, '{"total_commits": 0}')})

    assert forge.is_on_default_branch(FULL) is True


def test_gitea_an_unreadable_default_branch_is_an_error_not_a_verdict() -> None:
    forge, session = _gitea({f"/repos/{REPO}": (502, "bad gateway")})

    with pytest.raises(ForgeError, match="502"):
        forge.is_on_default_branch(FULL)
    assert len(session.calls) == 1, "a comparison against an unknown branch was asked"


@pytest.mark.parametrize("answer", [(404, '{"message":"not found"}'), (200, "{}")], ids=["unknown-sha", "no-total"])
def test_gitea_a_failed_comparison_is_an_error_not_a_verdict(answer: tuple[int, str]) -> None:
    forge, _ = _gitea({f"/repos/{REPO}": _repo_body(), f"/repos/{REPO}/compare/trunk...{FULL}": answer})

    with pytest.raises(ForgeError):
        forge.is_on_default_branch(FULL)


@pytest.mark.parametrize(
    ("gained", "lost", "forward"),
    [(3, 0, True), (0, 0, False), (0, 3, False), (2, 2, False)],
    ids=["ahead", "identical", "behind", "diverged"],
)
def test_gitea_a_commit_moves_another_forward_only_when_it_adds_commits_and_loses_none(
    gained: int, lost: int, forward: bool
) -> None:
    """Gitea's compare counts commits and names no status, so both directions are asked."""
    answers = {
        f"/repos/{REPO}/compare/{OLDER}...{FULL}": (200, json.dumps({"total_commits": gained})),
        f"/repos/{REPO}/compare/{FULL}...{OLDER}": (200, json.dumps({"total_commits": lost})),
    }
    forge, _ = _gitea(answers)

    assert forge.is_ahead_of(OLDER, FULL) is forward


def test_gitea_a_failed_order_comparison_is_an_error_not_a_verdict() -> None:
    forge, _ = _gitea({f"/repos/{REPO}/compare/{OLDER}...{FULL}": (502, "bad gateway")})

    with pytest.raises(ForgeError, match="502"):
        forge.is_ahead_of(OLDER, FULL)


def test_the_gitea_implementation_reads_with_read_repository_and_nothing_else() -> None:
    """The reads `GiteaForge` makes, observed on a spy client, are exactly the ones it declares."""
    used: set[str] = set()

    class Spy(GiteaClient):
        def __getattribute__(self, name: str) -> object:
            if name in SCOPE_BY_METHOD:
                used.add(name)
            return super().__getattribute__(name)

    forge, _ = _gitea(
        {
            f"{GIT}/{SHORT}": _commit_body(FULL),
            f"/repos/{REPO}": _repo_body(),
            f"/repos/{REPO}/compare/trunk...{FULL}": (200, '{"total_commits": 0}'),
            f"/repos/{REPO}/compare/{OLDER}...{FULL}": (200, '{"total_commits": 1}'),
            f"/repos/{REPO}/compare/{FULL}...{OLDER}": (200, '{"total_commits": 0}'),
            f"/repos/{REPO}/raw/kubelab.yaml?ref={FULL}": (200, "x"),
            f"/repos/{REPO}/tags/v1": _tag_body("v1", FULL, FULL),
        },
        client=Spy,
    )
    forge.resolve_commit(SHORT)
    forge.is_on_default_branch(FULL)
    forge.is_ahead_of(OLDER, FULL)
    forge.read_file("kubelab.yaml", FULL)
    forge.resolve_tag("v1")

    assert used == set(GiteaForge.READS), "GiteaForge.READS does not name what the forge calls"
    assert {SCOPE_BY_METHOD[m] for m in used} == {frozenset({"read:repository"})}
    # `get_repo` is shared with the reconciler; the rest are the receiver's own reads.
    assert not (used - {"get_repo"}) & set(ADMIN_METHODS), "the receiver reads with its own token, not the reconciler's"


def test_the_factory_builds_the_gitea_implementation_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITEA_URL", "https://forge.invalid/")
    monkeypatch.setenv("GITEA_REPO_READER_TOKEN", "not-a-real-token")
    entry = product_registry.product("web").model_copy(update={"forge": "gitea"})

    forge = adapter_for("web", entry, FakeRunner({}))

    assert isinstance(forge, GiteaForge) and forge.repository == entry.repository


@pytest.mark.parametrize("missing", ["GITEA_URL", "GITEA_REPO_READER_TOKEN"])
def test_the_factory_names_the_gitea_setting_it_lacks(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    monkeypatch.setenv("GITEA_URL", "https://forge.invalid")
    monkeypatch.setenv("GITEA_REPO_READER_TOKEN", "not-a-real-token")
    monkeypatch.delenv(missing)
    entry = product_registry.product("web").model_copy(update={"forge": "gitea"})

    with pytest.raises(ContractError) as refused:
        adapter_for("web", entry, FakeRunner({}))

    assert missing in refused.value.error and refused.value.why and refused.value.fix
    assert "not-a-real-token" not in str(refused.value)


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
