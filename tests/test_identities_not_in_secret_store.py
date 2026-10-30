"""#1356 (option B): identities resolve from `apps.auth.identities`, never from SOPS.

On 2026-08-23 `credentials generate` rewrote `basic_auth.user`, a username, as if it
were a credential, and the rename took prod Gitea SSO down. It still wrote three
usernames on every run: `basic_auth.user`, `grafana.admin_user` and
`uptime_kuma.admin_user`. The last one, written into `{env}.enc.yaml`, named the
operator while Kuma's only account is the superadmin (#2493), so the rotation's own
Kuma login used the wrong name.

What holds now:
- the generator writes no value equal to a declared identity, and refuses to;
- the merged config derives each service's admin username from the declaration,
  over any copy a vault still holds;
- the Kuma login reads that derived name.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

from toolkit.features import credentials, monitoring
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.secrets_manager import SECRET_CATALOG, SecretKind

REPO = Path(__file__).resolve().parent.parent

IDENTITIES = {"superadmin": "declared-superadmin", "operator": "declared-operator"}
GRAFANA_BREAK_GLASS = "declared-breakglass"
#: The usernames the generator wrote until #1356. None of them may come back.
IDENTITY_KEYS = (
    "basic_auth.user",
    "apps.services.observability.grafana.admin_user",
    "apps.services.observability.uptime_kuma.admin_user",
)


def _declared() -> dict[str, Any]:
    return {
        "apps": {
            "auth": {"identities": dict(IDENTITIES)},
            "services": {
                "security": {
                    "authelia": {
                        "break_glass": {
                            "grafana": {
                                "login": GRAFANA_BREAK_GLASS,
                                "secret": "apps.services.observability.grafana.admin_password",
                            }
                        }
                    }
                },
                # A stale copy as the vaults held one until #1356: prod named the operator for Kuma.
                "observability": {
                    "grafana": {"admin_user": IDENTITIES["operator"]},
                    "uptime_kuma": {"admin_user": IDENTITIES["operator"], "default_port": 3001},
                },
            },
        },
    }


def _generate(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Run `credentials generate` for prod with every side effect replaced; return what it wrote."""
    writes: list[dict[str, Any]] = []
    cm = MagicMock()
    cm.get_merged_config.return_value = _declared()
    cm.batch_update_secrets.side_effect = lambda data, secret_file_path=None: writes.append(dict(data)) or True
    monkeypatch.setattr(credentials, "ConfigurationManager", MagicMock(return_value=cm))
    answers = iter([IDENTITIES["operator"], "Passw0rdForTests"])
    monkeypatch.setattr(credentials.typer, "prompt", lambda *a, **k: next(answers))

    manager = credentials.CredentialsManager()
    monkeypatch.setattr(manager, "_read_existing_secrets", lambda env: {})
    monkeypatch.setattr(manager, "generate_argon2_hash", lambda s: "$argon2id$fake")
    monkeypatch.setattr(manager, "generate_oidc_client_secret_hash", lambda s: "$argon2id$fake")
    monkeypatch.setattr(manager, "generate_bcrypt_hash", lambda s: "$2b$fake")
    monkeypatch.setattr(manager, "_generate_htpasswd_bcrypt_hash", lambda u, p: f"{u}:$2y$fake")
    monkeypatch.setattr(manager, "_reconcile_external_credentials", lambda *a, **k: None)
    manager.setup_authelia_secrets("prod", auto_update=True)
    return writes


