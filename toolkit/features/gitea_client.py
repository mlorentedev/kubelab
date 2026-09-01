"""A minimal Gitea API client, carrying only what the reconciler needs (TOOL-035, #1076).

Scope is deliberately narrow. This speaks the endpoints `gitea_repos.execute` calls
and nothing else -- no migration endpoints (PR2), no webhooks or branch protection
(#503, explicitly out of scope). A client that grows ahead of its callers is a
surface nobody tests.

TWO CREDENTIALS, AND WHICH ONE READS IS NOT A DETAIL. ADR-065 D1 requires the
machine identity to own nothing, and Gitea makes the creating account the sole
member of a new organization's `Owners` team -- measured 2026-08-27. So the
superadmin creates organizations and the bot creates repositories inside them,
which is why callers construct two clients rather than one.

The *read* path also belongs to the superadmin, for a separate reason. The bot
cannot see an organization it is not a member of, so a listing taken with the
bot's token reports a private organization as absent, and `plan_reconcile` would
then plan to create something that already exists. That is lesson-408's corollary
exactly: a report that cannot find a value must distinguish "I looked and it is
not there" from "I did not look there". `list_orgs` uses the admin endpoint so the
answer means the former.

PAGINATION IS EXHAUSTIVE FOR THE SAME REASON. Gitea's list endpoints default to a
bounded page, and a count that equals the limit you passed measured the limit
rather than the collection -- the mistake lesson-408 was written about, made on
this very spec's baseline. `_paginate` walks until a short page arrives, so
"absent" is a fact about the forge instead of a fact about a default.
"""

from __future__ import annotations

from typing import Any, Iterator

import requests

#: Gitea caps `limit` at `MAX_RESPONSE_ITEMS` (50 by default). Asking for more is
#: silently clamped, so the page size is a hint and the loop below is what
#: guarantees exhaustion.
PAGE_SIZE = 50

#: The scope the bot's token needs before it can create a repository inside an
#: organization it does not own. Measured 2026-08-27: without it the call is
#: refused with `required=[write:organization]`, and a token's scopes cannot be
#: edited after minting -- widening means re-minting.
REQUIRED_BOT_SCOPE = "write:organization"


class GiteaError(Exception):
    """A Gitea API call that did not succeed.

    Carries the status code so callers can tell refusal from absence. `execute`
    relies on that distinction: a 404 while reading is a legitimate empty state,
    while a 403 means the credential is wrong and continuing would produce a plan
    built on a half-visible forge.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GiteaClient:
    """Synchronous client for the Gitea REST API v1.

    Follows `vikunja_client.VikunjaClient`'s shape (a `Session`, one `_request`
    funnel, an error type) so the two read the same way, with one difference that
    matters: Gitea authenticates with `Authorization: token <T>` rather than
    `Bearer`. Gitea also accepts the token as a basic-auth password, but the
    header form is the documented one and does not look like a password in a log.
    """

    def __init__(self, base_url: str, token: str, timeout: int = 15) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.session = requests.Session()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"token {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}/api/v1{endpoint}"
        kwargs.setdefault("headers", self._headers())
        kwargs.setdefault("timeout", self.timeout)

        resp = self.session.request(method, url, **kwargs)
        if not resp.ok:
            # The body carries Gitea's scope diagnostics verbatim -- the
            # `required=[write:organization], token scope=...` message is the one
            # that told Risk 1 apart from a permission problem. Never swallow it.
            raise GiteaError(f"Gitea API {method} {endpoint} -> {resp.status_code}: {resp.text}", resp.status_code)

        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    def _paginate(self, endpoint: str, key: str | None = None) -> Iterator[dict[str, Any]]:
        """Yield every item, walking pages until one comes back short.

        `key` names the field holding the list when the endpoint wraps its results
        (`/repos/search` returns `{"data": [...]}`), and is None when the endpoint
        returns a bare array.

        Terminating on a short page rather than on a total count is deliberate:
        the total is not returned by every endpoint, and trusting one that is
        absent is how a loop silently stops at page one.
        """
        page = 1
        while True:
            payload = self._request("GET", f"{endpoint}?page={page}&limit={PAGE_SIZE}")
            items = payload.get(key, []) if key else payload
            if not isinstance(items, list):
                raise GiteaError(f"Gitea API GET {endpoint} returned {type(items).__name__}, expected a list")
            yield from items
            if len(items) < PAGE_SIZE:
                return
            page += 1

    # --- reads (superadmin: see the whole forge, not one account's view) -------

    def list_orgs(self) -> set[str]:
        """Every organization on the instance, via the admin endpoint.

        `/admin/orgs` rather than `/user/orgs`: the latter answers "organizations
        this token's account belongs to", which for the bot is a strict subset and
        would make an existing organization look creatable.
        """
        return {str(org["username"]) for org in self._paginate("/admin/orgs")}

    def list_repos(self) -> set[str]:
        """Every repository, as `"owner/name"` -- the shape `plan_reconcile` compares against.

        `/repos/search` with an admin token spans all owners, which is what makes
        the stray report (AC2) meaningful: a repository in an undeclared
        organization is exactly the case worth reporting, and a per-organization
        listing would never see it.
        """
        return {f"{r['owner']['username']}/{r['name']}" for r in self._paginate("/repos/search", key="data")}

    def whoami(self) -> dict[str, Any]:
        """The authenticated account. Used to assert AC4 by consequence, not by assumption."""
        return self._request("GET", "/user")

    def list_owned_repos(self, username: str) -> set[str]:
        """Repositories owned by one account, for AC4's "the bot owns nothing" check."""
        return {f"{r['owner']['username']}/{r['name']}" for r in self._paginate(f"/users/{username}/repos")}

    # --- writes ---------------------------------------------------------------

    def create_org(self, name: str) -> dict[str, Any]:
        """Create an organization. SUPERADMIN ONLY -- the creator lands in `Owners`."""
        return self._request("POST", "/orgs", json={"username": name})

    def create_repo(self, org: str, name: str, private: bool = True) -> dict[str, Any]:
        """Create a repository inside an organization. The bot's job (ADR-065 D1)."""
        return self._request("POST", f"/orgs/{org}/repos", json={"name": name, "private": private})

    def get_team(self, org: str, name: str) -> dict[str, Any] | None:
        """The named team, or None. Absence is a state, not an error."""
        for team in self._paginate(f"/orgs/{org}/teams"):
            if team.get("name") == name:
                return team
        return None

    def create_team(self, org: str, name: str, permission: str) -> dict[str, Any]:
        """Create a team with a coarse permission.

        `units` is deliberately NOT passed. Measured 2026-08-27: creating a team
        with an explicit `units` list AND `permission: "write"` came back as
        `permission: none` -- passing `units` appears to override the coarse field
        rather than combine with it. Callers verify the result regardless; see
        `gitea_repos.ensure_team`.
        """
        return self._request("POST", f"/orgs/{org}/teams", json={"name": name, "permission": permission})

    def add_team_member(self, team_id: int, username: str) -> dict[str, Any]:
        """Add an account to a team. Idempotent on Gitea's side -- re-adding answers 204."""
        return self._request("PUT", f"/teams/{team_id}/members/{username}")


