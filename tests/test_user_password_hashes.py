"""#2247 (SEC-034): an Authelia user with no password hash is refused, never rendered.

The dev users database gave the superadmin an empty `password`: Authelia refused
its schema and crash-looped, while `make secrets-audit` read 100% because the
catalog said dev needed no hash for that user. Two halves close it: both
renderers refuse a missing hash and name the SOPS key, and the catalog requires
a hash in every env whose users database renders the identity, checked here
against the same resolver the renderers use.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from toolkit.features import generator_authelia
from toolkit.features.configuration import ConfigurationManager, UserPasswordHashMissing, resolve_user_identity
from toolkit.features.k8s_secrets import _build_users_database
from toolkit.features.secrets_manager import SECRET_CATALOG

ENVS = ("dev", "staging", "prod")
HASH_PREFIX = "apps.services.security.authelia.users_"


def _merged(with_hash: bool) -> dict[str, Any]:
    authelia: dict[str, Any] = {"users": [{"username": "bob", "groups": ["users"]}]}
    if with_hash:
        authelia["users_bob_password_hash"] = "$argon2id$v=19$m=65536,t=3,p=4$abc$def"
    return {"apps": {"services": {"security": {"authelia": authelia}}, "auth": {"identities": {}}}}


def _rendered_identities(env: str) -> set[str]:
    """The identities `env`'s users database renders, from plaintext config alone."""
    values = ConfigurationManager(env).get_plaintext_values()
    users = values["apps"]["services"]["security"]["authelia"].get("users", [])
    return {name for name in (resolve_user_identity(u, values) for u in users) if name}


class TestTheK8sRenderer:
    def test_a_missing_hash_is_refused_and_names_the_key(self) -> None:
        cm = MagicMock(env="staging")
        cm.get_merged_config.return_value = _merged(with_hash=False)
        with pytest.raises(UserPasswordHashMissing, match=r"users_bob_password_hash.*staging\.enc\.yaml"):
            _build_users_database(cm)

    def test_a_present_hash_renders(self) -> None:
        cm = MagicMock(env="staging")
        cm.get_merged_config.return_value = _merged(with_hash=True)
        assert "bob" in _build_users_database(cm)


class TestTheComposeRenderer:
    @staticmethod
    def _generate(monkeypatch: pytest.MonkeyPatch, decrypted: bool) -> dict[str, Any]:
        merged = _merged(with_hash=False)

        class _Config:
            env_secrets_decrypted = decrypted

            def __init__(self, *_args: object) -> None:
                pass

            def get_env_vars(self) -> dict[str, str]:
                return {}

            def get_merged_config(self) -> dict[str, Any]:
                return merged

        monkeypatch.setattr(generator_authelia, "ConfigurationManager", _Config)
        rendered: list[str] = []

        class _Renderer:
            def render_template(self, name: str, _out: object, _context: object) -> bool:
                rendered.append(name)
                return True

        monkeypatch.setattr(generator_authelia, "create_renderer", lambda _dir: _Renderer())
        monkeypatch.setattr(generator_authelia, "oidc_clients_for_template", lambda *_a: [])
        result = generator_authelia.AutheliaGenerator().generate("dev")
        result["rendered"] = rendered
        return result

    def test_with_the_env_decrypted_a_missing_hash_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = self._generate(monkeypatch, decrypted=True)
        assert result["success"] is False
        assert "users_bob_password_hash" in result["error"] and "dev.enc.yaml" in result["error"]
        assert result["rendered"] == [], "nothing may be rendered once a hash is missing"

    def test_without_a_key_the_render_proceeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CI's drift gate runs the generator with no age key; it must not fail there."""
        result = self._generate(monkeypatch, decrypted=False)
        assert result["success"] is True


@pytest.mark.parametrize("env", ENVS)
def test_the_catalog_requires_a_hash_for_every_rendered_identity(env: str) -> None:
    rendered = _rendered_identities(env)
    assert rendered, f"{env} renders no Authelia user: this case would check nothing"
    required = {
        spec.key_path.removeprefix(HASH_PREFIX).removesuffix("_password_hash")
        for spec in SECRET_CATALOG
        if spec.key_path.startswith(HASH_PREFIX) and spec.key_path.endswith("_password_hash") and env in spec.envs
    }
    assert rendered <= required, f"{env} renders users the audit does not require a hash for: {rendered - required}"


@pytest.mark.parametrize(("env_file", "expected"), [({"apps": {"x": "y"}}, True), ({}, False)])
def test_the_manager_records_whether_the_env_file_decrypted(
    monkeypatch: pytest.MonkeyPatch, env_file: dict[str, Any], expected: bool
) -> None:
    cm = ConfigurationManager("dev")
    monkeypatch.setattr(cm, "_decrypt_sops", lambda path: env_file if path.name == "dev.enc.yaml" else {})
    cm.get_merged_config()
    assert cm.env_secrets_decrypted is expected
