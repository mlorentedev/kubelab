"""Access review: the live privilege of every account, reconciled to the declared one (AUTH-004 AC2).

The tier is declared once, as group membership in `apps.services.security.authelia.users`
(ADR-062 D2, amended by AUTH-011): `admins` administer, `users` operate, and anyone
else only reads. Each app maps those three tiers onto its own roles, and applies
that rule only when someone logs in, and keeps the result in its own database:
Gitea's `is_admin`, Grafana's org role. So taking someone out of `admins` changes
nothing in an app until they next log in there, and a session already open keeps
the old privilege. A demotion is not done until the live tier matches.

This reads the live tier of every account over the break-glass private path,
compares it with the declaration, and with `apply` corrects the difference. Both
apps check the stored privilege on every request, so a corrected value reaches a
session that is already open on its next request. How it is corrected differs:
Gitea's `is_admin` is edited through its API, but Grafana's role cannot be. With
OIDC as Grafana's only login, the role is written from `groups` at each login and
the API refuses to change it (`ErrCannotChangeRoleForExternallySyncedUser`). So
for Grafana, correcting means revoking the account's sessions: the next request
signs in again through Authelia and takes the declared tier. That is reported as
`bounded`, not `fixed`, because the stored role only changes at that next login.
Argo CD keeps no user database: it reads the groups from Authelia's UserInfo.
Authelia answers UserInfo with the groups captured when the access token was
issued, so a changed group reaches Argo CD only when that token expires and the
session signs in again (ARGOCD_TOKEN_LIFESPAN), not when its UserInfo cache
expires. It is reported, from the live hub config, rather than reconciled.

Every app takes the tier from the groups Authelia serves, and Authelia serves the
groups in its users database, a Secret that only `make apply-secrets` delivers: a
merge that changes `groups` shows Synced in Argo CD while Authelia keeps the old
ones (#1911). So the review first compares that live database with the declaration,
and for a user whose groups lag it corrects nothing in any app: an edit or a revoke
would be undone at the next login, from the stale groups. It reports `drift` and
names the command instead, never a `bounded` that cannot converge.

Accounts that exist in an app but belong to no declared identity are reported and
never touched: removing an account is a decision, not a reconciliation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from toolkit.features.break_glass_rotation import Request, _http

#: The groups that grant the admin and operating tiers, as Grafana's role mapping,
#: Argo CD's RBAC and Gitea's auth source spell them. `tests/test_access_review.py`
#: fails if any of them stops agreeing with these.
ADMIN_GROUP = "admins"
OPERATOR_GROUP = "users"

#: The declared tiers. Each app says what each one is called there (`tier_map`).
ADMIN, OPERATOR, VIEWER = "admin", "operator", "viewer"

#: How long a live `kubectl` read may take before the review reports it `failed`.
#: Staging is on-demand, and a spoke that is half up can accept a connection and
#: never answer, which without a bound would hang the review instead of failing it.
KUBECTL_TIMEOUT_S = 30


@dataclass(frozen=True)
class Account:
    """One account as an app holds it. `ref` carries what that app's edit call needs."""

    user: str
    tier: str
    ref: Mapping[str, Any] = field(default_factory=dict)
    #: How the account signs in, where the app says so (Grafana's `authLabels`).
    link: str = ""


@dataclass(frozen=True)
class Finding:
    service: str
    user: str
    declared: str | None
    live: str
    status: str  # ok | drift | undeclared | fixed | failed | refused | bounded
    detail: str = ""


def _tier(groups: list[str]) -> str:
    if ADMIN_GROUP in groups:
        return ADMIN
    return OPERATOR if OPERATOR_GROUP in groups else VIEWER


def declared_tiers(values: dict[str, Any]) -> dict[str, str]:
    """Username → the tier its groups declare: ADMIN, OPERATOR or VIEWER.

    Every Authelia user resolves through the one identity resolver. The machine
    identities (`machine`, `reviewer`, ...) are declared in `apps.auth.identities`
    but are never Authelia users, and only read (ADR-062 D1). Reading every
    identity rather than naming the keys is what keeps a new one from reporting
    `undeclared`, as `reviewer` did when TOOL-080 added it.
    """
    from toolkit.features.configuration import resolve_user_identity

    authelia = values["apps"]["services"]["security"]["authelia"]
    tiers = {}
    for entry in authelia.get("users") or []:
        name = resolve_user_identity(entry, values)
        if name:
            tiers[name] = _tier(entry.get("groups") or [])
    for name in (values.get("apps", {}).get("auth", {}).get("identities") or {}).values():
        if name:
            tiers.setdefault(name, VIEWER)
    return tiers


