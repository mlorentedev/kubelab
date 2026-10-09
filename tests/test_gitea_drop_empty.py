"""TOOL-035 (#1076) — removing an EMPTY declared repository, and refusing everything else.

WHY A DELETE PATH EXISTS AT ALL IN A SPEC THAT REFUSES DELETION. It does not, and
that is the point of this file. `ReconcilePlan` still has no field a deletion could
travel in, `test_the_plan_has_no_deletion_field` still asserts that structurally,
and the reconciler still cannot remove anything. What lives here is a SEPARATE,
operator-triggered command with a different object, a different credential and
three refusals in front of it.

It exists because PR1 created the declared repositories as empty shells and
`POST /repos/migrate` answers 409 when the target already exists (Gitea 1.25.5) --
it creates a repository, it does not fill one. So the shells block the migration
that was the whole point of declaring them, and something has to remove them once.

THE CREDENTIAL IS THE SAFETY PROPERTY, not the guard. Measured against live prod
2026-09-02 on a throwaway repository, cheapest privilege first:

    DELETE as bot token             -> 403 "user should be the owner of the repo"
    DELETE as admin token           -> 403 required=[write:repository]
    DELETE as superadmin basic auth -> 204

Two 403s from two different layers -- permission and scope -- which is the trap
AUTH-004 AC5 recorded and Risk 1 hit again: the status code alone tells you
nothing, the body does. The tempting fix is to widen the admin token with
`write:repository`. That is the wrong fix: any credential that can delete an empty
repository can delete a populated one, so widening buys a permanent delete
capability on the reconciler's own token in exchange for removing three shells
once. `GiteaBasicAuthClient` is already the documented path for operations Gitea
refuses to tokens, already used for token revocation, and grants nothing durable.

The `empty` guard is therefore a guard against OPERATOR ERROR, never against the
credential -- the credential does not know about it. That is why the checks are
pure, exhaustive and tested here rather than trusted to a code path.
"""

from __future__ import annotations

import pytest

from toolkit.features.gitea_repos import DropDecision, plan_drop


def test_an_empty_declared_repository_may_be_dropped() -> None:
    """The one case this command exists for."""
    decision = plan_drop(
        native=set(),
        tracker_items=0,
        full_name="personal/resume",
        repo={"empty": True, "size": 22},
        declared={"personal/resume"},
    )
    assert decision.may_drop
    assert decision.reason is None


def test_a_repository_with_content_is_refused() -> None:
    """`empty: False` is the whole difference between a shell and someone's work.

    Asserted on the DECISION rather than by checking no delete call happened,
    because the second form passes for a fixture that was never going to delete
    anything. This one holds for every caller.
    """
    decision = plan_drop(
        native=set(),
        tracker_items=0,
        full_name="personal/resume",
        repo={"empty": False, "size": 4102},
        declared={"personal/resume"},
    )
    assert not decision.may_drop
    assert "not empty" in (decision.reason or "")


def test_an_undeclared_repository_is_refused_even_when_empty() -> None:
    """#1076's central promise survives this command.

    An undeclared repository is REPORTED and never removed -- ADR-065 D3's "import
    by accident must not become policy by inertia" cuts both ways, and a stray is
    exactly the thing whose removal needs a human who knows what it was. Emptiness
    does not make it ours to delete.
    """
    decision = plan_drop(
        native=set(),
        tracker_items=0,
        full_name="personal/somebody-elses-thing",
        repo={"empty": True, "size": 0},
        declared={"personal/resume"},
    )
    assert not decision.may_drop
    assert "not declared" in (decision.reason or "")


def test_an_absent_repository_is_already_converged() -> None:
    """Idempotent by absence: a second run is a no-op, not an error.

    Same contract as `revoke_token`'s 404 handling. A command that fails on its
    second run is not an operation, it is a script.
    """
    decision = plan_drop(
        native=set(), tracker_items=0, full_name="personal/resume", repo=None, declared={"personal/resume"}
    )
    assert not decision.may_drop
    assert "already absent" in (decision.reason or "")


