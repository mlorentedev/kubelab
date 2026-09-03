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
    decision = plan_drop(full_name="personal/resume", repo=None, declared={"personal/resume"})
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
    assert plan_drop(full_name="a/b", repo={"empty": True, "size": 22}, declared={"a/b"}).may_drop

    tiny_but_real = plan_drop(full_name="a/b", repo={"empty": False, "size": 22}, declared={"a/b"})
    assert not tiny_but_real.may_drop


def test_a_missing_empty_field_is_refused_rather_than_assumed() -> None:
    """An answer that does not contain the field is "I do not know", never "no".

    lesson-408's rule applied to a single key: a payload lacking `empty` means the
    question was not answered, and defaulting it to True would delete on the
    strength of a missing value.
    """
    decision = plan_drop(full_name="a/b", repo={"size": 22}, declared={"a/b"})
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
        plan_drop(full_name=full_name, repo={"empty": True}, declared={full_name})


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