# --------------------------------------------------------------------------- per app


class GiteaTiers:
    """Gitea's `is_admin`, which it re-reads from its database on every request.
    It has nothing between admin and user, and a user already owns repositories and
    pushes, which is all operating needs."""

    admin_tier, user_tier = "admin", "user"
    tier_map = {ADMIN: admin_tier, OPERATOR: user_tier, VIEWER: user_tier}

    def __init__(self, request: Request = _http) -> None:
        self._request = request

    page_size = 50

    def read(self, base_url: str, auth: str) -> list[Account]:
        users: list[dict[str, Any]] = []
        page = 1
        while True:
            url = f"{base_url}/api/v1/admin/users?limit={self.page_size}&page={page}"
            status, body = self._request("GET", url, None, auth)
            if status != 200 or not isinstance(body, list):
                raise ReviewError(f"Gitea answered {status} listing users")
            users += body
            if len(body) < self.page_size:
                break
            page += 1
        return [
            Account(
                u["login"],
                self.admin_tier if u.get("is_admin") else self.user_tier,
                {"login_name": u.get("login_name", ""), "source_id": u.get("source_id", 0)},
            )
            for u in users
        ]

    def set_tier(self, base_url: str, auth: str, account: Account, tier: str) -> bool:
        # `login_name` is `binding:"Required"` and 1.25.5 writes it unconditionally
        # (routers/api/v1/admin/user.go, EditUser). For an SSO account it holds the
        # IdP's `sub`, the key Gitea matches the next login on. Sending the username
        # instead would detach the account from its SSO identity, so the live value
        # goes back as it came.
        body = {
            "login_name": account.ref.get("login_name", ""),
            "source_id": account.ref.get("source_id", 0),
            "admin": tier == self.admin_tier,
        }
        status, _ = self._request("PATCH", f"{base_url}/api/v1/admin/users/{account.user}", body, auth)
        return status == 200


class GrafanaTiers:
    """Grafana's org role, checked on every request and written from `groups` at each
    login, as `GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH` maps it. The API refuses to
    edit a role that OAuth syncs, so `set_tier` revokes the account's sessions
    instead, and the role changes at the login that follows."""

    tier_map = {ADMIN: "Admin", OPERATOR: "Editor", VIEWER: "Viewer"}
    #: The stored tier changes at the account's next login, not when `set_tier` answers.
    settles_on_next_login = True

    def __init__(self, request: Request = _http) -> None:
        self._request = request

    def read(self, base_url: str, auth: str) -> list[Account]:
        status, body = self._request("GET", f"{base_url}/api/org/users", None, auth)
        if status != 200 or not isinstance(body, list):
            raise ReviewError(f"Grafana answered {status} listing org users")
        # `authLabels` is what the removal of the email-lookup migration flag waits
        # for: every SSO identity must read `Generic OAuth` first. None means local.
        return [
            Account(
                u["login"], u.get("role", ""), {"user_id": u["userId"]}, ", ".join(u.get("authLabels") or []) or "local"
            )
            for u in body
        ]

    def set_tier(self, base_url: str, auth: str, account: Account, tier: str) -> bool:
        # `AdminLogoutUser` revokes every session of the account (13.0.2, no external
        # guard; Server Admin only, which the break-glass account is). With auto-login
        # and a live Authelia session the user notices nothing but the new tier.
        status, _ = self._request("POST", f"{base_url}/api/admin/users/{account.ref['user_id']}/logout", None, auth)
        return status == 200


TierReader = Callable[[], Any]

#: Apps that hold a tier in their own database. Each is reached with its declared
#: break-glass account, over its break-glass private path.
TIERS: dict[str, TierReader] = {"gitea": GiteaTiers, "grafana": GrafanaTiers}


class ReviewError(RuntimeError):
    """An app could not be read, so its accounts cannot be judged."""


# --------------------------------------------------------------------------- the review


