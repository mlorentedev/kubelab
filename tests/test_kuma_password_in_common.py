"""#2599: Uptime Kuma's password is one value, in `common.enc.yaml`.

Kuma is a single instance on rpi3, not one per env. `credentials generate --env <env>`
wrote its password into `{env}.enc.yaml` and then changed Kuma to it, while
`make monitoring-apply` reads the password from common only. Every rotation left
Kuma on a password the monitoring path did not have.

The catalog now marks the key HUB_MANAGED, so the shadow guard in
`test_hub_secrets_not_shadowed.py` holds where it is written and that no env file
copies it. These tests hold the service half: Kuma is changed only after common
holds the new value, starting from the value common held before.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from toolkit.features import credentials
from toolkit.features.secrets_manager import SECRET_CATALOG, SecretKind

KEY = "apps.services.observability.uptime_kuma.admin_password"


def _run(monkeypatch: pytest.MonkeyPatch, existing: dict[str, dict[str, Any]]) -> list[tuple[str, Any]]:
    """`credentials generate --env prod` with every side effect recorded, in order."""
    events: list[tuple[str, Any]] = []
    cm = MagicMock()
    cm.get_merged_config.return_value = {"apps": {"auth": {"identities": {"operator": "operator"}}}}

    def write(data: dict[str, Any], secret_file_path: Any = None) -> bool:
        events.append(("write", "common" if secret_file_path else "env"))
        return True

    cm.batch_update_secrets.side_effect = write
    monkeypatch.setattr(credentials, "ConfigurationManager", MagicMock(return_value=cm))
    answers = iter(["operator", "Passw0rdForTests"])
    monkeypatch.setattr(credentials.typer, "prompt", lambda *a, **k: next(answers))

    manager = credentials.CredentialsManager()
    monkeypatch.setattr(manager, "_read_existing_secrets", lambda env: existing.get(env, {}))
    monkeypatch.setattr(manager, "generate_argon2_hash", lambda s: "$argon2id$fake")
    monkeypatch.setattr(manager, "generate_oidc_client_secret_hash", lambda s: "$argon2id$fake")
    monkeypatch.setattr(manager, "generate_bcrypt_hash", lambda s: "$2b$fake")
    monkeypatch.setattr(manager, "_generate_htpasswd_bcrypt_hash", lambda u, p: "u:$2y$fake")
    monkeypatch.setattr(
        manager, "_reconcile_external_credentials", lambda new, old: events.append(("reconcile", old))
    )
    manager.setup_authelia_secrets("prod", auto_update=True)
    return events


def test_the_catalog_places_the_password_in_common() -> None:
    spec = next(s for s in SECRET_CATALOG if s.key_path == KEY)
    assert spec.kind == SecretKind.HUB_MANAGED


def test_kuma_is_changed_from_the_password_common_held(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stale env copy must not be the login: Kuma holds what common holds."""
    events = _run(monkeypatch, {"common": {KEY: "held-by-common"}, "prod": {KEY: "stale-env-copy"}})
    assert ("reconcile", "held-by-common") in events, events


def test_kuma_is_changed_only_after_common_holds_the_new_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """File before service: a failed common write must leave Kuma untouched, still on common's old value."""
    events = _run(monkeypatch, {"common": {KEY: "held-by-common"}})
    names = [e[0] for e in events]
    assert names.index("reconcile") > names.index("write") and ("write", "common") in events[: names.index("reconcile")], events
