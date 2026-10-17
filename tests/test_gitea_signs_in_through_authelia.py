"""ADR-071 D5: Gitea's sign-in page hands straight over to Authelia.

Gitea 1.27.3 skips its own sign-in page and redirects to the OAuth2 source only
when that source is the sole active one AND none of the other sign-in methods
is on (`performAutoLoginOAuth2` in routers/web/auth/auth.go): the password form
(`ENABLE_PASSWORD_SIGNIN_FORM`, default true), passkeys
(`ENABLE_PASSKEY_AUTHENTICATION`, default true) and OpenID sign-in. Leaving
either default on keeps the extra "Sign in with Authelia" click that SSO is
meant to remove.

What must NOT go with it: password basic auth on the API. Break-glass for Gitea
is the local superadmin over the private URL, "by API or `git`, the web form is
not relied on" (docs/runbooks/break-glass.md), and the toolkit configures
repositories the same way. `ENABLE_BASIC_AUTHENTICATION` is a separate key whose
default is true; it is declared anyway, so the property lives in the tree rather
than in Gitea's defaults.
"""

from __future__ import annotations

from tests.test_gitea_anonymous_surface import _gitea_environment


def test_the_password_form_and_passkeys_are_off_so_gitea_redirects_to_the_idp() -> None:
    env = _gitea_environment()
    assert env.get("GITEA__service__ENABLE_PASSWORD_SIGNIN_FORM") == "false"
    assert env.get("GITEA__service__ENABLE_PASSKEY_AUTHENTICATION") == "false"
    assert env.get("GITEA__openid__ENABLE_OPENID_SIGNIN") == "false"


def test_api_basic_auth_stays_on_for_break_glass() -> None:
    assert _gitea_environment().get("GITEA__service__ENABLE_BASIC_AUTHENTICATION") == "true"
