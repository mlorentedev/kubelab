"""A minimal Gitea API client, carrying only what the reconciler needs (TOOL-035, #1076).

Scope is deliberately narrow. This speaks the endpoints `gitea_repos.execute` calls
and nothing else -- no branch protection (#1633, second slice). A client that grows
ahead of its callers is a surface nobody tests.

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

from typing import Any, Iterator, Mapping

import requests

#: Gitea caps `limit` at `MAX_RESPONSE_ITEMS` (50 by default). Asking for more is
#: silently clamped, so the page size is a hint and the loop below is what
#: guarantees exhaustion.
PAGE_SIZE = 50

#: Seconds allowed for `POST /repos/migrate`, which is not a CRUD call. Measured
#: 2026-09-02: migrating `resume` (3 MB, 93 issues, 165 pull requests) had not
#: returned after the client's 15s default and `requests` raised `ReadTimeout`
#: while the server carried on succeeding. An error that means "it may or may not
#: have worked" is worse than a slow call, so this is generous on purpose.
MIGRATION_TIMEOUT = 600

#: The scope the bot's token needs before it can create a repository inside an
#: organization it does not own. Measured 2026-08-27: without it the call is
#: refused with `required=[write:organization]`, and a token's scopes cannot be
#: edited after minting -- widening means re-minting.
REQUIRED_BOT_SCOPE = "write:organization"

#: The scope Gitea demands for each public method on `GiteaClient`, keyed by
#: method name. THE MAP IS THE DECLARATION; nothing below restates it.
#:
#: WHY A MAP AND NOT A HAND-WRITTEN SET. `REQUIRED_ADMIN_SCOPES` used to be a
#: literal, written once by reading the code. The code then moved and the literal
#: did not: `whoami` and `list_owned_repos` were added to assert AC4 "the bot owns
#: nothing" by consequence, both call `/users/...`, both need `read:user`, and no
#: declaration anywhere mentioned it. Measured 2026-09-02 against live prod, all
#: three refused:
#:
#:     GET /users/hefesto        -> 403 required=[read:user]
#:     GET /users/hefesto/repos  -> 403 required=[read:user]
#:     GET /user                 -> 403 required=[read:user]
#:
#: So the acceptance criterion had a reader that could never read, while the scope
#: guard stayed green because it compared a stale requirement against a matching
#: grant. Lesson 413 one layer up: last time a credential was present and
#: powerless, this time a METHOD was. `tests/test_gitea_token_scopes.py` keeps
#: this map exhaustive by introspecting the class, so a new method cannot arrive
#: without its scope arriving too.
SCOPE_BY_METHOD: dict[str, frozenset[str]] = {
    # Reads. `/admin/orgs` rather than `/user/orgs` is what `read:admin` buys --
    # the whole-forge listing AC2's stray report needs. Read-only on that axis:
    # `write:admin` is never granted because nothing here needs it.
    "list_orgs": frozenset({"read:admin"}),
    "list_repos": frozenset({"read:repository"}),
    "get_repo": frozenset({"read:repository"}),
    "whoami": frozenset({"read:user"}),
    "list_owned_repos": frozenset({"read:user"}),
    "get_team": frozenset({"read:organization"}),
    # `/admin/actions/runners` sits under the same admin router as `list_orgs`, so
    # `read:admin` covers it. Measured 200 with that grant before this line existed.
    "list_runners": frozenset({"read:admin"}),
    # MEASURED, not assumed, because the read and the write of a webhook sit on
    # different credentials and it would have been easy to declare the write's scope
    # here. `GET /repos/{o}/{r}/hooks` answered 200 with the admin token on both
    # `personal/resume` and `teledyne/fae-brain` on 2026-09-04, while `POST` to the
    # same path answered 403 required=[write:repository]. So the listing costs
    # `read:repository` and nothing more -- and `write:repository`, a standing DELETE
    # capability, stays ungranted. The write goes through basic auth instead.
    "list_hooks": frozenset({"read:repository"}),
    # Writes.
    "create_org": frozenset({"write:organization"}),
    "create_repo": frozenset({"write:organization"}),
    # A migration creates a repository inside an organization, so it needs what
    # `create_repo` needs; `write:repository` on top of it because the endpoint
    # writes repository content rather than only registering the name.
    "migrate_repo": frozenset({"write:organization", "write:repository"}),
    "create_team": frozenset({"write:organization"}),
    # Same endpoint family as `create_team`, so the same grant. It is listed
    # rather than inherited because `REQUIRED_ADMIN_SCOPES` is DERIVED from this
    # map: a method absent here is a method whose scope never enters the
    # requirement, which is how a token was minted that could authenticate and
    # not work (#1564). The guard that just failed on this line is that
    # derivation refusing to let a new method in silently.
    "edit_team": frozenset({"write:organization"}),
    "add_team_member": frozenset({"write:organization"}),
}

#: Which methods the SUPERADMIN credential performs. Not every method: `create_repo`
#: is the bot's, because Gitea makes the creating account an organization's owner
#: and ADR-065 D1 requires the machine identity to own nothing.
ADMIN_METHODS: tuple[str, ...] = (
    "list_orgs",
    "list_repos",
    "get_repo",
    "whoami",
    "list_owned_repos",
    "get_team",
    "create_org",
    "create_team",
    "edit_team",
    "add_team_member",
    "list_runners",
    # The plan's webhook read. Listed even though `read:repository` already enters
    # the requirement through `list_repos`: the point of this tuple is that a method
    # the admin token performs cannot be absent from the derivation, and "its scope
    # happens to be covered by a sibling" is a coincidence, not a rule. It is exactly
    # how #1564's token came to authenticate and not work.
    "list_hooks",
)


def _derive_admin_scopes() -> frozenset[str]:
    """Union the scopes of the methods the admin credential performs.

    RAISES AT IMPORT rather than defaulting a missing method to "no scope", and
    the difference is the point of the module: silently narrowing the requirement
    is exactly the defect being cured, so an incoherent map has to be impossible
    to run rather than merely tested against.

    The explicit message exists because the bare `SCOPE_BY_METHOD[name]` this
    replaced raised `KeyError: 'whoami'` out of a comprehension -- accurate, and
    useless to whoever hits it.
    """
    undeclared = [name for name in ADMIN_METHODS if name not in SCOPE_BY_METHOD]
    if undeclared:
        raise RuntimeError(
            f"ADMIN_METHODS names {undeclared}, absent from SCOPE_BY_METHOD. Every method the "
            f"superadmin performs must declare the scope Gitea demands for it, or the grant in "
            f"`apps.services.core.gitea.token_scopes.admin` cannot be checked against it."
        )
    return frozenset().union(*(SCOPE_BY_METHOD[name] for name in ADMIN_METHODS))


#: DERIVED, never restated. A method entering `ADMIN_METHODS` drags its scope into
#: the requirement automatically, which is the property the old literal lacked.
#:
#: Still only half a contract on its own: the grant is declared in `common.yaml`
#: and minted by Ansible, which cannot import Python.
#: `tests/test_gitea_token_scopes.py` is what makes the two agree.
REQUIRED_ADMIN_SCOPES: frozenset[str] = _derive_admin_scopes()


def expand_grant(granted: set[str]) -> set[str]:
    """Add the read scope every write scope already implies.

    Gitea's `write:organization` carries `read:organization` -- a token holding the
    write scope is not refused a read. Modelling that here lets each method declare
    the scope it HONESTLY needs (`get_team` reads, so it says `read:organization`)
    without forcing the grant to spell out a scope it already covers.

    Without this the choice would be between a dishonest map (`get_team` claiming
    a write scope it does not use) and a bloated grant, and the first is how a map
    stops describing the code it is supposed to describe.
    """
    return granted | {f"read:{scope.split(':', 1)[1]}" for scope in granted if scope.startswith("write:")}


#: The units a reconciler team is granted, each at the team's coarse permission.
#: Gitea 1.25 refuses a team with no per-unit modes (`units permission should not
#: be empty`), so this list is not optional decoration -- it is the grant.
#: `repo.code` is the one that matters for pushing; the rest are included so a
#: migrated repository's issues and releases are not read-only by accident.
TEAM_UNITS: tuple[str, ...] = (
    "repo.code",
    "repo.issues",
    "repo.pulls",
    "repo.releases",
    "repo.wiki",
    "repo.projects",
    "repo.packages",
)


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
            # `&` when the caller already brought a query string, `?` otherwise.
            # It was unconditionally `?`, which produced
            # `/repos/x/y/issues?state=open?page=1&limit=50` -- a second `?` that
            # Gitea reads as part of the previous VALUE, so the filter silently
            # became `type=issues?page=1`. Latent until the first caller passed a
            # filter (AC3's issue count, 2026-09-02); the shape is a wrong answer
            # rather than an error, which is why it gets a guard and not just a fix.
            separator = "&" if "?" in endpoint else "?"
            payload = self._request("GET", f"{endpoint}{separator}page={page}&limit={PAGE_SIZE}")
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

    def list_repos(self) -> dict[str, bool]:
        """Every repository, as `"owner/name" -> is_private` -- what `plan_reconcile` compares against.

        `/repos/search` with an admin token spans all owners, which is what makes
        the stray report (AC2) meaningful: a repository in an undeclared
        organization is exactly the case worth reporting, and a per-organization
        listing would never see it.

        RETURNS VISIBILITY ALONGSIDE THE NAME, from the same listing, so the two can
        never disagree. It returned a bare set until 2026-09-03, and the plan built
        on it could only compare existence: three repositories declared with no
        visibility at all were living public, and the reconcile reported "forge
        matches the declaration". Fetching visibility separately would have restored
        the gap in a new place -- two reads of the same forge at two moments -- so
        the one listing carries both. Membership tests read the same on a mapping.
        """
        return {
            f"{r['owner']['username']}/{r['name']}": bool(r.get("private"))
            for r in self._paginate("/repos/search", key="data")
        }

    def get_repo(self, owner: str, name: str) -> dict[str, Any] | None:
        """One repository's metadata, or None when it does not exist.

        Absence is a state, not an error -- same contract as `get_team`. The caller
        that matters here is `plan_drop`, whose "already absent" branch is what
        makes dropping idempotent on a second run.

        Read with the LEAST-PRIVILEGED credential that can answer: `read:repository`
        rather than the basic-auth session that performs the deletion. Reading and
        deleting deliberately do not share a credential.
        """
        try:
            return dict(self._request("GET", f"/repos/{owner}/{name}"))
        except GiteaError as exc:
            if exc.status_code == 404:
                return None
            raise

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

    def migrate_repo(
        self,
        org: str,
        name: str,
        clone_addr: str,
        service: str,
        auth_token: str,
        private: bool = True,
    ) -> dict[str, Any]:
        """Migrate a remote repository INTO an organization, with its issues and pull requests.

        The bot's job, not the superadmin's: this creates a repository inside an
        organization, and ADR-065 D1 keeps the machine identity owning nothing --
        the same reasoning as `create_repo`, which this replaces for any repository
        whose declaration names a source.

        WHAT IS ASKED FOR AND WHY EACH FLAG IS THERE. `mirror: False` because
        Risk 3 settled this as a MOVE, not a mirror: Gitea accepts merges from the
        migration onward and GitHub becomes the frozen rollback snapshot. A mirror
        would keep pulling from GitHub and overwrite exactly that. The content flags
        are TOOL-035 AC3 stated as a request -- they are not defaults, and omitting
        one carries the code across while silently leaving its issues behind.

        THE CREDENTIAL TRAVELS AS `auth_token`, NEVER INSIDE `clone_addr`. Embedding
        it in the URL would persist it in Gitea's stored remote and surface it in any
        error that echoes the address, and `GiteaError` echoes response bodies
        verbatim by design.

        `409` MEANS THE TARGET ALREADY EXISTS and is deliberately not swallowed.
        Migration is not idempotent the way creation is: it cannot fill an existing
        repository, so a 409 means the caller planned work against a forge state it
        had already been given. `plan_reconcile` prevents that by never proposing a
        migration for a repository that is present; a 409 reaching here means that
        invariant broke and should be loud.

        ITS OWN TIMEOUT, AND A LONG ONE. The client's 15s default is right for CRUD
        and wrong here: measured 2026-09-02 migrating `resume`, the call had not
        returned after 15 seconds and `requests` raised `ReadTimeout` -- while the
        migration was proceeding perfectly well on the server. A timeout on this
        call therefore does NOT mean the migration failed, which is the worst
        possible thing for an error to mean, so the window is widened rather than
        left to produce a false negative on every real repository.

        AND THE IMPORT OUTLIVES THE RESPONSE. Even after this returns, Gitea keeps
        importing issues and pull requests in the background. Counted minutes apart
        on the same repository: 98 pull requests then 147, 93 issues throughout. So
        a count taken when this returns measures the clock rather than the
        repository -- lesson-408's mistake with a different disguise. Callers
        verifying AC3 must wait for the import to settle, and `execute` says so
        rather than implying the repository is complete.
        """
        return self._request(
            "POST",
            "/repos/migrate",
            timeout=MIGRATION_TIMEOUT,
            json={
                "clone_addr": clone_addr,
                "repo_owner": org,
                "repo_name": name,
                "service": service,
                "auth_token": auth_token,
                "private": private,
                "mirror": False,
                "issues": True,
                "pull_requests": True,
                "labels": True,
                "milestones": True,
                "releases": True,
                "wiki": True,
            },
        )

    def get_team(self, org: str, name: str) -> dict[str, Any] | None:
        """The named team, or None. Absence is a state, not an error."""
        for team in self._paginate(f"/orgs/{org}/teams"):
            if team.get("name") == name:
                return team
        return None

    def create_team(self, org: str, name: str, permission: str) -> dict[str, Any]:
        """Create a team that can actually create repositories in `org`.

        THREE MEASUREMENTS GOT US HERE, and each looked like a complete answer:

        - 2026-08-27: `units` list + `permission: "write"` -> created, read back
          as `permission: none`. Concluded that `units` overrides the coarse
          field, so `units` was dropped.
        - 2026-09-02: no `units` at all -> HTTP 500, `units permission should not
          be empty`. Gitea 1.25 requires per-unit modes; dropping them is fatal.
        - 2026-09-02: `units_map` (a permission PER unit) -> created, still reads
          back `permission: none`, and the bot STILL could not create a
          repository -- but with a different refusal: `Given user is not allowed
          to create repository in organization`, not a scope error.

        That last one is the whole answer. Creating a repository inside an
        organization is not governed by `repo.code`; it is governed by
        `can_create_org_repo`, a separate boolean that defaults to false. With it
        set and `units_map` supplied, the bot's `POST /orgs/<org>/repos` returns
        201 -- measured, not inferred.

        `permission` still reads back as `none` and THAT IS CORRECT. It is the
        team's COARSE access mode, which Gitea sets to none precisely because the
        grant now lives per unit. Do not "fix" it; `gitea_repos.ensure_team`
        checks the fields that actually govern instead.

        A FOURTH MEASUREMENT, 2026-09-03, and it is the one that made the other
        three worth nothing on a migrated repository. `includes_all_repositories`
        defaults to FALSE, and a team's units apply only to the repositories the
        team covers. Measured on prod: `reconcilers` in both organizations read
        back `repo.code -> write`, `can_create_org_repo -> True`, and
        `repos attached: NONE`. So the bot held write over an empty set --

            personal/resume         pull=True  push=False  admin=False
            teledyne/fae-brain      pull=True  push=False  admin=False
            teledyne/openkm-brain   pull=True  push=True   admin=True

        -- with push only on the repository it had created itself, where creation
        conferred access directly rather than through the team. Every field this
        function had learned to set was correct and the grant covered nothing.
        """
        return self._request(
            "POST",
            f"/orgs/{org}/teams",
            json={
                "name": name,
                "permission": permission,
                "can_create_org_repo": True,
                "units_map": {unit: permission for unit in TEAM_UNITS},
                # The scope the units apply TO. Without it the team is created
                # covering zero repositories and every other field is decoration.
                "includes_all_repositories": True,
            },
        )

    def edit_team(self, team_id: int, name: str, permission: str) -> dict[str, Any]:
        """Bring an existing team up to the grant `create_team` would give it now.

        Needed because `ensure_team` only ever created: a team that predates a
        change to the payload above keeps whatever it was born with, and Gitea has
        no notion of reconciling one. Both live `reconcilers` teams were created
        before `includes_all_repositories` was set, so without this the fix would
        apply to organizations that do not exist yet and to no others.

        WIDENS, NEVER NARROWS, and the asymmetry is deliberate: this is the bot's
        own team and the declaration says what it should hold. Narrowing someone's
        access from a config edit is the kind of change that should require a
        human noticing, so nothing here removes a unit or a repository.
        """
        return self._request(
            "PATCH",
            f"/teams/{team_id}",
            json={
                "name": name,
                "permission": permission,
                "can_create_org_repo": True,
                "units_map": {unit: permission for unit in TEAM_UNITS},
                "includes_all_repositories": True,
            },
        )

    def add_team_member(self, team_id: int, username: str) -> dict[str, Any]:
        """Add an account to a team. Idempotent on Gitea's side -- re-adding answers 204."""
        return self._request("PUT", f"/teams/{team_id}/members/{username}")

    def list_runners(self) -> list[dict[str, Any]]:
        """Every Actions runner registered on the instance.

        Instance scope deliberately: a runner registered at organisation or
        repository level still runs on this node and still consumes its memory, so
        a listing that could not see one would report an empty fleet over a
        populated one.

        `read:admin` is already in the grant -- this endpoint sits under the same
        admin router as `list_orgs`, verified 200 before the method existed.
        """
        return list(self._paginate("/admin/actions/runners", key="runners"))

    def list_hooks(self, owner: str, name: str) -> list[dict[str, Any]]:
        """Every webhook on a repository. On the TOKEN class, unlike every write below.

        THE READ AND THE WRITE SIT ON DIFFERENT CREDENTIALS HERE, which is not the
        shape `edit_repo` has, so it is measured rather than assumed. Asking all
        three on 2026-09-04, on both `personal/resume` and `teledyne/fae-brain` so
        the answer is not one repository's provenance (lesson-425):

            GET as admin token           -> 200, both repositories
            GET as bot token             -> 403 "owner or a collaborator with admin
                                            write", both repositories
            GET as superadmin basic auth -> 200, both repositories

        So the admin token's `read:repository` reaches the listing while its lack of
        `write:repository` stops at the create -- and this method belongs here, on
        the class the plan's other reads already use. Putting it on the basic-auth
        class would make an ordinary plan-only run depend on the admin password,
        which `gitea_reconcile` deliberately reads only when work is planned.

        The bot cannot read them at all. That is the same repo-admin gate as
        `edit_repo`, and the reason the plan reads the forge with `admin`.
        """
        return self._request("GET", f"/repos/{owner}/{name}/hooks") or []


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

    def delete_repo(self, owner: str, name: str) -> bool:
        """Delete a repository. True if it was there, False if it already was not.

        ON THIS CLASS RATHER THAN THE TOKEN CLIENT, and that placement is the
        safety property of the whole drop-empty path. Measured against live prod
        2026-09-02, cheapest privilege first:

            DELETE as bot token             -> 403 "user should be the owner of the repo"
            DELETE as admin token           -> 403 required=[write:repository]
            DELETE as superadmin basic auth -> 204

        Two 403s from two DIFFERENT layers -- permission and scope -- which is why
        the body is read rather than the status code. The obvious fix, widening the
        admin token with `write:repository`, is the wrong one: any credential that
        can delete an empty repository can delete a populated one, so it would buy
        a permanent delete capability on the reconciler's own token in exchange for
        removing three shells once. That capability is what #1076 refuses
        structurally, and a scope guard would not have objected -- the superset
        check passes on any widening.

        Basic auth is already the documented path for what Gitea refuses to tokens
        (`revoke_token` above), and ADR-062 keeps machine credentials reversible in
        SOPS precisely so automation can use them. It grants nothing durable.

        IDEMPOTENT BY 404, same contract as `revoke_token`: a name that matches
        nothing is the desired end state, not an error.
        """
        try:
            self._request("DELETE", f"/repos/{owner}/{name}")
        except GiteaError as exc:
            if exc.status_code == 404:
                return False
            raise
        return True

    def edit_repo(self, owner: str, name: str, settings: Mapping[str, Any]) -> dict[str, Any]:
        """Set repository settings -- merge styles, branch cleanup, optional units.

        ON THIS CLASS, and the measurement that put it here is more interesting than
        the two that came before it. Same probe shape as `delete_repo` (a no-op
        PATCH handing back the value the read had just returned), run against all
        three declared repositories on 2026-09-04:

            PATCH as admin token           -> 403 required=[write:repository]   (x3)
            PATCH as bot token             -> 403 "owner or a collaborator with
                                              admin write", on teledyne/fae-brain
                                              and personal/resume
            PATCH as bot token             -> 200, on teledyne/openkm-brain
            PATCH as superadmin basic auth -> 200                               (x3)

        THE BOT'S ONE SUCCESS IS NOT A CAPABILITY, and reading it as one is the trap
        this docstring exists to close. `openkm-brain` is the empty shell the BOT
        created, and Gitea makes a repository's creator its admin; the other two were
        migrated by the superadmin, so the bot holds only the `reconcilers` team's
        `write`. Gitea gates repository editing on repo-ADMIN, which a `write` team
        does not confer -- so the bot's answer tracks the PROVENANCE of each
        repository, not its own grant.

        Which makes this the sampling version of lesson-425: a probe that measures a
        single target measures that target's history. Had it run only on
        `openkm-brain` it would have "established" that the bot may configure
        repositories, and the reconciler would then have failed on exactly the
        repositories that matter -- the migrated ones, which are all of them that
        hold content.

        Widening the admin token with `write:repository` is the same wrong fix
        `delete_repo` refuses: that scope is a standing DELETE capability, bought
        permanently to set a merge style. Granting the team repo-admin is wrong in
        the other direction -- it would let the machine identity reconfigure and
        delete every repository in the organization, which is the concentration
        ADR-065 D1 exists to avoid.

        `settings` is passed through as Gitea's own `EditRepoOption` field names, so
        the declaration and the API speak one vocabulary and no mapping layer can
        drift between them. NOT idempotent-by-404: a PATCH against an absent
        repository is a caller error, and `plan_reconcile` never schedules one.
        """
        return self._request("PATCH", f"/repos/{owner}/{name}", json=dict(settings))

    def create_hook(self, owner: str, name: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Create a repository webhook. Same credential table as `edit_repo`, re-measured.

        Not inherited from that measurement -- asked directly, on 2026-09-04, both
        repositories, creating and immediately deleting a hook pointing at an
        unroutable URL so nothing was ever delivered:

            POST as admin token           -> 403 required=[write:repository]
            POST as bot token             -> 403 "owner or a collaborator with admin
                                              write of a repository"
            POST as superadmin basic auth -> 201

        The probe deliberately sent NO secret. A capability question does not need
        one, and a delete that failed would then have left an unauthenticated
        endpoint registered on a real repository rather than a signed one.

        `payload` is Gitea's own `CreateHookOption`, passed through unmapped for the
        same reason `edit_repo` passes `EditRepoOption` through: one vocabulary from
        the YAML key to the wire, with nothing in between free to drift.
        """
        return self._request("POST", f"/repos/{owner}/{name}/hooks", json=dict(payload))

    def edit_hook(self, owner: str, name: str, hook_id: int, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Update a webhook in place, preserving its id and therefore its delivery history.

        CALLERS MUST SEND THE WHOLE `config`, SECRET INCLUDED, on every update. Gitea's
        `EditHookOption.config` is a map, and whether omitting a key leaves it alone or
        clears it is a question this codebase has NOT measured. Rather than answer it,
        the caller is built so the question cannot arise: `gitea_repos.ensure_webhook`
        sends the full config every time.

        That is not fastidiousness. If an omitted `secret` cleared it, the hook would
        keep delivering and n8n's `multi-forge-sync` would reject every delivery for a
        failed signature -- and its rejection path answers HTTP 200 and drops the event
        silently. The forge's delivery log would stay green over an integration that
        had stopped working. Sending the secret unconditionally costs one field.
        """
        return self._request("PATCH", f"/repos/{owner}/{name}/hooks/{hook_id}", json=dict(payload))

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

    def delete_runner(self, runner_id: int) -> bool:
        """Deregister a runner. True if it was there, False if it already was not.

        ON THIS CLASS, not the token client, for exactly the reason `delete_repo`
        gives: the admin token would need `write:admin` to reach this endpoint, and
        any credential that can deregister a runner holds that capability
        permanently. Buying a standing delete on a long-lived reconciler credential
        to remove a stale record occasionally is the trade #1076 refuses
        structurally -- and a superset scope guard would not object to the widening,
        which is what makes the refusal a design choice rather than a check.

        Idempotent by 404, and the discrimination is real rather than assumed:
        measured 2026-09-03 against live prod, a non-existent id answers
        `{"message":"Runner not found"}` -- a SEMANTIC 404 from a wired route, not
        the router's `404 page not found`. Reading the body is what tells "already
        gone" apart from "this endpoint does not exist on this version", and those
        two call for opposite reactions.
        """
        try:
            self._request("DELETE", f"/admin/actions/runners/{runner_id}")
        except GiteaError as exc:
            if exc.status_code == 404:
                return False
            raise
        return True
