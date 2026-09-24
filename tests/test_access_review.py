"""AUTH-004 AC2: each app's live privilege follows the declared groups, and is enforced at all.

Two defects this pins, both measured on 2026-09-24 by the first `make auth-review`:

- Grafana's role path returned 'Viewer' from the ID token, which carries no
  `groups` under Authelia 4.39, so Grafana never read UserInfo and every SSO user
  was Viewer, admins included.
- Argo CD read `groups` from the ID token only, so `g, admins, role:admin` matched
  nobody and every SSO user fell to `role:readonly`.

And the reconciliation that makes a demotion take effect in a session already open.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import jmespath  # type: ignore[import-untyped]
import pytest
import yaml

from toolkit.features.access_review import (
    ADMIN_GROUP,
    Account,
    GiteaTiers,
    GrafanaTiers,
    declared_admins,
    reconcile,
    review,
)

REPO = Path(__file__).resolve().parent.parent
COMMON = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())


# --------------------------------------------------------------------------- the declaration


def test_the_declared_tiers_come_from_the_groups() -> None:
    tiers = declared_admins(COMMON)
    assert tiers["manu"] is True, "the superadmin is in admins"
    assert tiers["testuser"] is False, "the e2e fixture is never an admin"
    assert tiers[COMMON["apps"]["auth"]["identities"]["machine"]] is False, "the machine identity is never an admin"


def test_every_app_spells_the_admin_group_the_same_way() -> None:
    """The group name is a literal in three consumers; they must agree with the review."""
    grafana = (REPO / "infra/k8s/base/services/grafana-config/grafana.env").read_text()
    argocd = yaml.safe_load((REPO / "infra/helm/argocd/values.yaml").read_text())["configs"]["rbac"]["policy.csv"]
    gitea = (REPO / "infra/ansible/roles/beelink_services/files/gitea-bootstrap.sh").read_text()
    assert f"'{ADMIN_GROUP}'" in grafana
    assert re.search(rf"^\s*g,\s*{ADMIN_GROUP},\s*role:admin\s*$", argocd, re.M)
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


@pytest.mark.parametrize(("where", "expr"), _role_paths())
def test_the_role_path_defers_to_userinfo_when_the_id_token_has_no_groups(where: str, expr: str) -> None:
    """Grafana evaluates the ID token first and moves on only when the result is empty.

    An expression that ends in a default returns it from the ID token, and UserInfo,
    where Authelia puts `groups`, is never read.
    """
    assert jmespath.search(expr, {"sub": "x", "email": "a@b"}) in (None, ""), where
    assert jmespath.search(expr, {"groups": [ADMIN_GROUP, "users"]}) == "Admin", where
    assert jmespath.search(expr, {"groups": ["users"]}) == "Viewer", where
    assert jmespath.search(expr, {"groups": []}) == "Viewer", where


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
    assert oidc.get("userInfoCacheExpiration"), "the cache bounds how long a changed group goes unseen"


# --------------------------------------------------------------------------- the review


class FakeApp:
    """A tier store that answers reads and records edits, like an app's API."""

    def __init__(self, tiers: Any, accounts: list[Account], accept: bool = True) -> None:
        self.tiers, self.accounts, self.accept = tiers, {a.user: a for a in accounts}, accept
        self.edits: list[tuple[str, str]] = []
        self.admin_tier, self.user_tier = tiers.admin_tier, tiers.user_tier

    def read(self, base_url: str, auth: str) -> list[Account]:
        return list(self.accounts.values())

    def set_tier(self, base_url: str, auth: str, account: Account, tier: str) -> bool:
        self.edits.append((account.user, tier))
        if self.accept:
            self.accounts[account.user] = Account(account.user, tier, account.ref)
        return True  # a 200 either way: the read-back is what decides


DECLARED = {"manu": True, "operator": False, "hefesto": False}


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


def test_grafana_edit_sets_the_org_role_by_user_id() -> None:
    request = Recorder()
    GrafanaTiers(request).set_tier("http://gr", "a:b", Account("operator", "Admin", {"user_id": 7}), "Viewer")
    assert request.calls == [("PATCH", "http://gr/api/org/users/7", {"role": "Viewer"})]


def test_the_break_glass_account_is_never_edited() -> None:
    """A declaration that dropped the superadmin from `admins` must not have the review
    demote the only credential that can repair it."""
    app = FakeApp(GiteaTiers, [Account("manu", "admin"), Account("operator", "admin")])
    findings = {f.user: f for f in reconcile("gitea", {"manu": False, "operator": False}, app, "u", "a", True, "manu")}
    assert findings["manu"].status == "refused"
    assert ("manu", "user") not in app.edits
    assert findings["operator"].status == "fixed"


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
        assert "5m" in bound


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