def review(service: str, declared: Mapping[str, str], accounts: list[Account], tiers: Any) -> list[Finding]:
    """Judge each live account against the declaration. Pure: no I/O."""
    findings = []
    for account in sorted(accounts, key=lambda a: a.user):
        if account.user not in declared:
            findings.append(Finding(service, account.user, None, account.tier, "undeclared", _sign_in(account)))
            continue
        want = tiers.tier_map[declared[account.user]]
        status = "ok" if account.tier == want else "drift"
        findings.append(Finding(service, account.user, want, account.tier, status, _sign_in(account)))
    return findings


def _sign_in(account: Account) -> str:
    return f"sign-in: {account.link}" if account.link else ""


def reconcile(
    service: str,
    declared: Mapping[str, str],
    tiers: Any,
    base_url: str,
    auth: str,
    apply: bool,
    protected: str = "",
    stale: frozenset[str] = frozenset(),
    stale_detail: str = "",
) -> list[Finding]:
    """Review one app and, with APPLY, correct every drift and read it back.

    PROTECTED is the break-glass account the review runs as. It is never edited:
    a declaration that lost it from `admins` (a typo, a bad rebase) would otherwise
    have the review demote the only credential that can undo the mistake. A local
    break-glass account (Grafana's, #951) belongs to no Authelia user, so the
    declaration says nothing of it; being the break-glass account is what puts it
    in the admin tier. An identity keeps its declared tier, so dropping it from
    `admins` still surfaces as `refused` instead of being re-declared here.

    STALE are the users whose groups the live users database has not caught up
    with (`idp_groups_drift`). Their drift is reported with STALE_DETAIL and never
    corrected: the app would write the old tier back at their next login.
    """
    if protected:
        declared = {protected: ADMIN, **declared}
    accounts = {a.user: a for a in tiers.read(base_url, auth)}
    findings = _hold_back(review(service, declared, list(accounts.values()), tiers), protected, stale, stale_detail)
    editable = [f for f in findings if f.status == "drift" and f.user not in stale and f.declared is not None]
    if not apply or not editable:
        return findings
    accepted = {f.user: tiers.set_tier(base_url, auth, accounts[f.user], f.declared) for f in editable}
    # A 200 says the request was accepted, not that the tier changed: read it back.
    after = {a.user: a.tier for a in tiers.read(base_url, auth)}
    settles = getattr(tiers, "settles_on_next_login", False)
    return [
        f
        if f.status != "drift" or f.user in stale
        else _read_back(service, f, after, bool(settles and accepted.get(f.user)))
        for f in findings
    ]


def _hold_back(findings: list[Finding], protected: str, stale: frozenset[str], stale_detail: str) -> list[Finding]:
    """Mark the drifts the review must not correct: the break-glass account, and
    every user whose groups the IdP has not caught up with."""
    held = []
    for f in findings:
        if f.status == "drift" and f.user == protected:
            detail = "the break-glass account is never edited by the review"
            f = Finding(f.service, f.user, f.declared, f.live, "refused", detail)
        elif f.status == "drift" and f.user in stale:
            f = Finding(f.service, f.user, f.declared, f.live, f.status, stale_detail)
        held.append(f)
    return held


def _read_back(service: str, f: Finding, after: Mapping[str, str], bounded: bool) -> Finding:
    """What one corrected drift became, judged by the tier read back, never by the write's answer."""
    if after.get(f.user) == f.declared:
        return Finding(service, f.user, f.declared, after[f.user], "fixed", f"was {f.live}")
    if bounded:
        detail = "sessions revoked; the next request signs in again and takes the tier from `groups`"
        return Finding(service, f.user, f.declared, after.get(f.user, "?"), "bounded", detail)
    return Finding(service, f.user, f.declared, after.get(f.user, "?"), "failed", f"was {f.live}")


# --------------------------------------------------------------------------- the IdP's live groups


def apply_secrets_hint(env: str) -> str:
    return f"Authelia still serves the old groups: run `make apply-secrets ENV={env}`, then the review again"


