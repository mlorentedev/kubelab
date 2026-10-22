"""AUTH-004 AC2: each app's live privilege follows the declared groups, and is enforced at all.

Two defects this pins, both measured on 2026-09-24 by the first `make auth-review`:

- Grafana's role path returned 'Viewer' from the ID token, which carries no
  `groups` under Authelia 4.39, so Grafana would never read UserInfo. The Viewer
  actually measured had a second cause that hid this one: the auth proxy logged
  users in before OAuth ran (lesson-458, tests/test_grafana_login_door.py).
- Argo CD read `groups` from the ID token only, so `g, admins, role:admin` matched
  nobody and every SSO user fell to `role:readonly`.

And the reconciliation that makes a demotion take effect in a session already open.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import jmespath  # type: ignore[import-untyped]
import pytest
import yaml

from toolkit.features.access_review import (
    ADMIN,
    ADMIN_GROUP,
    ARGOCD_RBAC_CASES,
    ARGOCD_TOKEN_LIFESPAN,
    OPERATOR,
    OPERATOR_GROUP,
    VIEWER,
    Account,
    GiteaTiers,
    GrafanaTiers,
    OpenWebUITiers,
    ReviewError,
    argocd_image,
    argocd_rbac_disagreements,
    argocd_tier_findings,
    declared_tiers,
    idp_groups_drift,
    reconcile,
    review,
)

REPO = Path(__file__).resolve().parent.parent
COMMON = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())


# --------------------------------------------------------------------------- the declaration


def test_the_declared_tiers_come_from_the_groups() -> None:
    """ADR-062 D2 (amended by AUTH-011): `admins` administer, `users` operate, anyone
    else only reads."""
    tiers = declared_tiers(COMMON)
    assert tiers["manu"] == ADMIN, "the superadmin is in admins"
    assert tiers["testuser"] == VIEWER, "the e2e fixture is in neither group"
    assert tiers[COMMON["apps"]["auth"]["identities"]["machine"]] == VIEWER, "the machine identity only reads"


def test_every_declared_identity_is_judged_and_the_machine_ones_are_never_admins() -> None:
    """Every account in `apps.auth.identities` is declared, not only `machine`.

    Measured 2026-09-26: TOOL-080 added `reviewer: mentor`, and the prod review
    reported it `undeclared` because only the `machine` key was read.
    """
    from toolkit.features.configuration import resolve_user_identity

    tiers = declared_tiers(COMMON)
    users = COMMON["apps"]["services"]["security"]["authelia"]["users"]
    humans = {resolve_user_identity(u, COMMON) for u in users}
    for role, name in COMMON["apps"]["auth"]["identities"].items():
        assert name in tiers, f"identity {role}={name} is not declared to the review"
        if name not in humans:
            assert tiers[name] == VIEWER, f"{role}={name} is no Authelia user, so it holds no tier above reading"


def test_the_role_account_operates_and_never_administers() -> None:
    """ADR-062 D1: a role account is impersonal, so it holds no administrative power.

    `operator` sat in `admins` until AUTH-004 AC2 step 2, which made the tier
    enforced first and then took it out. AUTH-011 gave it the operating tier.
    """
    operator = COMMON["apps"]["auth"]["identities"]["operator"]
    assert declared_tiers(COMMON)[operator] == OPERATOR, (
        f"the role account {operator!r} must be in {OPERATOR_GROUP!r} only"
    )


def test_every_app_spells_the_admin_group_the_same_way() -> None:
    """The group name is a literal in three consumers; they must agree with the review."""
    grafana = (REPO / "infra/k8s/base/services/grafana-config/grafana.env").read_text()
    argocd = yaml.safe_load((REPO / "infra/helm/argocd/values.yaml").read_text())["configs"]["rbac"]["policy.csv"]
    gitea = (REPO / "infra/ansible/roles/beelink_services/files/gitea-bootstrap.sh").read_text()
    assert f"'{ADMIN_GROUP}'" in grafana
    assert f"'{OPERATOR_GROUP}'" in grafana
    assert re.search(rf"^\s*g,\s*{ADMIN_GROUP},\s*role:admin\s*$", argocd, re.M)
    assert re.search(rf"^\s*g,\s*{OPERATOR_GROUP},\s*role:operator\s*$", argocd, re.M)
    assert f'OIDC_ADMIN_GROUP="{ADMIN_GROUP}"' in gitea


# --------------------------------------------------------------------------- enforcement


def _role_paths() -> list[tuple[str, str]]:
    """Every Grafana role path in the repo: the K8s env files and the Compose stacks."""
    key = "GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH="
    found = []
    for path in REPO.glob("infra/k8s/**/grafana*.env"):
        for line in path.read_text().splitlines():
            if line.startswith(key):
                found.append((str(path.relative_to(REPO)), line[len(key) :].strip()))
    for path in REPO.glob("infra/stacks/**/grafana/compose*.yml"):
        for service in (yaml.safe_load(path.read_text()).get("services") or {}).values():
            for entry in service.get("environment") or []:
                if isinstance(entry, str) and entry.startswith(key):
                    found.append((str(path.relative_to(REPO)), entry[len(key) :].strip()))
    return found


def test_every_role_path_is_found() -> None:
    assert len(_role_paths()) >= 2, _role_paths()


def _grafana_role(expr: str, source: dict[str, Any]) -> str:
    """Grafana 13.0.2's `searchRole` for one source: the path on the source's JSON, and
    if that finds nothing, the path again on `{"groups": []}`, a list the caller
    hardcodes as empty (`extractRoleAndAdminOptional(data.rawJSON, []string{})`)."""
    empty: dict[str, Any] = {"groups": []}
    for doc in (source, empty):
        try:
            found = jmespath.search(expr, doc)
        except jmespath.exceptions.JMESPathError:
            found = None  # Grafana treats an evaluation error as "not found"
        if isinstance(found, str) and found:
            return found
    return ""


@pytest.mark.parametrize(("where", "expr"), _role_paths())
def test_the_role_path_defers_to_userinfo_when_the_id_token_has_no_groups(where: str, expr: str) -> None:
    """Grafana evaluates the ID token first and moves on only when the result is empty.

    An expression that ends in a default returns it from the ID token, and UserInfo,
    where Authelia puts `groups`, is never read. Grafana also re-runs the path on an
    EMPTY groups list, so an expression that answers `[]` with 'Viewer' does the same
    (lesson-461): every SSO user was Viewer in staging on 2026-09-24.
    """
    id_token = {"sub": "x", "email": "a@b"}
    assert _grafana_role(expr, id_token) == "", f"{where}: the ID token must not decide the role"
    assert _grafana_role(expr, {"groups": []}) == "", f"{where}: an empty list must not decide the role either"


@pytest.mark.parametrize(("where", "expr"), _role_paths())
@pytest.mark.parametrize(
    ("groups", "role"),
    [([ADMIN_GROUP, OPERATOR_GROUP], "Admin"), ([OPERATOR_GROUP], "Editor"), (["e2e"], "Viewer")],
)
def test_the_role_path_maps_each_tier(where: str, expr: str, groups: list[str], role: str) -> None:
    """AUTH-011: `users` operate, so they edit dashboards; `admins` wins over `users`."""
    assert _grafana_role(expr, {"groups": groups}) == role, where


@pytest.mark.parametrize(
    ("tiers", "expected"),
    [
        (GiteaTiers, {ADMIN: "admin", OPERATOR: "user", VIEWER: "user"}),
        (GrafanaTiers, {ADMIN: "Admin", OPERATOR: "Editor", VIEWER: "Viewer"}),
        # A login with neither group is refused (OAUTH_ALLOWED_ROLES), and `pending` is
        # the role with no access (v0.12.0 `VERIFIED_USER_ROLES = {'user', 'admin'}`).
        (OpenWebUITiers, {ADMIN: "admin", OPERATOR: "user", VIEWER: "pending"}),
    ],
)
def test_each_app_maps_every_declared_tier(tiers: Any, expected: dict[str, str]) -> None:
    """Gitea has no tier between admin and user: a normal user already owns and pushes."""
    assert tiers.tier_map == expected


def test_argo_cd_reads_groups_from_userinfo() -> None:
    """Otherwise `g, admins, role:admin` matches nobody and everyone is read-only."""
    cm = yaml.safe_load((REPO / "infra/helm/argocd/values.yaml").read_text())["configs"]["cm"]
    oidc = yaml.safe_load(cm["oidc.config"])
    assert oidc.get("enableUserInfoGroups") is True
    grafana = (REPO / "infra/k8s/base/services/grafana-config/grafana.env").read_text()
    match = re.search(r"GF_AUTH_GENERIC_OAUTH_API_URL=https://[^/]+(\S+)", grafana)
    assert match, "Grafana's UserInfo URL is not declared"
    userinfo_path = match.group(1)
    assert oidc.get("userInfoPath") == userinfo_path, "Argo CD must ask the same UserInfo endpoint Grafana does"
    assert oidc.get("userInfoCacheExpiration"), "the cache keeps UserInfo from being asked on every request"


# --------------------------------------------------------------------------- the review


class FakeApp:
    """A tier store that answers reads and records edits, like an app's API."""

    def __init__(self, tiers: Any, accounts: list[Account], accept: bool = True, answer: bool = True) -> None:
        self.tiers, self.accounts, self.accept, self.answer = tiers, {a.user: a for a in accounts}, accept, answer
        self.edits: list[tuple[str, str]] = []
        self.tier_map = tiers.tier_map
        self.settles_on_next_login = getattr(tiers, "settles_on_next_login", False)

    def read(self, base_url: str, auth: str) -> list[Account]:
        return list(self.accounts.values())

    def set_tier(self, base_url: str, auth: str, account: Account, tier: str) -> bool:
        self.edits.append((account.user, tier))
        if self.accept:
            self.accounts[account.user] = Account(account.user, tier, account.ref)
        return self.answer  # a 200 unless told otherwise: the read-back is what decides


