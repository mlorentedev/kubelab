"""The paginator builds a valid URL even when the caller brought a query string.

Latent until AC3's verification passed `?state=open&type=issues` and got back
`403 required=[read:issue]` -- which hid the real defect for a moment, because the
URL was ALSO malformed: `_paginate` appended `?page=1` unconditionally, producing
a second `?`. Gitea reads that as part of the previous parameter's value, so the
filter silently becomes `type=issues?page=1` and the endpoint answers with the
wrong set rather than an error.

That is the failure shape this repository keeps writing lessons about: not a crash,
a quietly wrong answer. A count taken through such a URL would have been recorded
in `verification.md` as evidence.
"""

from __future__ import annotations

from typing import Any

from toolkit.features.gitea_client import PAGE_SIZE, GiteaClient


class RecordingClient(GiteaClient):
    """Captures the URLs `_paginate` builds, without a network."""

    def __init__(self) -> None:
        super().__init__("https://forge.invalid", token="unused")
        self.requested: list[str] = []

    def _request(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        self.requested.append(endpoint)
        return []


def test_a_plain_endpoint_gets_a_question_mark() -> None:
    client = RecordingClient()
    list(client._paginate("/admin/orgs"))
    assert client.requested == [f"/admin/orgs?page=1&limit={PAGE_SIZE}"]


def test_an_endpoint_with_a_filter_gets_an_ampersand() -> None:
    """The regression itself: one `?` per URL, never two."""
    client = RecordingClient()
    list(client._paginate("/repos/personal/resume/issues?state=open&type=issues"))

    url = client.requested[0]
    assert url.count("?") == 1, f"{url} carries two query separators; the filter is swallowed"
    assert url == f"/repos/personal/resume/issues?state=open&type=issues&page=1&limit={PAGE_SIZE}"
