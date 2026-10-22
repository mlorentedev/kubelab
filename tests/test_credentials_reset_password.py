"""#909: `make credentials-reset-password ENV=<env> IDENTITY=<key>` resets one Authelia login.

The flow it wraps is the one a locked-out operator reaches for, which is the worst
moment to spell `apps.services.security.authelia.users_<username>_password_hash`
from memory. So the caller names an identity KEY of `apps.auth.identities`, the
same key an Authelia user entry carries in `identity:`, and the key path resolves
through `resolve_user_identity`, the one resolver both generators use.

There is no default identity: two Authelia users name one (`superadmin` and
`operator`), and which account a recovery resets is a decision, not a fallback. A
missing or unknown key is refused with the keys that would work.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from toolkit.features import credentials
from toolkit.features.configuration import ConfigurationManager

REPO = Path(__file__).resolve().parent.parent
AUTH = "apps.services.security.authelia"


def _config(users: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "apps": {
            "auth": {"identities": {"superadmin": "alice", "operator": "bob", "machine": "robot"}},
            "services": {"security": {"authelia": {"users": users}}},
        }
    }


USERS = [{"identity": "superadmin"}, {"identity": "operator"}, {"username": "testuser"}]


class TestTheKeyResolvesFromTheIdentity:
    @pytest.mark.parametrize(("identity", "username"), [("superadmin", "alice"), ("operator", "bob")])
    def test_a_declared_identity_names_its_hash_key(self, identity: str, username: str) -> None:
        key = credentials.authelia_password_hash_key(identity, _config(USERS))
        assert key == f"{AUTH}.users_{username}_password_hash"

    @pytest.mark.parametrize("identity", ["", "nobody", "machine", "testuser"])
    def test_anything_else_is_refused_with_the_keys_that_work(self, identity: str) -> None:
        """`machine` is declared but has no Authelia user; `testuser` is a username, not a key."""
        with pytest.raises(ValueError, match=r"operator.*superadmin"):
            credentials.authelia_password_hash_key(identity, _config(USERS))

    @pytest.mark.parametrize("env", ["staging", "prod"])
    def test_the_real_declarations_resolve(self, env: str) -> None:
        merged = ConfigurationManager(env, REPO).get_merged_config()
        identities = merged["apps"]["auth"]["identities"]
        for user in merged["apps"]["services"]["security"]["authelia"]["users"]:
            if "identity" in user:
                key = credentials.authelia_password_hash_key(user["identity"], merged)
                assert key == f"{AUTH}.users_{identities[user['identity']]}_password_hash"


class TestTheCli:
    def _run(self, monkeypatch: pytest.MonkeyPatch, args: list[str]) -> tuple[Any, dict[str, Any]]:
        from typer.testing import CliRunner

        from toolkit.cli import credentials as cli

        seen: dict[str, Any] = {}
        monkeypatch.setattr(cli.credentials_manager, "update_hashed_secret", lambda **kw: seen.update(kw))
        monkeypatch.setattr(cli, "_merged_config", lambda env: _config(USERS))
        return CliRunner().invoke(cli.app, ["hash-password", *args]), seen

    def test_identity_resolves_the_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        run, seen = self._run(monkeypatch, ["--identity", "operator", "--env", "prod"])
        assert run.exit_code == 0, run.output
        assert seen == {"key_path": f"{AUTH}.users_bob_password_hash", "env": "prod"}

    def test_a_key_path_still_works(self, monkeypatch: pytest.MonkeyPatch) -> None:
        run, seen = self._run(monkeypatch, ["argocd.admin_password_hash", "--env", "prod"])
        assert run.exit_code == 0, run.output
        assert seen == {"key_path": "argocd.admin_password_hash", "env": "prod"}

    @pytest.mark.parametrize(
        "args",
        [
            ["--env", "prod"],
            ["argocd.admin_password_hash", "--identity", "operator", "--env", "prod"],
            ["--identity", "", "--env", "prod"],
        ],
        ids=["neither", "both", "empty-identity"],
    )
    def test_exactly_one_target_or_nothing_is_written(self, monkeypatch: pytest.MonkeyPatch, args: list[str]) -> None:
        run, seen = self._run(monkeypatch, args)
        assert run.exit_code == 1, run.output
        assert not seen, "a refused call must not reach the write"


def _recipe(*variables: str) -> str:
    out = subprocess.run(
        ["make", "-n", "credentials-reset-password", *variables],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout


class TestTheMakeTarget:
    def test_it_delegates_the_identity_and_env(self) -> None:
        recipe = _recipe("ENV=prod", "IDENTITY=operator")
        assert re.search(r"credentials hash-password --identity \"operator\" --env prod\b", recipe), recipe

    def test_an_unset_identity_reaches_the_cli_as_empty(self) -> None:
        """Unquoted, `--identity --env prod` would take `--env` as the identity."""
        recipe = _recipe("ENV=prod", "IDENTITY=")
        assert '--identity "" --env prod' in recipe, recipe

    def test_the_shell_login_never_becomes_the_identity(self) -> None:
        """Make imports the environment: a `$(USER)` here would be the OS login (SSOT-014)."""
        makefile = (REPO / "Makefile").read_text()
        block = makefile.split("credentials-reset-password:", 1)[1].split("\n\n", 1)[0]
        assert "$(USER)" not in block, block