DECLARED = {"manu": ADMIN, "operator": OPERATOR, "hefesto": VIEWER}


def test_review_judges_each_account() -> None:
    accounts = [Account("manu", "admin"), Account("operator", "admin"), Account("stranger", "user")]
    by_user = {f.user: f.status for f in review("gitea", DECLARED, accounts, GiteaTiers)}
    assert by_user == {"manu": "ok", "operator": "drift", "stranger": "undeclared"}


def test_apply_fixes_the_drift_and_proves_it_by_reading_back() -> None:
    app = FakeApp(GiteaTiers, [Account("manu", "admin"), Account("operator", "admin"), Account("stranger", "admin")])
    findings = {f.user: f for f in reconcile("gitea", DECLARED, app, "http://x", "a:b", apply=True)}
    assert findings["operator"].status == "fixed" and findings["operator"].live == "user"
    assert app.edits == [("operator", "user")], "only the drifted, declared account may be edited"
    assert findings["stranger"].status == "undeclared", "an undeclared account is reported, never touched"


def test_a_200_that_changed_nothing_is_a_failure() -> None:
    app = FakeApp(GiteaTiers, [Account("operator", "admin")], accept=False)
    [finding] = reconcile("gitea", DECLARED, app, "http://x", "a:b", apply=True)
    assert finding.status == "failed"


def test_without_apply_nothing_is_edited() -> None:
    app = FakeApp(GiteaTiers, [Account("operator", "admin")])
    [finding] = reconcile("gitea", DECLARED, app, "http://x", "a:b", apply=False)
    assert finding.status == "drift" and app.edits == []


# --------------------------------------------------------------------------- the app calls


class Recorder:
    def __init__(self, response: tuple[int, Any] = (200, {})) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.response = response

    def __call__(self, method: str, url: str, body: Any, auth: str) -> tuple[int, Any]:
        self.calls.append((method, url, body))
        return self.response


