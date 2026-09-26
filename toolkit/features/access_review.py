"""Access review: the live privilege of every account, reconciled to the declared one (AUTH-004 AC2).

The tier is declared once, as group membership in `apps.services.security.authelia.users`
(ADR-062 D2): `admins` is the admin tier, everyone else is a user. Each app applies
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
Argo CD keeps no user database: it
reads the groups from Authelia's UserInfo and caches them for
`userInfoCacheExpiration`, so its gap closes within that bound without any edit.
It is reported, from the live hub config, rather than reconciled.

Accounts that exist in an app but belong to no declared identity are reported and
never touched: removing an account is a decision, not a reconciliation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from toolkit.features.break_glass_rotation import Request, _http

#: The group that grants the admin tier, as Grafana's role mapping, Argo CD's RBAC
#: and Gitea's auth source spell it. `tests/test_access_review.py` fails if any of
#: them stops agreeing with this.
ADMIN_GROUP = "admins"


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


def declared_admins(values: dict[str, Any]) -> dict[str, bool]:
    """Username → whether the declaration puts it in the admin tier.

    Every Authelia user resolves through the one identity resolver. The machine
    identity is declared in `apps.auth.identities` but is never an Authelia user,
    and is never an admin (ADR-062 D1).
    """
    from toolkit.features.configuration import resolve_user_identity

    authelia = values["apps"]["services"]["security"]["authelia"]
    tiers = {}
    for entry in authelia.get("users") or []:
        name = resolve_user_identity(entry, values)
        if name:
            tiers[name] = ADMIN_GROUP in (entry.get("groups") or [])
    machine = (values.get("apps", {}).get("auth", {}).get("identities") or {}).get("machine")
    if machine:
        tiers.setdefault(machine, False)
    return tiers


# --------------------------------------------------------------------------- per app


class GiteaTiers:
    """Gitea's `is_admin`, which it re-reads from its database on every request."""

    admin_tier, user_tier = "admin", "user"

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
    login. Non-admins are `Viewer`, as `GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH` maps
    them. The API refuses to edit a role that OAuth syncs, so `set_tier` revokes the
    account's sessions instead, and the role changes at the login that follows."""

    admin_tier, user_tier = "Admin", "Viewer"
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


def review(service: str, declared: Mapping[str, bool], accounts: list[Account], tiers: Any) -> list[Finding]:
    """Judge each live account against the declaration. Pure: no I/O."""
    findings = []
    for account in sorted(accounts, key=lambda a: a.user):
        if account.user not in declared:
            findings.append(Finding(service, account.user, None, account.tier, "undeclared", _sign_in(account)))
            continue
        want = tiers.admin_tier if declared[account.user] else tiers.user_tier
        status = "ok" if account.tier == want else "drift"
        findings.append(Finding(service, account.user, want, account.tier, status, _sign_in(account)))
    return findings


def _sign_in(account: Account) -> str:
    return f"sign-in: {account.link}" if account.link else ""


def reconcile(
    service: str,
    declared: Mapping[str, bool],
    tiers: Any,
    base_url: str,
    auth: str,
    apply: bool,
    protected: str = "",
) -> list[Finding]:
    """Review one app and, with APPLY, correct every drift and read it back.

    PROTECTED is the break-glass account the review runs as. It is never edited:
    a declaration that lost it from `admins` (a typo, a bad rebase) would otherwise
    have the review demote the only credential that can undo the mistake. A local
    break-glass account (Grafana's, #951) belongs to no Authelia user, so the
    declaration says nothing of it; being the break-glass account is what puts it
    in the admin tier. An identity keeps its declared tier, so dropping it from
    `admins` still surfaces as `refused` instead of being re-declared here.
    """
    if protected:
        declared = {protected: True, **declared}
    accounts = {a.user: a for a in tiers.read(base_url, auth)}
    findings = [
        Finding(
            f.service, f.user, f.declared, f.live, "refused", "the break-glass account is never edited by the review"
        )
        if f.status == "drift" and f.user == protected
        else f
        for f in review(service, declared, list(accounts.values()), tiers)
    ]
    if not apply or not any(f.status == "drift" for f in findings):
        return findings
    accepted = {
        f.user: tiers.set_tier(base_url, auth, accounts[f.user], f.declared)
        for f in findings
        if f.status == "drift" and f.declared is not None
    }
    # A 200 says the request was accepted, not that the tier changed: read it back.
    after = {a.user: a.tier for a in tiers.read(base_url, auth)}
    result = []
    for f in findings:
        if f.status != "drift":
            result.append(f)
        elif after.get(f.user) == f.declared:
            result.append(Finding(service, f.user, f.declared, after[f.user], "fixed", f"was {f.live}"))
        elif getattr(tiers, "settles_on_next_login", False) and accepted.get(f.user):
            detail = "sessions revoked; the next request signs in again and takes the tier from `groups`"
            result.append(Finding(service, f.user, f.declared, after.get(f.user, "?"), "bounded", detail))
        else:
            result.append(Finding(service, f.user, f.declared, after.get(f.user, "?"), "failed", f"was {f.live}"))
    return result


def argocd_group_bound(read_cm: Callable[[], str]) -> str:
    """How long a changed group can go unseen by Argo CD, read from the LIVE hub.

    With `enableUserInfoGroups`, Argo CD caches the groups from Authelia's UserInfo
    for `userInfoCacheExpiration`. Without it, the groups would have to be in the ID
    token, and under Authelia 4.39 they are not: RBAC then matches no group at all.
    Read from the running `argocd-cm`, not the Helm values, because what counts is
    what the hub runs, which is only true after `make deploy-argocd`.
    """
    import yaml

    oidc = yaml.safe_load(read_cm() or "") or {}
    if oidc.get("enableUserInfoGroups"):
        return f"groups from UserInfo, seen within {oidc.get('userInfoCacheExpiration') or 'the default cache'}"
    return "NO groups: the live hub reads them from the ID token, which carries none, so RBAC matches no group"


def _live_argocd_oidc_config() -> str:
    import subprocess

    from toolkit.features.k8s_kubeconfig import output_path

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
    )
    if result.returncode != 0:
        raise ReviewError(f"the hub's argocd-cm is unreadable: {result.stderr.strip()}")
    return result.stdout


def review_env(env: str, project_root: Path, apply: bool, log: Callable[[str], None]) -> list[Finding]:
    """Review every app that holds a tier in ENV, over its break-glass path."""
    from toolkit.features import break_glass as bg
    from toolkit.features.oidc_clients import load_values
    from toolkit.features.secrets_manager import SecretsManager

    values = load_values(env, project_root)
    declared = declared_admins(values)
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
                findings += reconcile(service, declared, make(), base_url, auth, apply, protected)
            except ReviewError as exc:
                findings.append(Finding(service, "*", None, "unreadable", "failed", str(exc)))
    clients = values["apps"]["services"]["security"]["authelia"].get("oidc_clients") or []
    if any(c.get("client_id") == "argocd" and env in (c.get("envs") or []) for c in clients):
        try:
            bound = argocd_group_bound(_live_argocd_oidc_config)
        except ReviewError as exc:
            findings.append(Finding("argocd", "*", None, "unreadable", "failed", str(exc)))
        else:
            status = "bounded" if bound.startswith("groups from UserInfo") else "failed"
            findings.append(Finding("argocd", "*", None, "groups claim", status, f"no user database; {bound}"))
    return findings