def _groups_by_user(text: str, side: str) -> dict[str, tuple[str, ...]]:
    """Username -> its sorted groups, and nothing else: the database also holds each
    password hash, which must never reach a finding. A YAML error is not passed on,
    because PyYAML quotes the offending line, and that line can be a hash."""
    import yaml

    try:
        doc = yaml.safe_load(text or "")
    except yaml.YAMLError:
        raise ReviewError(f"the {side} users database is not valid YAML") from None
    users = doc.get("users") if isinstance(doc, dict) else None
    if not isinstance(users, dict):
        raise ReviewError(f"the {side} users database has no `users` map")
    groups = {}
    for user, entry in users.items():
        listed = (entry or {}).get("groups") if isinstance(entry, dict | None) else None
        # A string would be read letter by letter, so anything but a list is malformed.
        if not isinstance(entry, dict | None) or not isinstance(listed, list | None):
            raise ReviewError(f"the {side} users database has a malformed entry for `{user}`")
        groups[str(user)] = tuple(sorted({str(g) for g in listed or []}))
    return groups


def idp_groups_drift(rendered: str, read_live: Callable[[], str], env: str) -> tuple[list[Finding], frozenset[str]]:
    """Compare the users database Authelia runs with the one the declaration renders.

    Returns one `authelia` finding per user and the users whose groups lag. Any
    difference is `drift`, a live user the declaration lacks included: `make
    apply-secrets` renders the Secret whole, so it removes that user too, which is
    why this is not `undeclared` (a status that means "never touched" here). The
    rendered side comes from the same builder as the Secret, so a user with no
    password hash in ENV is absent from both and never a false drift.
    """
    try:
        want = _groups_by_user(rendered, "rendered")
        have = _groups_by_user(read_live(), f"live {env}")
    except ReviewError as exc:
        return [Finding("authelia", "*", None, "unreadable", "failed", str(exc))], frozenset()
    hint = f"the live users database lags the declaration: run `make apply-secrets ENV={env}`"
    findings = []
    for user in sorted(want.keys() | have.keys()):
        declared = ",".join(want[user]) or "-" if user in want else "(absent)"
        live = ",".join(have[user]) or "-" if user in have else "(absent)"
        same = user in want and user in have and want[user] == have[user]
        findings.append(Finding("authelia", user, declared, live, "ok" if same else "drift", "" if same else hint))
    return findings, frozenset(f.user for f in findings if f.status == "drift")


def _rendered_users_database(env: str, project_root: Path) -> str:
    from toolkit.features.configuration import ConfigurationManager
    from toolkit.features.k8s_secrets import _build_users_database

    return _build_users_database(ConfigurationManager(env, project_root))