def test_gitea_edit_sends_back_the_live_login_name() -> None:
    """Gitea 1.25.5 writes `login_name` unconditionally, and for an SSO account it is
    the IdP's `sub`. Sending the username would detach the account from its SSO login."""
    request = Recorder()
    account = Account("operator", "admin", {"login_name": "d439346a-sub", "source_id": 1})
    GiteaTiers(request).set_tier("http://g", "a:b", account, "user")
    method, url, body = request.calls[0]
    assert (method, url) == ("PATCH", "http://g/api/v1/admin/users/operator")
    assert body == {"login_name": "d439346a-sub", "source_id": 1, "admin": False}


def test_grafana_revokes_the_sessions_instead_of_editing_the_role() -> None:
    """With OIDC as the only login, Grafana writes the role from `groups` at each login
    and refuses to edit it (`ErrCannotChangeRoleForExternallySyncedUser`). Revoking the
    sessions makes the next request sign in again, which is when the role changes."""
    request = Recorder()
    GrafanaTiers(request).set_tier("http://gr", "a:b", Account("operator", "Admin", {"user_id": 7}), "Viewer")
    assert request.calls == [("POST", "http://gr/api/admin/users/7/logout", None)]


def test_a_revoked_grafana_session_is_bounded_not_fixed() -> None:
    """The stored role still reads Admin after the revoke: `fixed` would be false,
    and `failed` would fail a review that did the only thing Grafana allows."""
    app = FakeApp(GrafanaTiers, [Account("operator", "Admin", {"user_id": 7})], accept=False)
    [finding] = reconcile("grafana", DECLARED, app, "http://x", "a:b", apply=True)
    assert finding.status == "bounded" and finding.live == "Admin"
    assert "revoked" in finding.detail


def test_a_refused_revoke_is_a_failure() -> None:
    app = FakeApp(GrafanaTiers, [Account("operator", "Admin", {"user_id": 7})], accept=False, answer=False)
    [finding] = reconcile("grafana", DECLARED, app, "http://x", "a:b", apply=True)
    assert finding.status == "failed"


def test_the_break_glass_account_is_never_edited() -> None:
    """A declaration that dropped the superadmin from `admins` must not have the review
    demote the only credential that can repair it."""
    app = FakeApp(GiteaTiers, [Account("manu", "admin"), Account("operator", "admin")])
    declared = {"manu": VIEWER, "operator": VIEWER}
    findings = {f.user: f for f in reconcile("gitea", declared, app, "u", "a", True, "manu")}
    assert findings["manu"].status == "refused"
    assert ("manu", "user") not in app.edits
    assert findings["operator"].status == "fixed"


def test_a_local_break_glass_account_is_admin_not_undeclared() -> None:
    """Grafana's break-glass account belongs to nobody in Authelia (#951). Reported as
    undeclared, it would fail every review; it is the admin the review runs as."""
    app = FakeApp(GrafanaTiers, [Account("breakglass", "Admin"), Account("operator", "Viewer")])
    findings = {f.user: f for f in reconcile("grafana", DECLARED, app, "u", "a", False, "breakglass")}
    assert findings["breakglass"].status == "ok" and findings["breakglass"].declared == "Admin"
    demoted = FakeApp(GrafanaTiers, [Account("breakglass", "Viewer")])
    [finding] = reconcile("grafana", DECLARED, demoted, "u", "a", True, "breakglass")
    assert finding.status == "refused" and demoted.edits == []


def test_gitea_read_takes_the_link_fields_from_the_api_payload_and_pages() -> None:
    """The fields the edit sends back come from the real payload shape, across pages."""
    pages = {
        1: [{"login": f"u{i}", "is_admin": False, "login_name": f"sub-{i}", "source_id": 1} for i in range(50)],
        2: [{"login": "operator", "is_admin": True, "login_name": "d439-sub", "source_id": 1}],
    }

    def request(method: str, url: str, body: Any, auth: str) -> tuple[int, Any]:
        return 200, pages.get(int(url.rsplit("page=", 1)[1]), [])

    accounts = {a.user: a for a in GiteaTiers(request).read("http://g", "a:b")}
    assert len(accounts) == 51, "the second page was not read"
    assert accounts["operator"].ref == {"login_name": "d439-sub", "source_id": 1}
    assert accounts["operator"].tier == "admin"


@pytest.mark.parametrize(
    ("live_cm", "enforced"),
    [
        ("name: x\nenableUserInfoGroups: true\nuserInfoCacheExpiration: 5m\n", True),
        ("name: x\nrequestedScopes: [openid, groups]\n", False),
    ],
)
def test_argo_cd_is_judged_on_the_live_hub_config(live_cm: str, enforced: bool) -> None:
    """Merged is not deployed: the bound comes from the running argocd-cm."""
    from toolkit.features.access_review import argocd_group_bound

    bound = argocd_group_bound(lambda: live_cm)
    assert bound.startswith("groups from UserInfo") is enforced
    if enforced:
        assert ARGOCD_TOKEN_LIFESPAN in bound, "the bound is the token lifespan"
        assert "5m" not in bound, "the UserInfo cache is not the bound (#1861)"


def test_the_argo_cd_bound_is_the_token_lifespan_authelia_actually_issues() -> None:
    """Measured 2026-09-26 (#1861): after `operator` left `admins`, Argo CD kept
    showing `admins` well past its 5m UserInfo cache. A refetch reuses the stored
    access token, and Authelia answers with the groups captured when that token was
    issued, so a demotion reaches Argo CD only when the token expires: 1h later, at
    the silent re-login. The stated bound is Authelia's default lifespan, which holds
    only while neither environment configures `lifespans` and the argocd client
    names none. Set one, and this fails until ARGOCD_TOKEN_LIFESPAN says the same."""
    for path in (
        REPO / "infra/k8s/base/services/authelia-config/configuration.yml",
        REPO / "infra/k8s/overlays/prod/authelia-config/configuration.yml",
    ):
        oidc = (yaml.safe_load(path.read_text()).get("identity_providers") or {}).get("oidc") or {}
        assert "lifespans" not in oidc, f"{path.relative_to(REPO)} sets lifespans: update ARGOCD_TOKEN_LIFESPAN"
    clients = COMMON["apps"]["services"]["security"]["authelia"]["oidc_clients"]
    argocd = next(c for c in clients if c["client_id"] == "argocd")
    assert "lifespan" not in argocd, "the argocd client names a lifespan: update ARGOCD_TOKEN_LIFESPAN"
    # The 1h is Authelia 4.39's default, so it only holds for the image we pin: an
    # upgrade to another minor must re-measure the default before this passes again.
    image = COMMON["apps"]["services"]["security"]["authelia"]["image"]
    assert image.split(":", 1)[1].startswith("4.39."), (
        f"Authelia is pinned to {image}: re-measure its default token lifespan, then update ARGOCD_TOKEN_LIFESPAN"
    )
    assert ARGOCD_TOKEN_LIFESPAN == "1h", "Authelia 4.39's default access and ID token lifespan"