class TestTheGeneratorWritesNoIdentity:
    def test_no_identity_key_is_written(self, monkeypatch: pytest.MonkeyPatch) -> None:
        writes = _generate(monkeypatch)
        assert writes, "nothing was written: the test exercised nothing"
        written = sorted(k for data in writes for k in data if k in IDENTITY_KEYS)
        assert not written, f"credentials generate still writes usernames to SOPS: {written}"

    def test_no_written_value_is_a_declared_identity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        names = set(IDENTITIES.values()) | {GRAFANA_BREAK_GLASS}
        leaked = sorted(k for data in _generate(monkeypatch) for k, v in data.items() if v in names)
        assert not leaked, f"these keys hold a declared identity: {leaked}"

    def test_a_value_equal_to_an_identity_is_refused_before_any_write(self) -> None:
        """The 2026-08-23 shape: `basic_auth.user` holding the operator's name."""
        with pytest.raises(credentials.CredentialsWriteFailed, match="basic_auth.user"):
            credentials._refuse_identities({"basic_auth.user": IDENTITIES["operator"]}, _declared())

    def test_a_credential_is_not_refused(self) -> None:
        credentials._refuse_identities({"basic_auth.credentials": "declared-operator:$2y$fake"}, _declared())


class TestTheConfigDerivesEachAdminUsername:
    def test_derived_over_the_vault_copy(self) -> None:
        config = _declared()
        ConfigurationManager._inject_identity_derivations(config)
        observability = config["apps"]["services"]["observability"]
        assert observability["grafana"]["admin_user"] == GRAFANA_BREAK_GLASS
        assert observability["uptime_kuma"]["admin_user"] == IDENTITIES["superadmin"]

    def test_an_undeclared_identity_drops_the_vault_copy(self) -> None:
        """Assigned, not defaulted: with no declaration, the stale copy must not survive either."""
        config = _declared()
        config["apps"]["services"]["core"] = {"gitea": {"admin_user": IDENTITIES["operator"]}}
        del config["apps"]["auth"]["identities"]["superadmin"]
        del config["apps"]["services"]["security"]["authelia"]["break_glass"]["grafana"]
        ConfigurationManager._inject_identity_derivations(config)
        services = config["apps"]["services"]
        assert "admin_user" not in services["observability"]["grafana"]
        assert "admin_user" not in services["observability"]["uptime_kuma"]
        assert "admin_user" not in services["core"]["gitea"]

    @pytest.mark.parametrize("env", ["dev", "staging", "prod"])
    def test_the_merged_config_runs_the_derivation(self, env: str) -> None:
        """The real loader over the real declarations, whatever the vault holds or lacks."""
        common = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text(encoding="utf-8"))
        superadmin = common["apps"]["auth"]["identities"]["superadmin"]
        login = common["apps"]["services"]["security"]["authelia"]["break_glass"]["grafana"]["login"]
        services = ConfigurationManager(env, REPO).get_merged_config()["apps"]["services"]
        assert services["observability"]["grafana"]["admin_user"] == login
        assert services["observability"]["uptime_kuma"]["admin_user"] == superadmin
        assert services["core"]["gitea"]["admin_user"] == superadmin