def _live_users_database(env: str) -> str:
    """The users database the env's Authelia runs, decoded in-process and never printed."""
    import base64
    import subprocess

    from toolkit.features.k8s_kubeconfig import output_path

    try:
        result = subprocess.run(
            [
                "kubectl",
                "--kubeconfig",
                str(output_path(env)),
                "-n",
                "kubelab",
                "get",
                "secret",
                "authelia-users",
                "-o",
                r"jsonpath={.data.users_database\.yml}",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=KUBECTL_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        raise ReviewError(f"the {env} authelia-users Secret is unreadable: no answer in {KUBECTL_TIMEOUT_S}s") from None
    if result.returncode != 0 or not result.stdout:
        raise ReviewError(f"the {env} authelia-users Secret is unreadable: {result.stderr.strip() or 'empty'}")
    try:
        return base64.b64decode(result.stdout, validate=True).decode()
    except ValueError:
        # binascii.Error and UnicodeDecodeError are both ValueErrors; the value itself
        # holds password hashes, so the message names the Secret, never its content.
        raise ReviewError(f"the {env} authelia-users Secret does not decode to text") from None


#: How long a demotion can go unseen by Argo CD (#1861). A UserInfo refetch reuses
#: the stored access token, and Authelia answers with the groups captured when that
#: token was issued, so the bound is the token's lifespan, not
#: `userInfoCacheExpiration`. No `lifespans` is configured, so this is Authelia
#: 4.39's default; `tests/test_access_review.py` fails if either config sets one.
ARGOCD_TOKEN_LIFESPAN = "1h"


def argocd_group_bound(read_cm: Callable[[], str]) -> str:
    """How long a changed group can go unseen by Argo CD.

    Whether groups come from UserInfo at all is read from the LIVE hub. The bound
    itself is the declared ARGOCD_TOKEN_LIFESPAN, which a test holds to the repo's
    Authelia config and pinned version, not something read from the running IdP.

    With `enableUserInfoGroups`, Argo CD reads the groups from Authelia's UserInfo,
    which fixes them at token issue: a change is seen within ARGOCD_TOKEN_LIFESPAN,
    at the next sign-in. Without it, the groups would have to be in the ID
    token, and under Authelia 4.39 they are not: RBAC then matches no group at all.
    Read from the running `argocd-cm`, not the Helm values, because what counts is
    what the hub runs, which is only true after `make deploy-argocd`.
    """
    import yaml

    oidc = yaml.safe_load(read_cm() or "") or {}
    if oidc.get("enableUserInfoGroups"):
        return (
            f"groups from UserInfo, fixed at token issue: a change is seen within {ARGOCD_TOKEN_LIFESPAN}"
            " (the argocd token lifespan), at the next sign-in"
        )
    return "NO groups: the live hub reads them from the ID token, which carries none, so RBAC matches no group"


def _live_argocd_oidc_config() -> str:
    import subprocess

    from toolkit.features.k8s_kubeconfig import output_path

    try:
        result = subprocess.run(
            [
                "kubectl",
                "--kubeconfig",
                str(output_path("hub")),
                "-n",
                "argocd",
                "get",
                "configmap",
                "argocd-cm",
                "-o",
                r"jsonpath={.data.oidc\.config}",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=KUBECTL_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        raise ReviewError(f"the hub's argocd-cm is unreadable: no answer in {KUBECTL_TIMEOUT_S}s") from None
    if result.returncode != 0:
        raise ReviewError(f"the hub's argocd-cm is unreadable: {result.stderr.strip()}")
    return result.stdout


def review_env(env: str, project_root: Path, apply: bool, log: Callable[[str], None]) -> list[Finding]:
    """Review every app that holds a tier in ENV, over its break-glass path."""
    from toolkit.features.oidc_clients import load_values

    values = load_values(env, project_root)
    # First, so a user whose groups lag is never "corrected" in an app below.
    findings, stale = idp_groups_drift(
        _rendered_users_database(env, project_root), lambda: _live_users_database(env), env
    )
    # With the IdP unread, no user is known not to lag, so a correction could be the
    # non-converging revoke this check exists to prevent: review the apps, fix nothing.
    if apply and any(f.status == "failed" for f in findings):
        log("  apply skipped: the groups Authelia serves could not be read, so no correction is made")
        apply = False
    findings += _review_apps(env, project_root, values, apply, stale, log)
    findings += _argocd_findings(env, values)
    return findings


def _review_apps(
    env: str,
    project_root: Path,
    values: dict[str, Any],
    apply: bool,
    stale: frozenset[str],
    log: Callable[[str], None],
) -> list[Finding]:
    """Reconcile every app that has a break-glass secret in ENV, each over its own private path."""
    from toolkit.features import break_glass as bg
    from toolkit.features.secrets_manager import SecretsManager

    declared = declared_tiers(values)
    decls = bg.declarations(values)
    manager = SecretsManager(project_root)
    findings: list[Finding] = []
    for service, make in TIERS.items():
        decl = decls.get(service) or {}
        if "secret" not in decl:
            continue
        try:
            _decl, _route, plan = bg.resolve(env, service, project_root)
        except bg.BreakGlassError as exc:
            log(f"  {service}: skipped -- {exc}")
            continue
        file_env = bg.secret_file(decl["secret"], env, project_root / "infra" / "config" / "secrets")
        protected = bg.account_login(decl, values)
        auth = f"{protected}:{manager.show_secret(file_env, decl['secret'])}"
        with bg.private_url(env, plan) as base_url:
            try:
                findings += reconcile(
                    service, declared, make(), base_url, auth, apply, protected, stale, apply_secrets_hint(env)
                )
            except ReviewError as exc:
                findings.append(Finding(service, "*", None, "unreadable", "failed", str(exc)))
    return findings


def _argocd_findings(env: str, values: dict[str, Any]) -> list[Finding]:
    """Argo CD keeps no user database: what it can be held to is where it reads `groups` from."""
    clients = values["apps"]["services"]["security"]["authelia"].get("oidc_clients") or []
    if not any(c.get("client_id") == "argocd" and env in (c.get("envs") or []) for c in clients):
        return []
    try:
        bound = argocd_group_bound(_live_argocd_oidc_config)
    except ReviewError as exc:
        return [Finding("argocd", "*", None, "unreadable", "failed", str(exc))]
    status = "bounded" if bound.startswith("groups from UserInfo") else "failed"
    return [Finding("argocd", "*", None, "groups claim", status, f"no user database; {bound}")]