# --------------------------------------------------------------------------- the IdP's live groups (AUTH-014)

#: Two distinct fake hashes, one per side, so a leak from either is caught.
RENDERED_HASH = "$argon2id$v=19$m=65536,t=3,p=4$rendered-hash-must-not-leak"
LIVE_HASH = "$argon2id$v=19$m=65536,t=3,p=4$live-hash-must-not-leak"
RENDERED_GROUPS = {"manu": ["admins", "users"], "operator": ["users"]}


def _users_db(groups: dict[str, list[str]], password: str, emails: dict[str, str] | None = None) -> str:
    emails = emails or {}
    users = {
        u: {
            "disabled": False,
            "displayname": u,
            "password": password,
            "email": emails.get(u, f"{u}@example.com"),
            "groups": g,
        }
        for u, g in groups.items()
    }
    return yaml.safe_dump({"users": users})


def _no_hash_in(findings: list[Any]) -> None:
    text = repr(findings)
    assert "must-not-leak" not in text, "a password hash reached a finding"


@pytest.mark.parametrize(
    ("live", "lagging"),
    [
        # Measured 2026-09-29 in staging: operator declared ['users'], served ['admins', 'users'].
        ({"manu": ["admins", "users"], "operator": ["admins", "users"]}, {"operator"}),
        ({"manu": ["admins", "users"]}, {"operator"}),
        ({**RENDERED_GROUPS, "ghost": ["admins"]}, {"ghost"}),
    ],
    ids=["other-groups", "declared-user-missing", "live-user-undeclared"],
)
def test_idp_groups_drift_when_the_live_users_database_lags(live: dict[str, list[str]], lagging: set[str]) -> None:
    """A merge that changes `groups` reaches Authelia only through `make apply-secrets`,
    and Argo CD reports Synced either way (#1911). Every difference is one that
    command removes, since it renders the Secret whole, so every one is `drift`."""
    findings, stale = idp_groups_drift(
        _users_db(RENDERED_GROUPS, RENDERED_HASH), lambda: _users_db(live, LIVE_HASH), "staging"
    )
    assert stale == lagging
    drifts = [f for f in findings if f.status == "drift"]
    assert {f.user for f in drifts} == lagging
    assert all(f.service == "authelia" and "make apply-secrets ENV=staging" in f.detail for f in drifts)
    _no_hash_in(findings)


def test_idp_email_that_lags_holds_the_user_back() -> None:
    """Open WebUI accounts are keyed to a login by the email the declaration renders.
    Until `make apply-secrets` lands a moved email, the account holding it still
    belongs to the old user, so a correction would hand one user's tier to another."""
    live = _users_db(RENDERED_GROUPS, LIVE_HASH, {"operator": "old-operator@example.com"})
    findings, stale = idp_groups_drift(_users_db(RENDERED_GROUPS, RENDERED_HASH), lambda: live, "prod")
    assert stale == {"operator"}
    [drift] = [f for f in findings if f.status == "drift"]
    assert (drift.user, drift.service) == ("operator", "authelia")
    assert "email" in drift.detail and "make apply-secrets ENV=prod" in drift.detail
    assert "old-operator@example.com" not in repr(findings)
    _no_hash_in(findings)


def test_idp_groups_that_match_are_ok_whatever_their_order() -> None:
    live = {"manu": ["users", "admins"], "operator": ["users"]}
    findings, stale = idp_groups_drift(
        _users_db(RENDERED_GROUPS, RENDERED_HASH), lambda: _users_db(live, LIVE_HASH), "prod"
    )
    assert stale == frozenset()
    assert {(f.service, f.user, f.status) for f in findings} == {
        ("authelia", "manu", "ok"),
        ("authelia", "operator", "ok"),
    }


def test_no_password_hash_reaches_a_finding_even_from_a_malformed_database() -> None:
    """PyYAML quotes about 30 characters around the error, so where the error is an
    unclosed hash, the start of that hash is in the message."""
    broken = f'users:\n  operator:\n    password: "must-not-leak{LIVE_HASH}\n'
    findings, stale = idp_groups_drift(_users_db(RENDERED_GROUPS, RENDERED_HASH), lambda: broken, "prod")
    assert stale == frozenset()
    assert [(f.service, f.status) for f in findings] == [("authelia", "failed")]
    _no_hash_in(findings)


def test_an_unreadable_users_secret_is_a_failure_not_a_pass() -> None:
    """Staging is on-demand, so the spoke can be off. That is `failed`, which exits 1,
    never an empty comparison that reads as `ok`."""

    def unreachable() -> str:
        raise ReviewError("the staging authelia-users Secret is unreadable: connection refused")

    findings, stale = idp_groups_drift(_users_db(RENDERED_GROUPS, RENDERED_HASH), unreachable, "staging")
    assert stale == frozenset()
    [finding] = findings
    assert (finding.service, finding.status) == ("authelia", "failed") and "unreadable" in finding.detail


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param(f'"{LIVE_HASH}"', id="user-is-a-string"),
        pytest.param('{groups: "users"}', id="groups-is-a-string"),
    ],
)
def test_a_malformed_user_entry_is_a_failure_not_a_crash(entry: str) -> None:
    """Valid YAML with the wrong shape must still end in a `failed` finding, never an
    exception that aborts the review, and never a string read as a list of letters."""
    live = f"users:\n  manu: {{groups: [admins, users]}}\n  operator: {entry}\n"
    findings, stale = idp_groups_drift(_users_db(RENDERED_GROUPS, RENDERED_HASH), lambda: live, "prod")
    assert stale == frozenset()
    assert [(f.service, f.status) for f in findings] == [("authelia", "failed")]
    _no_hash_in(findings)


