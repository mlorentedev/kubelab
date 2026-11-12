"""IDP-036 AC6 -- the Gitea Renovate run authors as its own machine account.

The account follows the agent's shape (AUTH-022): created by the bootstrap script,
its token minted once in the container and recorded in SOPS from the controller,
both gated on the SOPS key being empty. Two differences, both on purpose:

- **Its login is not declared here.** `apps.auth.identities.renovate` is the
  operator's to name, like every other machine account on the forge. Until it is,
  every task below skips, so a provision creates no account and mints nothing.
- **Its grant is Renovate's documented one**, wider than the agent's: Renovate reads
  `/user` and the organization's labels and teams, besides writing branches, pull
  requests and the Dependency Dashboard issue.

The run's read-only github.com token is not catalogued here: an expiring token
needs an expiry checker, which belongs with the run that reads it (AC2).
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

from toolkit.features.gitea_repos import MACHINE_IDENTITIES
from toolkit.features.gitea_tokens import RENOVATE_SCOPES, ROTATABLE_TOKENS

REPO = pathlib.Path(__file__).resolve().parent.parent
COMMON = REPO / "infra/config/values/common.yaml"
ROLE = REPO / "infra/ansible/roles/beelink_services"
PLAYBOOK = REPO / "infra/ansible/playbooks/provision-bee.yml"

RENOVATE_TOKEN_KEY = "apps.services.core.gitea.renovate_token"
#: Renovate's Gitea platform docs, for Gitea >= 1.20: repo read/write, user read,
#: issue read/write, organization read ("to read org labels and teams").
DOCUMENTED_SCOPES = {"write:repository", "read:user", "write:issue", "read:organization"}


def _common() -> dict[str, Any]:
    return yaml.safe_load(COMMON.read_text(encoding="utf-8"))


def _tasks() -> list[dict[str, Any]]:
    return [t for t in yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8")) if isinstance(t, dict)]


def _task(name: str) -> dict[str, Any]:
    for task in _tasks():
        if task.get("name") == name:
            return task
    raise AssertionError(f"no task named {name!r} in beelink_services/tasks/main.yml")


def _catalogued(key: str):
    from toolkit.features.secrets_manager import SECRET_CATALOG

    spec = next((s for s in SECRET_CATALOG if s.key_path == key), None)
    assert spec is not None, f"{key} is not in SECRET_CATALOG"
    return spec


# --------------------------------------------------------------------------- the grant


def test_the_declared_grant_is_renovates_documented_one() -> None:
    declared = _common()["apps"]["services"]["core"]["gitea"]["token_scopes"]["renovate"]
    assert set(declared.split(",")) == set(RENOVATE_SCOPES) == DOCUMENTED_SCOPES


def test_the_renovate_identity_is_a_machine_identity() -> None:
    """A machine identity may never be exempt from branch protection."""
    assert "renovate" in MACHINE_IDENTITIES


def test_the_token_is_rotatable_under_its_own_name() -> None:
    token = ROTATABLE_TOKENS["renovate"]
    others = [t for label, t in ROTATABLE_TOKENS.items() if label != "renovate"]
    assert token.identity == "renovate"
    assert token.secret_key == RENOVATE_TOKEN_KEY
    assert token.token_name not in {t.token_name for t in others}


# --------------------------------------------------------------------------- the catalogue


def test_the_token_is_catalogued_for_prod() -> None:
    from toolkit.features.secrets_manager import Expiry, SecretKind

    forge = _catalogued(RENOVATE_TOKEN_KEY)
    assert forge.kind is SecretKind.EXTERNAL
    assert forge.expiry is Expiry.NEVER
    assert forge.envs == ("prod",)
    assert "gitea-rotate-token TOKEN=renovate" in forge.rotate_note


# --------------------------------------------------------------------------- the role


def test_the_playbook_reads_the_login_the_grant_and_the_secret_from_the_ssot() -> None:
    playbook = PLAYBOOK.read_text(encoding="utf-8")
    assert "gitea_config.apps.auth.identities.renovate | default('')" in playbook
    assert "token_scopes.renovate" in playbook
    assert "gitea_secrets.apps.services.core.gitea.renovate_token | default('')" in playbook


def test_the_bootstrap_creates_the_account_only_once_named() -> None:
    script = (ROLE / "files/gitea-bootstrap.sh").read_text(encoding="utf-8")
    compose = (ROLE / "templates/compose.yml.j2").read_text(encoding="utf-8")
    block = 'if [ -n "${GITEA_RENOVATE_USER:-}" ]; then\n  ensure_machine_account "$GITEA_RENOVATE_USER"'
    assert block in script
    assert 'GITEA_RENOVATE_USER: "{{ gitea_renovate_user }}"' in compose
    assert 'GITEA_RENOVATE_EMAIL: "{{ gitea_renovate_email }}"' in compose


def test_it_is_minted_once_with_the_declared_grant_and_only_once_named() -> None:
    task = _task("Mint the Renovate account's scoped token")
    when = str(task.get("when") or "")
    assert task.get("no_log") is True
    assert "not gitea_renovate_token" in when, "an ungated mint issues a new live token every run"
    assert "gitea_renovate_user | length > 0" in when, "with no login declared there is no account to mint for"
    command = " ".join(task["command"]["argv"])
    assert "--username {{ gitea_renovate_user }}" in command
    assert f"--token-name {ROTATABLE_TOKENS['renovate'].token_name}" in command
    assert "--scopes {{ gitea_renovate_scopes }}" in command


def test_it_is_recorded_over_stdin_under_its_own_key() -> None:
    task = _task("Record the Renovate token in SOPS")
    assert task.get("no_log") is True
    assert task.get("delegate_to") == "localhost"
    assert task["when"] == _task("Mint the Renovate account's scoped token")["when"]
    assert f"toolkit secrets set {RENOVATE_TOKEN_KEY}" in task["command"]
    assert "--stdin" in task["command"]


def test_the_orphan_guards_cover_the_renovate_token() -> None:
    revoke = _task("Revoke a named token that Gitea holds and SOPS does not")
    assert any(item["name"] == ROTATABLE_TOKENS["renovate"].token_name for item in revoke["loop"])
    gate = str(_task("Assert the controller can record a minted token")["when"])
    assert "gitea_renovate_user | length > 0 and not gitea_renovate_token" in gate