class GiteaBasicAuthClient(GiteaClient):
    """The subset of the API that REFUSES tokens and requires a password.

    A separate class rather than a flag, because the boundary is Gitea's and not
    ours. `DELETE /users/{username}/tokens/{id}` and its sibling listing sit
    behind `reqBasicOrRevProxyAuth()` in `routers/api/v1/api.go`, which rejects a
    bearer token before the handler runs. Read from the source on 1.25.x, not
    inferred from a 403.

    WHY THIS IS NOT ADR-062'S BREAK-GLASS DRIFTING INTO DAILY USE. ADR-062 D-88
    reserves the local password for "when Authelia is unavailable, and at no
    other time", and that rule is about a HUMAN choosing a login path. This is
    not a login: it is the only credential Gitea will accept for this endpoint,
    by construction, and line 92 of the same ADR keeps machine credentials
    "reversible in SOPS by design" precisely so automation can use them. Deleting
    this class and routing through a token does not work -- it is not a style
    preference that a later reader should tidy away.

    The paired consequence, and the reason the Ansible reassert task exists: this
    makes the admin password load-bearing for token rotation. A password that has
    drifted from SOPS takes the whole rotation path down with it, which is why
    reality is reconciled against SOPS rather than assumed to match it.
    """

    def __init__(self, base_url: str, username: str, password: str, timeout: int = 15) -> None:
        # `token` is unused on this path; the parent's signature is satisfied with
        # an empty one so the shared `_request`/`_paginate` machinery still works.
        super().__init__(base_url, token="", timeout=timeout)
        self.username = username
        self._password = password

    def _headers(self) -> dict[str, str]:
        # No Authorization header: `requests` builds the basic-auth one from
        # `auth=`. Overridden rather than inherited so a future edit to the parent
        # cannot silently send a token this endpoint would reject with a 403 that
        # reads like a permissions problem.
        return {"Content-Type": "application/json", "Accept": "application/json"}

    def _request(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        # The credential travels WITH THE REQUEST rather than living on the
        # session. Setting `session.auth` once in the constructor works until
        # something replaces the session -- a test double, a retry wrapper, a
        # pooled client -- after which every call goes out unauthenticated and
        # Gitea answers 401, which on this endpoint is indistinguishable from a
        # drifted admin password. Binding it here makes that failure impossible
        # rather than unlikely.
        kwargs.setdefault("auth", (self.username, self._password))
        return super()._request(method, endpoint, **kwargs)

    def list_tokens(self, username: str) -> list[dict[str, Any]]:
        """Every access token on an account. Names and ids only -- Gitea never returns values."""
        return list(self._paginate(f"/users/{username}/tokens"))

    def revoke_token(self, username: str, token_name: str) -> bool:
        """Delete a named token. True if it was there, False if it already was not.

        IDEMPOTENT BY 404, which is the whole contract. Gitea answers 404 when the
        name matches nothing, and that is indistinguishable from the desired end
        state -- so it is reported as "already converged" rather than raised. A
        rotation that fails on its second run is not a rotation, it is a script.

        Gitea resolves a non-numeric `{id}` by name against the path user, so the
        token name goes straight in. It answers 422 on multiple matches rather
        than guessing, which is left to propagate: two tokens sharing a name is
        exactly the state `bot_token`'s rotate_note warns about ("the account
        would hold two live credentials and nothing records which consumer holds
        which") and it needs a human, not a coin flip.
        """
        try:
            self._request("DELETE", f"/users/{username}/tokens/{token_name}")
        except GiteaError as exc:
            if exc.status_code == 404:
                return False
            raise
        return True
