"""An Authelia bump PR names #1845 while a JWT access-token client has no audience.

SEC-021 made the `grafana` client issue RFC 9068 JWT access tokens, and RFC 9068
requires an `aud` claim. Authelia's `master` validator warns about a client with
a signed access-token algorithm and no `audience` or `requested_audience_mode:
implicit`; the pinned 4.39.15 does not. #1845 holds the fix, to land with the
next bump or before it. The person merging that bump is the only one placed to
remember, so the Renovate PR carries the reminder.

A dashboard-approval gate was the other option and was rejected: it would hold
back every Authelia release, security fixes included, over a warning.

The guard is bound to its condition, not to the ticket: once every such client
declares an audience, this test stops requiring the note, and the note can go.
"""

from __future__ import annotations

import json
import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
RENOVATE = REPO / "renovate.json"
COMMON = REPO / "infra/config/values/common.yaml"


def _clients_missing_an_audience() -> list[str]:
    common = yaml.safe_load(COMMON.read_text(encoding="utf-8"))
    clients = common["apps"]["services"]["security"]["authelia"]["oidc_clients"]
    return [
        c["client_id"]
        for c in clients
        if c.get("access_token_signed_response_alg")
        and not c.get("audience")
        and c.get("requested_audience_mode") != "implicit"
    ]


def _authelia_rule() -> dict:
    rules = json.loads(RENOVATE.read_text(encoding="utf-8"))["packageRules"]
    matching = [r for r in rules if "authelia/authelia" in r.get("matchPackageNames", [])]
    assert len(matching) == 1, f"expected one Renovate rule for authelia/authelia, found {len(matching)}"
    return matching[0]


def test_an_authelia_bump_names_the_audience_ticket_while_a_client_needs_one():
    missing = _clients_missing_an_audience()
    if not missing:
        return
    notes = " ".join(_authelia_rule().get("prBodyNotes", []))
    assert "#1845" in notes, (
        f"OIDC client(s) {missing} issue JWT access tokens with no audience; the "
        "authelia/authelia Renovate rule must name #1845 in prBodyNotes so the bump "
        "that starts warning about it is not merged blind."
    )
