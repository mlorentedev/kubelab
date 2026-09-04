"""What `create_team` and `edit_team` actually SEND, asserted on the real client.

`test_gitea_repo_execute.py` asserts what `ensure_team` does with a team it reads
back, and its `FakeClient` decides that team's shape from a constructor knob. So
the fake is free to report a correctly-scoped team however the real payload is
written -- and it did: measured by mutation on 2026-09-03, deleting
`includes_all_repositories` from `create_team` left all 24 tests there green.

That is the same defect the file's own docstring records from 2026-09-02, when
the fake echoed `permission: "write"` -- a value no real Gitea returns -- and 14
tests passed while the reconcile 500'd. A fake cannot verify the request; it can
only agree with whoever wrote it. So the request is asserted here, on the client,
against no fake at all.

The grant is a PAIR: what may be done (`units_map`, `can_create_org_repo`) and to
what (`includes_all_repositories`). Both halves are asserted, because the live
teams held the first half alone and it bought nothing -- write over zero
repositories, with the bot able to read the migrated repositories and push to
none of them.
"""

from __future__ import annotations

from typing import Any

from toolkit.features.gitea_client import TEAM_UNITS, GiteaClient


class _CapturingClient(GiteaClient):
    """Captures the method, endpoint and JSON body. No network."""

    def __init__(self) -> None:
        super().__init__("https://forge.invalid", token="unused")
        self.sent: list[tuple[str, str, dict[str, Any]]] = []

    def _request(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        self.sent.append((method, endpoint, kwargs.get("json") or {}))
        return {}


def test_create_team_grants_a_scope_and_not_only_a_permission() -> None:
    """The mutation that escaped the fake: omit the scope and the grant covers nothing."""
    client = _CapturingClient()
    client.create_team("personal", "reconcilers", "write")

    method, endpoint, body = client.sent[0]
    assert (method, endpoint) == ("POST", "/orgs/personal/teams")
    assert body["includes_all_repositories"] is True, (
        "create_team must send includes_all_repositories. Without it Gitea defaults it to "
        "False and the team is created covering zero repositories, which is the state both "
        "live teams were measured in on 2026-09-03: repo.code=write, can_create_org_repo=True, "
        "repos attached NONE."
    )


def test_edit_team_widens_the_scope_of_a_team_that_already_exists() -> None:
    """The convergence path sends the same grant, or it repairs nothing.

    Both live teams predate the flag, so every repository in the forge today
    depends on this call rather than on `create_team`.
    """
    client = _CapturingClient()
    client.edit_team(7, "reconcilers", "write")

    method, endpoint, body = client.sent[0]
    assert (method, endpoint) == ("PATCH", "/teams/7")
    assert body["includes_all_repositories"] is True


def test_both_calls_send_the_same_grant() -> None:
    """Create and converge must not drift apart.

    If they disagree, the end state depends on whether the team happened to exist
    when the reconcile ran -- a difference nothing would report and no test that
    exercises one path would catch.
    """
    client = _CapturingClient()
    client.create_team("personal", "reconcilers", "write")
    client.edit_team(7, "reconcilers", "write")

    created, edited = (body for _m, _e, body in client.sent)
    grant_fields = ("permission", "can_create_org_repo", "units_map", "includes_all_repositories")

    assert {k: created[k] for k in grant_fields} == {k: edited[k] for k in grant_fields}


def test_every_declared_unit_reaches_the_payload() -> None:
    """Anti-vacuity on the derived map, not on the constant that feeds it.

    `units_map` is built by comprehension over `TEAM_UNITS`. An empty or filtered
    `TEAM_UNITS` would produce an empty map, Gitea answers 500 on that
    (`units permission should not be empty`, measured 2026-09-02) -- but the two
    assertions above would still pass, because neither looks at what is inside.

    Asserting the FLOOR on the emitted map rather than copying the tuple: a copy
    passes when both go empty together, which is exactly the failure lesson-416
    names.
    """
    client = _CapturingClient()
    client.create_team("personal", "reconcilers", "write")

    units = client.sent[0][2]["units_map"]

    assert units, "units_map is empty; Gitea answers 500 rather than creating a powerless team"
    assert set(units) == set(TEAM_UNITS)
    assert set(units.values()) == {"write"}, f"a unit was granted something other than write: {units}"


def test_repo_code_is_among_the_units() -> None:
    """The one unit that decides whether a push succeeds.

    Named explicitly rather than left to the set comparison above, because
    `TEAM_UNITS` shrinking to exclude it would keep that comparison true against
    the smaller tuple while quietly removing the ability to push.
    """
    client = _CapturingClient()
    client.create_team("personal", "reconcilers", "write")

    assert client.sent[0][2]["units_map"].get("repo.code") == "write"