@pytest.mark.parametrize(
    "outcome",
    [
        pytest.param(subprocess.CompletedProcess([], 0, "not base64 at all!", ""), id="not-base64"),
        pytest.param(subprocess.CompletedProcess([], 0, "//79", ""), id="not-utf8"),
        pytest.param(subprocess.TimeoutExpired(["kubectl"], 30), id="api-server-hangs"),
    ],
)
def test_a_live_secret_that_cannot_be_decoded_is_a_review_error(
    monkeypatch: pytest.MonkeyPatch, outcome: subprocess.CompletedProcess[str] | subprocess.TimeoutExpired
) -> None:
    """The live read is the one step that talks to a cluster, so every way it can go
    wrong has to become a ReviewError, which `idp_groups_drift` turns into `failed`."""
    from toolkit.features import access_review

    calls: list[dict[str, Any]] = []

    def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(kwargs)
        if isinstance(outcome, subprocess.TimeoutExpired):
            raise outcome
        return outcome

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(ReviewError, match="authelia-users"):
        access_review._live_users_database("prod")
    assert calls and calls[0].get("timeout"), "a hung API server must not block the review"


def test_a_stale_user_is_neither_edited_nor_revoked_and_reads_drift() -> None:
    """A revoke is undone at the next login, which writes the role from the stale
    groups: `bounded` would promise a convergence that cannot happen (#1911)."""
    app = FakeApp(GrafanaTiers, [Account("operator", "Admin", {"user_id": 7})], accept=False)
    hint = "the IdP still serves the old groups: run `make apply-secrets ENV=staging`"
    [finding] = reconcile(
        "grafana", DECLARED, app, "u", "a", apply=True, stale=frozenset({"operator"}), stale_detail=hint
    )
    assert app.edits == [], "a stale user must not be revoked"
    assert finding.status == "drift" and finding.detail == hint


def test_a_stale_user_does_not_hold_back_the_others() -> None:
    app = FakeApp(GiteaTiers, [Account("operator", "admin"), Account("hefesto", "admin")])
    findings = {
        f.user: f
        for f in reconcile(
            "gitea", DECLARED, app, "u", "a", apply=True, stale=frozenset({"operator"}), stale_detail="x"
        )
    }
    assert app.edits == [("hefesto", "user")]
    assert findings["hefesto"].status == "fixed" and findings["operator"].status == "drift"


def test_a_stale_break_glass_user_still_reads_refused() -> None:
    app = FakeApp(GiteaTiers, [Account("manu", "admin")])
    [finding] = reconcile(
        "gitea", {"manu": VIEWER}, app, "u", "a", True, "manu", stale=frozenset({"manu"}), stale_detail="x"
    )
    assert finding.status == "refused" and app.edits == []


def _wire_review_env(monkeypatch: pytest.MonkeyPatch, read_live: Any) -> list[tuple[str, bool, frozenset[str], str]]:
    """Stub everything `review_env` reaches except the IdP comparison, and record
    each `reconcile` call as (service, apply, stale, detail)."""
    from contextlib import contextmanager

    from toolkit.features import access_review, break_glass, oidc_clients, secrets_manager

    monkeypatch.setattr(
        access_review, "_rendered_users_database", lambda env, root: _users_db(RENDERED_GROUPS, RENDERED_HASH)
    )
    monkeypatch.setattr(access_review, "_live_users_database", read_live)
    monkeypatch.setattr(oidc_clients, "load_values", lambda env, root: COMMON)
    monkeypatch.setattr(break_glass, "declarations", lambda values: {"grafana": {"secret": "s"}})
    monkeypatch.setattr(break_glass, "resolve", lambda env, service, root: (None, None, None))
    monkeypatch.setattr(break_glass, "secret_file", lambda *a: "f")
    monkeypatch.setattr(break_glass, "account_login", lambda decl, values: "breakglass")

    @contextmanager
    def url(env: str, plan: Any) -> Any:
        yield "http://grafana"

    monkeypatch.setattr(break_glass, "private_url", url)
    monkeypatch.setattr(secrets_manager.SecretsManager, "show_secret", lambda self, f, k: "pw")
    calls: list[tuple[str, bool, frozenset[str], str]] = []

    def fake_reconcile(service: str, *args: Any) -> list[Any]:
        calls.append((service, args[4], args[6], args[7]))
        return []

    monkeypatch.setattr(access_review, "reconcile", fake_reconcile)
    monkeypatch.setattr(access_review, "TIERS", {"grafana": GrafanaTiers})
    monkeypatch.setattr(access_review, "_live_argocd_oidc_config", lambda: "enableUserInfoGroups: true")
    monkeypatch.setattr(access_review, "_live_argocd_rbac", lambda: ("p, x", "role:readonly"))
    monkeypatch.setattr(access_review, "argocd_rbac_disagreements", lambda *a: [])
    return calls


def test_review_env_checks_the_idp_first_and_passes_the_lagging_users_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """The order is the fix: a user whose groups lag must be known before any app is
    reconciled, or the app would be revoked and report `bounded` (#1911)."""
    from toolkit.features import access_review

    live = {"manu": ["admins", "users"], "operator": ["admins", "users"]}
    calls = _wire_review_env(monkeypatch, lambda env: _users_db(live, LIVE_HASH))
    logged: list[str] = []
    findings = access_review.review_env("staging", REPO, apply=True, log=logged.append)

    assert findings[0].service == "authelia", "the IdP is judged before any app"
    assert [(f.user, f.status) for f in findings if f.status != "ok"] == [("operator", "drift")]
    [(service, apply, stale, detail)] = calls
    assert service == "grafana" and apply and stale == frozenset({"operator"})
    assert "make apply-secrets ENV=staging" in detail
    _no_hash_in(findings)
    assert not any("must-not-leak" in line for line in logged)