def test_emptiness_is_read_from_the_field_gitea_sets_not_inferred_from_size() -> None:
    """`size` is not `empty`, and trusting it would delete a repository with content.

    Gitea reports `size: 22` for a freshly created EMPTY repository -- the bytes
    are the git directory itself, measured on all three shells on 2026-09-02. A
    guard written as `size == 0` would have refused every real shell (harmless) and
    a guard written as `size < 100` would eventually accept a tiny real repository
    (not harmless). `empty` is the field Gitea maintains for this question.
    """
    assert plan_drop(
        native=set(), tracker_items=0, full_name="a/b", repo={"empty": True, "size": 22}, declared={"a/b"}
    ).may_drop

    tiny_but_real = plan_drop(
        native=set(), tracker_items=0, full_name="a/b", repo={"empty": False, "size": 22}, declared={"a/b"}
    )
    assert not tiny_but_real.may_drop


def test_a_missing_empty_field_is_refused_rather_than_assumed() -> None:
    """An answer that does not contain the field is "I do not know", never "no".

    lesson-408's rule applied to a single key: a payload lacking `empty` means the
    question was not answered, and defaulting it to True would delete on the
    strength of a missing value.
    """
    decision = plan_drop(native=set(), tracker_items=0, full_name="a/b", repo={"size": 22}, declared={"a/b"})
    assert not decision.may_drop
    assert "did not report" in (decision.reason or "")


@pytest.mark.parametrize("full_name", ["resume", "a/b/c", "", "/", "personal/"])
def test_a_malformed_target_is_refused(full_name: str) -> None:
    """`owner/name` is the only shape, and a wrong one must not become a wrong URL.

    `DELETE /repos/{owner}/{repo}` built from `"resume"` would produce a path that
    is not the repository anyone meant. Refusing here keeps a typo from reaching
    the API at all.
    """
    with pytest.raises(ValueError):
        plan_drop(native=set(), tracker_items=0, full_name=full_name, repo={"empty": True}, declared={full_name})


def test_the_decision_carries_no_capability() -> None:
    """`DropDecision` answers a question; it cannot perform the deletion.

    The same structural reasoning as `ReconcilePlan`: safety asserted over the type
    rather than over a code path nobody happens to call. A future refactor that
    hangs a client on the decision fails here.
    """
    import dataclasses

    fields = {f.name for f in dataclasses.fields(DropDecision)}
    assert fields == {"may_drop", "reason"}, (
        f"DropDecision grew {sorted(fields - {'may_drop', 'reason'})}. It is a verdict, not an "
        f"actor -- giving it a client or a callable puts the delete back inside the planning half."
    )


def test_the_declared_set_is_produced_by_one_function_not_by_each_caller() -> None:
    """`declared_full_names` exists because two call sites drifted apart the first time.

    `drop-empty` built its own `{f"{org}/{name}" for org, names in ...}` against the
    declaration's OLD shape. When entries became `RepoSpec` records, that
    comprehension produced strings like `"personal/RepoSpec(name='resume', ...)"`,
    so a declared repository read as undeclared and the command refused it —
    measured against prod on 2026-09-02.

    It failed safe, because the membership test guards a deletion and garbage on
    one side means refuse. That was luck about which direction the bug pointed, not
    a property of the design, so the set now has a single producer.
    """
    from toolkit.features.gitea_repos import RepoSpec, declared_full_names

    declaration = {
        "personal": [RepoSpec("resume", migrate_from="github:mlorentedev/resume")],
        "kubelab": [],
    }
    assert declared_full_names(declaration) == {"personal/resume"}
    assert all("RepoSpec" not in name for name in declared_full_names(declaration))


# --- #2133: an empty GIT repository is not an empty REPOSITORY ------------------


def test_an_empty_repository_with_issues_is_refused() -> None:
    """#2133: `empty` is about git, and issues live outside it.

    `teledyne/openkm-brain` read `empty: True` on 2026-10-08 while holding two
    issues with comments, one of them a fixture APP-CONFIG-015 replays. The old
    guard would have deleted both, because the only content it knew of was git.
    """
    decision = plan_drop(
        native=set(),
        full_name="teledyne/openkm-brain",
        repo={"empty": True, "size": 22},
        declared={"teledyne/openkm-brain"},
        tracker_items=2,
    )
    assert not decision.may_drop
    assert "2 issue" in (decision.reason or "")