class TestKumaLogsInAsItsAccount:
    def _merged(self) -> dict[str, Any]:
        config = _declared()
        ConfigurationManager._inject_identity_derivations(config)
        return config

    def test_monitoring_reads_the_derived_username(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cm = MagicMock()
        cm.get_merged_config.return_value = self._merged()
        cm.secrets_path = Path("/nonexistent")
        vault = {"admin_user": IDENTITIES["operator"], "admin_password": "x"}
        cm._decrypt_sops.return_value = {"apps": {"services": {"observability": {"uptime_kuma": vault}}}}
        monkeypatch.setattr(monitoring, "ConfigurationManager", MagicMock(return_value=cm))
        assert monitoring._get_kuma_creds(Path("."))["username"] == IDENTITIES["superadmin"]

    def test_a_missing_identity_stops_before_any_login(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No declared superadmin: the vault's stale name is not used, and Kuma is never tried."""
        config = _declared()
        del config["apps"]["auth"]["identities"]["superadmin"]
        ConfigurationManager._inject_identity_derivations(config)
        cm = MagicMock()
        cm.get_merged_config.return_value = config
        cm.secrets_path = Path("/nonexistent")
        vault = {"admin_password": "x"}
        cm._decrypt_sops.return_value = {"apps": {"services": {"observability": {"uptime_kuma": vault}}}}
        monkeypatch.setattr(monitoring, "ConfigurationManager", MagicMock(return_value=cm))
        with pytest.raises(SystemExit):
            monitoring._get_kuma_creds(Path("."))

    def test_the_rotation_logs_in_as_kumas_account(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import uptime_kuma_api

        api = MagicMock()
        monkeypatch.setattr(uptime_kuma_api, "UptimeKumaApi", MagicMock(return_value=api))
        cm = MagicMock()
        cm.get_merged_config.return_value = self._merged()
        monkeypatch.setattr(credentials, "ConfigurationManager", MagicMock(return_value=cm))
        monkeypatch.setattr("toolkit.features.configuration.ConfigurationManager", MagicMock(return_value=cm))

        credentials.CredentialsManager()._reconcile_external_credentials("new-pass", "old-pass")
        api.login.assert_called_with(IDENTITIES["superadmin"], "old-pass")


class TestTheCatalogRefusesIdentities:
    """The catalog half: a username cannot be registered as a secret, so no tool can rotate one."""

    @pytest.mark.parametrize(
        "key_path",
        ["basic_auth.user", "apps.services.observability.grafana.admin_user", "apps.x.admin_username"],
    )
    def test_an_identity_key_is_refused(self, key_path: str) -> None:
        from toolkit.features.secrets_manager import SecretKind, SecretSpec

        with pytest.raises(ValueError, match="identity"):
            SecretSpec(key_path=key_path, description="a username", kind=SecretKind.PASSWORD)

    def test_a_password_hash_named_after_a_user_is_not_an_identity(self) -> None:
        from toolkit.features.secrets_manager import SecretKind, SecretSpec

        SecretSpec(key_path="a.users_x_password_hash", description="hash", kind=SecretKind.ARGON2_HASH)

    def test_a_third_party_account_name_is_allowed(self) -> None:
        """EXTERNAL values are typed in and delivered, never minted, so no rotation renames them."""
        from toolkit.features.secrets_manager import SecretKind, SecretSpec

        SecretSpec(key_path="dockerhub.username", description="Docker Hub account", kind=SecretKind.EXTERNAL)

    def test_the_compose_gitea_admin_is_the_superadmin(self) -> None:
        config = _declared()
        config["apps"]["services"]["core"] = {"gitea": {"admin_user": IDENTITIES["operator"]}}
        ConfigurationManager._inject_identity_derivations(config)
        assert config["apps"]["services"]["core"]["gitea"]["admin_user"] == IDENTITIES["superadmin"]


def _key_paths(node: Any, prefix: str = "") -> list[str]:
    if not isinstance(node, dict):
        return [prefix]
    return [p for k, v in node.items() for p in _key_paths(v, f"{prefix}.{k}" if prefix else str(k))]


@pytest.mark.parametrize("vault", sorted((REPO / "infra/config/secrets").glob("*.enc.yaml")), ids=lambda p: p.name)
def test_no_vault_holds_a_username(vault: Path) -> None:
    """SOPS leaves key names in plaintext, so this needs no age key and runs in CI (#2493).

    Allowed: a third-party account name registered as EXTERNAL, and an orphan the
    baseline already tracks with its own plan (`infra.smtp.user`, the SMTP relay).
    """
    from toolkit.features.secrets_manager import baselined_orphans

    external = {s.key_path for s in SECRET_CATALOG if s.kind == SecretKind.EXTERNAL} | set(baselined_orphans())
    doc = {k: v for k, v in (yaml.safe_load(vault.read_text(encoding="utf-8")) or {}).items() if k != "sops"}
    held = [
        path
        for path in _key_paths(doc)
        if (leaf := path.rsplit(".", 1)[-1]) in ("user", "username") or leaf.endswith(("_user", "_username"))
        if path not in external
    ]
    assert not held, f"{vault.name} holds usernames, which resolve from apps.auth.identities: {held}"