def test_review_env_corrects_nothing_when_the_idp_cannot_be_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the IdP's groups unknown, no user can be shown not to lag, so APPLY=1 must
    not revoke or edit anything: that would be the non-converging `bounded` again."""
    from toolkit.features import access_review

    def unreachable(env: str) -> str:
        raise ReviewError("the staging authelia-users Secret is unreadable: connection refused")

    calls = _wire_review_env(monkeypatch, unreachable)
    logged: list[str] = []
    findings = access_review.review_env("staging", REPO, apply=True, log=logged.append)

    assert (findings[0].service, findings[0].status) == ("authelia", "failed")
    [(service, apply, _stale, _detail)] = calls
    assert service == "grafana" and not apply, "the app is still reviewed, but never corrected"
    assert any("no correction" in line for line in logged)


@pytest.mark.parametrize(
    ("status", "exit_code"),
    [("ok", 0), ("fixed", 0), ("bounded", 0), ("drift", 1), ("undeclared", 1), ("failed", 1), ("refused", 1)],
)
def test_the_command_exits_1_on_every_finding_a_human_must_act_on(
    monkeypatch: pytest.MonkeyPatch, status: str, exit_code: int
) -> None:
    """A refused finding is a declaration that lost the break-glass account: the review
    will not fix it, so a green exit would hide the one thing only a human can repair."""
    from typer.testing import CliRunner

    from toolkit.cli.auth import app
    from toolkit.features import access_review
    from toolkit.features.access_review import Finding

    monkeypatch.setattr(
        access_review, "review_env", lambda *a, **k: [Finding("gitea", "manu", "admin", "user", status)]
    )
    result = CliRunner().invoke(app, ["review", "--env", "staging"])
    assert result.exit_code == exit_code, result.output


# --------------------------------------------------------------------------- Open WebUI


class ScriptedOpenWebUI:
    """Open WebUI's sign-in and user API, answering by route and recording each call."""

    def __init__(
        self, users: list[dict[str, Any]], signin: tuple[int, Any] | None = None, update_status: int = 200
    ) -> None:
        self.users = users
        self.signin = signin or (200, {"email": "breakglass@kubelab.live", "token": "tok"})
        self.update_status = update_status
        self.calls: list[tuple[str, str, Any, str]] = []

    def __call__(self, method: str, url: str, body: Any, auth: str) -> tuple[int, Any]:
        self.calls.append((method, url, body, auth))
        if url.endswith("/api/v1/auths/signin"):
            return self.signin
        if url.endswith("/api/v1/users/all"):
            return 200, {"users": self.users, "total": len(self.users)}
        return self.update_status, {"id": url.split("/")[-2]}


LOGINS = {"manu@mlorente.dev": "manu", "info@kubelab.live": "operator", "breakglass@kubelab.live": "breakglass"}
WEBUI_USERS = [
    {"id": "u1", "email": "Manu@mlorente.dev", "role": "admin"},
    {"id": "u2", "email": "info@kubelab.live", "role": "user"},
    {"id": "u0", "email": "breakglass@kubelab.live", "role": "admin"},
    {"id": "u9", "email": "someone@else.test", "role": "user"},
]


def test_open_webui_signs_in_by_email_and_keys_each_account_by_its_authelia_login() -> None:
    """Open WebUI holds no username: `name` is a display name its user can edit. The
    email is the OIDC claim Authelia sends, so it is the key back to the declaration."""
    app = ScriptedOpenWebUI(WEBUI_USERS)
    accounts = {a.user: a for a in OpenWebUITiers(app, LOGINS).read("http://w", "breakglass@kubelab.live:pw")}

    assert set(accounts) == {"manu", "operator", "breakglass", "someone@else.test"}
    assert accounts["operator"].tier == "user" and accounts["operator"].ref == {"id": "u2"}
    signin, listing = app.calls
    assert signin[:3] == (
        "POST",
        "http://w/api/v1/auths/signin",
        {"email": "breakglass@kubelab.live", "password": "pw"},
    )
    assert listing[:2] == ("GET", "http://w/api/v1/users/all") and listing[3] == "Bearer tok"


def test_open_webui_edits_the_role_under_the_break_glass_session() -> None:
    """v0.12.0 loads the user from its database on every request (`get_current_user`),
    so the edited role reaches a session already open on its next request."""
    app = ScriptedOpenWebUI(WEBUI_USERS)
    tiers = OpenWebUITiers(app, LOGINS)
    accounts = {a.user: a for a in tiers.read("http://w", "breakglass@kubelab.live:pw")}
    assert tiers.set_tier("http://w", "breakglass@kubelab.live:pw", accounts["operator"], "pending")
    assert app.calls[-1] == ("POST", "http://w/api/v1/users/u2/update", {"role": "pending"}, "Bearer tok")


def test_open_webui_reports_a_refused_edit_as_unfixed() -> None:
    """v0.12.0 takes `role` as any string (`UserUpdateForm`, `routers/users.py`), so
    `pending` is accepted; a refusal (the primary-admin guard) must not read as fixed."""
    app = ScriptedOpenWebUI(WEBUI_USERS, update_status=403)
    tiers = OpenWebUITiers(app, LOGINS)
    accounts = {a.user: a for a in tiers.read("http://w", "breakglass@kubelab.live:pw")}
    assert not tiers.set_tier("http://w", "breakglass@kubelab.live:pw", accounts["operator"], "pending")


@pytest.mark.parametrize(
    "signin",
    [
        (401, {}),
        (0, {}),
        (200, {"email": "someone@else.test", "token": "tok"}),
        (200, {"email": "breakglass@kubelab.live"}),
        (200, ["not", "an", "object"]),
    ],
    ids=["refused", "unreachable", "another-account", "no-token", "not-an-object"],
)
def test_an_open_webui_sign_in_that_opens_no_break_glass_session_is_a_review_error(signin: tuple[int, Any]) -> None:
    with pytest.raises(ReviewError, match="Open WebUI"):
        OpenWebUITiers(ScriptedOpenWebUI(WEBUI_USERS, signin), LOGINS).read("http://w", "breakglass@kubelab.live:pw")