def test_an_unknown_tracker_count_is_refused() -> None:
    """None means the count was not read, which is not zero."""
    decision = plan_drop(native=set(), full_name="a/b", repo={"empty": True}, declared={"a/b"}, tracker_items=None)
    assert not decision.may_drop
    assert "did not count" in (decision.reason or "")


def test_the_operator_may_discard_issues_only_by_naming_their_exact_count() -> None:
    """The override is a count, not a switch, so a stale approval cannot delete more than was seen."""

    def drop(discard: int | None):
        return plan_drop(
            native=set(),
            full_name="a/b",
            repo={"empty": True},
            declared={"a/b"},
            tracker_items=2,
            discard_tracker_items=discard,
        )

    assert drop(2).may_drop
    assert not drop(1).may_drop
    assert not drop(3).may_drop
    assert "2" in (drop(1).reason or "")


def test_the_discard_count_cannot_unlock_a_repository_with_git_content() -> None:
    decision = plan_drop(
        native=set(), full_name="a/b", repo={"empty": False}, declared={"a/b"}, tracker_items=2, discard_tracker_items=2
    )
    assert not decision.may_drop


# --- the count the decision depends on ------------------------------------------


class _Response:
    def __init__(self, status: int, payload: object) -> None:
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload
        self.content = b"x"
        self.text = str(payload)

    def json(self) -> object:
        return self._payload


class _Session:
    """Answers by the `type=` filter, so a client that asks for one kind only is visible."""

    def __init__(self, issues: int, pulls: int) -> None:
        self.by_type = {
            "issues": [{"number": n} for n in range(issues)],
            "pulls": [{"number": n} for n in range(pulls)],
        }
        self.urls: list[str] = []

    def request(self, method: str, url: str, **_kwargs: object) -> _Response:
        self.urls.append(url)
        kind = url.split("type=")[1].split("&")[0]
        return _Response(200, self.by_type[kind])


def test_the_count_includes_closed_issues_and_pull_requests() -> None:
    """A closed issue is deleted with the repository as surely as an open one.

    `GET /repos/{o}/{r}` carries `open_issues_count` and `open_pr_counter`, which is
    why it is tempting and why it is wrong: both are OPEN counts, so a repository
    whose history is all closed would read as holding nothing.
    """
    from toolkit.features.gitea_client import GiteaBasicAuthClient

    client = GiteaBasicAuthClient("https://gitea.example.invalid", "manu", "pw")
    session = _Session(issues=2, pulls=3)
    client.session = session  # type: ignore[assignment]

    assert client.count_tracker_items("teledyne", "openkm-brain") == 5
    assert all("state=all" in url for url in session.urls)
    assert {url.split("type=")[1].split("&")[0] for url in session.urls} == {"issues", "pulls"}


# --- #2133: a native repository is never dropped -------------------------------


def test_a_native_repository_is_refused_even_when_empty() -> None:
    """This command clears shells that block a MIGRATION. A native repository has no
    source to migrate from, so dropping it buys nothing and leaves the reconciler
    reporting it absent with only a restore to answer -- and an empty native one may
    be new work about to be pushed. Declared native means kept."""
    decision = plan_drop(
        full_name="personal/imagesensortool",
        repo={"empty": True, "size": 22},
        declared={"personal/imagesensortool"},
        native={"personal/imagesensortool"},
        tracker_items=0,
    )
    assert not decision.may_drop
    assert "native" in (decision.reason or "")


def test_the_native_set_is_produced_by_one_function() -> None:
    from toolkit.features.gitea_repos import RepoSpec, native_full_names

    declaration = {
        "personal": [RepoSpec("resume", migrate_from="github:mlorentedev/resume"), RepoSpec("ist", native=True)],
        "kubelab": [],
    }
    assert native_full_names(declaration) == {"personal/ist"}


def test_native_is_a_required_argument_so_no_caller_can_forget_it() -> None:
    """The refusal guards a delete, so a caller that omits the set must not get the
    permissive answer by default."""
    with pytest.raises(TypeError):
        plan_drop(full_name="a/b", repo={"empty": True}, declared={"a/b"}, tracker_items=0)  # type: ignore[call-arg]
