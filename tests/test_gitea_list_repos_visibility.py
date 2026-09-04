"""`list_repos` must read visibility FROM THE PAYLOAD, not assume it.

Split from `test_gitea_repo_reconcile.py` on purpose. Those tests prove the plan
compares declared visibility against live visibility correctly; they take the
live side as a fixture, so they hold whatever `list_repos` hands them and stay
green if it hands them a constant.

Measured by mutation on 2026-09-03: replacing the payload read with a literal
`True` left all 129 Gitea tests passing. Every drift assertion in the suite was
resting on a value nothing checked -- lesson-413's shape, where a fake that
encodes a wrong belief certifies the belief rather than failing.
"""

from __future__ import annotations

from typing import Any

from toolkit.features.gitea_client import GiteaClient


class _StubbedListing(GiteaClient):
    """Answers `/repos/search` with a fixed payload. No network."""

    def __init__(self, payload: list[dict[str, Any]]) -> None:
        super().__init__("https://forge.invalid", token="unused")
        self._payload = payload

    def _paginate(self, endpoint: str, key: str | None = None) -> Any:
        assert endpoint.startswith("/repos/search"), endpoint
        return list(self._payload)


def _repo(owner: str, name: str, private: bool) -> dict[str, Any]:
    """The subset of Gitea's repository object this reads. Field names are Gitea's."""
    return {"owner": {"username": owner}, "name": name, "private": private}


def test_visibility_comes_from_the_payload() -> None:
    """Both values must survive the mapping, or the comparison built on it is fiction."""
    client = _StubbedListing(
        [
            _repo("personal", "resume", private=False),
            _repo("teledyne", "fae-brain", private=True),
        ]
    )

    assert client.list_repos() == {"personal/resume": False, "teledyne/fae-brain": True}


def test_a_listing_of_mixed_visibility_does_not_collapse() -> None:
    """The anti-vacuity floor, on the returned mapping rather than on the payload.

    A constant return value satisfies any assertion that only checks one repo, so
    assert that BOTH values are present. This is the assertion the mutation above
    escaped: `{...: True}` for every entry passes a same-visibility fixture and
    every existence check in the suite.
    """
    client = _StubbedListing(
        [
            _repo("personal", "resume", private=False),
            _repo("personal", "cv", private=True),
            _repo("teledyne", "fae-brain", private=False),
        ]
    )

    visibilities = set(client.list_repos().values())

    assert visibilities == {True, False}, (
        f"list_repos collapsed a mixed-visibility listing to {visibilities}. Every "
        "visibility-drift test in the suite takes this mapping as given, so a constant "
        "here makes all of them assert nothing."
    )


def test_a_missing_private_field_is_not_read_as_private() -> None:
    """Absence must not silently become the safer-looking answer.

    Gitea always sends `private`, so this is about what happens when it does not --
    a truncated response, a future API change, a fixture someone writes by hand.
    Defaulting to True would report a public repository as private, which is the
    one direction that turns this guard into a source of false reassurance: the
    forge would be more open than the tool says.
    """
    client = _StubbedListing([{"owner": {"username": "personal"}, "name": "resume"}])

    assert client.list_repos() == {"personal/resume": False}


def test_the_name_still_carries_the_owner() -> None:
    """The key shape `plan_reconcile` matches declarations against, unchanged by this.

    `declared_full_names` builds `"org/name"` independently, and a shape change on
    one side made a declared repository read as undeclared once already (recorded
    in `format_plan`'s docstring, measured on prod 2026-09-02).
    """
    client = _StubbedListing([_repo("teledyne", "openkm-brain", private=False)])

    assert set(client.list_repos()) == {"teledyne/openkm-brain"}