def test_a_demoted_open_webui_account_is_fixed_as_pending_not_bounded() -> None:
    """Gitea's shape, not Grafana's: the role edit is the correction, and the read-back proves it.
    A later login with neither group is refused and leaves `pending` as it is."""
    app = FakeApp(OpenWebUITiers, [Account("operator", "user", {"id": "u2"})])
    [finding] = reconcile("open-webui", {"operator": VIEWER}, app, "http://x", "a:b", apply=True)
    assert (finding.status, finding.live) == ("fixed", "pending")
    assert app.edits == [("operator", "pending")]


def test_review_env_signs_open_webui_in_by_email_with_the_rendered_logins(monkeypatch: pytest.MonkeyPatch) -> None:
    """The email to login map is the users database Authelia is given, plus the local
    break-glass account, which belongs to no Authelia user (ADR-062 D4)."""
    from toolkit.features import access_review, break_glass

    _wire_review_env(monkeypatch, lambda env: _users_db(RENDERED_GROUPS, LIVE_HASH))
    monkeypatch.setattr(access_review, "TIERS", {"open-webui": OpenWebUITiers})
    decl = {"login": "breakglass", "email": "Breakglass@kubelab.live", "secret": "s"}
    monkeypatch.setattr(break_glass, "declarations", lambda values: {"open-webui": decl})
    seen: list[tuple[Any, str, str]] = []

    def record(service: str, declared: Any, tiers: Any, base_url: str, auth: str, *rest: Any) -> list[Any]:
        seen.append((tiers, auth, rest[1]))
        return []

    monkeypatch.setattr(access_review, "reconcile", record)
    access_review.review_env("prod", REPO, apply=False, log=lambda line: None)

    [(tiers, auth, protected)] = seen
    assert isinstance(tiers, OpenWebUITiers)
    assert auth == "Breakglass@kubelab.live:pw" and protected == "breakglass"
    assert tiers.logins == {
        "manu@example.com": "manu",
        "operator@example.com": "operator",
        "breakglass@kubelab.live": "breakglass",
    }


# --------------------------------------------------------------------------- how each account signs in


def test_grafana_reports_how_each_account_signs_in() -> None:
    """`GF_AUTH_OAUTH_ALLOW_INSECURE_EMAIL_LOOKUP` is a migration flag: it may come out
    only once every SSO identity is linked to Generic OAuth, or that identity's next
    login finds no link and no lookup and fails on its own row. The link is what the
    removal waits for, so the review shows it instead of leaving it to an ad hoc read."""
    users = [
        {"login": "testuser", "role": "Viewer", "userId": 4, "authLabels": ["Auth Proxy"]},
        {"login": "operator", "role": "Admin", "userId": 3, "authLabels": ["Generic OAuth"]},
        # The live break-glass row: seeded by the auth proxy, and still local, because
        # `errOnExternalUser` does not count the proxy as a provider (#951).
        {"login": "breakglass", "role": "Admin", "userId": 1, "authLabels": ["Auth Proxy"]},
        {"login": "seeded", "role": "Viewer", "userId": 9, "authLabels": []},
    ]
    accounts = {a.user: a for a in GrafanaTiers(Recorder((200, users))).read("http://gr", "a:b")}
    declared = {"testuser": VIEWER, "operator": ADMIN}
    findings = {f.user: f for f in review("grafana", declared, list(accounts.values()), GrafanaTiers)}

    assert findings["testuser"].detail == "sign-in: Auth Proxy"
    assert findings["operator"].detail == "sign-in: Generic OAuth"
    assert findings["breakglass"].detail == "sign-in: Auth Proxy"
    assert findings["seeded"].detail == "sign-in: local", "a row with no link at all"
    assert findings["testuser"].status == "ok", "the link is information, never a verdict"


# --------------------------------------------------------------------------- Argo CD RBAC, by Argo CD itself


def _shipped_rbac() -> dict[str, str]:
    return yaml.safe_load((REPO / "infra/helm/argocd/values.yaml").read_text())["configs"]["rbac"]


def _docker_or_skip() -> None:
    if shutil.which("docker") is None:
        if os.environ.get("CI"):
            pytest.fail("docker not on PATH in CI: the Argo CD RBAC went untested")
        pytest.skip("docker not on PATH: cannot run Argo CD (a skip is CANNOT CHECK, not OK)")


@pytest.mark.integration
def test_argo_cd_rbac_lets_users_operate_and_never_administer(docker_mount_dir: Path) -> None:
    """AUTH-011 AC1, asked of Argo CD's own evaluator with the pinned image.

    The cases are `ARGOCD_RBAC_CASES`, the matrix `make auth-review` judges the live
    hub with (#1876), so the shipped file and the served one answer the same questions."""
    _docker_or_skip()
    rbac = _shipped_rbac()
    wrong = argocd_rbac_disagreements(
        rbac["policy.csv"], rbac["policy.default"], argocd_image(COMMON), docker_mount_dir
    )
    assert not wrong, f"Argo CD disagrees with the declared tiers on: {wrong}"


@pytest.mark.integration
def test_a_policy_granting_users_delete_reads_drift(docker_mount_dir: Path) -> None:
    """#1876 AC3: the evaluator, not a CSV read, sees the widened operator tier."""
    _docker_or_skip()
    rbac = _shipped_rbac()
    widened = rbac["policy.csv"] + "p, role:operator, applications, delete, */*, allow\n"
    wrong = argocd_rbac_disagreements(widened, rbac["policy.default"], argocd_image(COMMON), docker_mount_dir)
    findings = {f.user: f for f in argocd_tier_findings(wrong)}
    assert findings[OPERATOR].status == "drift", findings
    assert "delete applications */*" in findings[OPERATOR].detail
    assert findings[ADMIN].status == findings[VIEWER].status == "ok"


def test_every_tier_is_judged_and_ok_without_a_disagreement() -> None:
    findings = argocd_tier_findings([])
    assert [(f.service, f.user, f.status) for f in findings] == [
        ("argocd", ADMIN, "ok"),
        ("argocd", OPERATOR, "ok"),
        ("argocd", VIEWER, "ok"),
    ]


def test_a_disagreement_is_drift_on_its_own_tier_and_names_the_first_tuple() -> None:
    granted = [c for c in ARGOCD_RBAC_CASES if c[0] == OPERATOR_GROUP and not c[-1]][:2]
    findings = {f.user: f for f in argocd_tier_findings(granted)}
    _subject, action, resource, obj, _allowed = granted[0]
    assert findings[OPERATOR].status == "drift"
    assert findings[OPERATOR].detail.startswith(f"allowed {action} {resource} {obj}"), findings[OPERATOR].detail
    assert findings[ADMIN].status == findings[VIEWER].status == "ok"


def test_the_matrix_covers_every_tier() -> None:
    """A tier with no case would read `ok` on any policy, and a bounded tier asked
    only what it may do would read `ok` on a policy that lets it do everything.
    Admin is bounded by nothing, so it has no case it must be refused."""
    from toolkit.features.access_review import ARGOCD_TIER_SUBJECTS

    assert set(ARGOCD_TIER_SUBJECTS) == {ADMIN, OPERATOR, VIEWER}
    for tier, subject in ARGOCD_TIER_SUBJECTS.items():
        polarities = {c[-1] for c in ARGOCD_RBAC_CASES if c[0] == subject}
        assert polarities == ({True} if tier == ADMIN else {True, False}), subject


def test_this_module_keeps_no_matrix_of_its_own() -> None:
    """#1876 AC2 by construction: one matrix, imported, so the CI test and the live
    reader cannot diverge. A local copy here would be the divergence."""
    import ast

    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    tuples = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Tuple)
        and len(n.elts) == 5
        and isinstance(n.elts[-1], ast.Constant)
        and isinstance(n.elts[-1].value, bool)
    ]
    assert not tuples, "an RBAC case is written here; add it to ARGOCD_RBAC_CASES instead"


def _wire_argocd(monkeypatch: pytest.MonkeyPatch, live: tuple[str, str], judged: list[Any]) -> None:
    from toolkit.features import access_review

    monkeypatch.setattr(access_review, "_live_argocd_oidc_config", lambda: "enableUserInfoGroups: true")
    monkeypatch.setattr(access_review, "_live_argocd_rbac", lambda: live)
    monkeypatch.setattr(access_review.shutil, "which", lambda name: "/usr/bin/docker")

    def judge(policy: str, default: str, image: str, work_dir: Path) -> list[Any]:
        judged.append((policy, default, image, work_dir))
        return []

    monkeypatch.setattr(access_review, "argocd_rbac_disagreements", judge)


def test_the_review_judges_the_live_policy_and_its_live_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """The viewer tier is the default role, so a default taken from the Helm values
    would judge the shipped hub, not the served one."""
    from toolkit.features import access_review

    judged: list[Any] = []
    _wire_argocd(monkeypatch, ("p, live-policy", "role:live-default"), judged)
    findings = access_review._argocd_findings("prod", COMMON)

    [(policy, default, image, work_dir)] = judged
    assert (policy, default) == ("p, live-policy", "role:live-default")
    assert image == argocd_image(COMMON)
    # Colima and Docker Desktop share $HOME only: a mount from /var/folders arrives
    # empty, every case reads No, and every tier would read a false `drift`.
    assert work_dir.resolve().is_relative_to(Path.home().resolve())
    assert [f.user for f in findings] == ["*", ADMIN, OPERATOR, VIEWER]


def test_no_docker_is_cannot_check_never_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    from toolkit.features import access_review

    _wire_argocd(monkeypatch, ("p, x", "role:readonly"), [])
    monkeypatch.setattr(access_review.shutil, "which", lambda name: None)
    findings = access_review._argocd_findings("prod", COMMON)
    assert [(f.user, f.status) for f in findings[1:]] == [("*", "failed")]
    assert "cannot check" in findings[1].detail


def test_an_unreadable_rbac_configmap_is_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    from toolkit.features import access_review

    _wire_argocd(monkeypatch, ("", ""), [])

    def unreadable() -> tuple[str, str]:
        raise ReviewError("the hub's argocd-rbac-cm is unreadable: connection refused")

    monkeypatch.setattr(access_review, "_live_argocd_rbac", unreadable)
    findings = access_review._argocd_findings("prod", COMMON)
    assert [(f.user, f.status) for f in findings[1:]] == [("*", "failed")]


def test_an_evaluator_that_does_not_answer_is_a_review_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A slow pull or a hung daemon is a `failed` row, never a traceback."""
    from toolkit.features import access_review

    def hung(*_a: object, **_k: object) -> None:
        raise subprocess.TimeoutExpired("docker", 180)

    monkeypatch.setattr(subprocess, "run", hung)
    with pytest.raises(ReviewError, match="no answer in 180s"):
        access_review.argocd_rbac_disagreements("", "role:readonly", "img", tmp_path)


def test_a_container_that_never_starts_names_docker_s_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from toolkit.features import access_review

    def refused(*_a: object, **_k: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 125, "", "pull access denied\n")

    monkeypatch.setattr(subprocess, "run", refused)
    with pytest.raises(ReviewError, match="pull access denied"):
        access_review.argocd_rbac_disagreements("", "role:readonly", "img", tmp_path)


def test_kubectl_output_that_is_not_json_is_a_review_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from toolkit.features import access_review

    def garbled(*_a: object, **_k: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, "map[policy.csv:p]", "")

    monkeypatch.setattr(subprocess, "run", garbled)
    with pytest.raises(ReviewError, match="argocd-rbac-cm"):
        access_review._live_argocd_rbac()


def test_the_rbac_reader_takes_both_keys_from_the_configmap_object(monkeypatch: pytest.MonkeyPatch) -> None:
    """`-o json` is a documented format; a jsonpath over a whole map is the printer's choice."""
    import json

    from toolkit.features import access_review

    seen: list[list[str]] = []

    def kubectl(argv: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        seen.append(argv)
        body = {"kind": "ConfigMap", "data": {"policy.csv": "p, a", "policy.default": "role:readonly"}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(body), "")

    monkeypatch.setattr(subprocess, "run", kubectl)
    assert access_review._live_argocd_rbac() == ("p, a", "role:readonly")
    assert seen[0][-2:] == ["-o", "json"]
