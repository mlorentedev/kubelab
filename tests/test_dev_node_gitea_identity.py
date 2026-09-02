"""ANSIBLE-037 AC2 — ace2's git access to Gitea resolves from the identity SSOT,
and reads the forge's credential from the forge's OWN environment.

`tests/test_ansible_identity_ssot.py` guards the same decision on the Beelink,
and this is deliberately a **second file rather than that one extended**. The
shared guard's rule is "every `*_user` variable resolves from
`apps.auth.identities`", and ace2's playbook legitimately carries
`dev_node_user: config.networking.ssh_users.homelab` — the OS-level Linux user
that SSHes into the node, whose SSOT is `networking.ssh_users` (SSOT-014a) and
which CLAUDE.md separates from the app-level identity by name. Pointing the
existing guard at this playbook would fail a variable that is already correct;
relaxing it to accept both SSOTs would weaken it for the Beelink, where an app
identity resolving from the OS-user map is exactly the confusion to catch.

**The defect this file exists to prevent is specific to this node.** ace2 is
provisioned with `deploy_env: staging`, but Gitea's environment identity is
**prod** (ADR-061: "prod is an environment, not a location"; the Beelink
playbook encodes it as `gitea_identity_env`). So on this node the natural
expression — `secrets.apps.services.core.gitea.bot_token` — reads the *staging*
vault, where that key does not exist. With Ansible's `default('')` idiom, which
this playbook already uses for `dev_node_github_token`, that resolves to an
empty string rather than an error: the play reports `failed=0`, the node is
provisioned, and the credential is simply absent. That is the same
fails-open-silently shape as `optional_keys` on the Vikunja R2 secret (#1525),
which crashlooped prod for nine hours.

Static: reads the playbook, which is the file that decides. No cluster, no SOPS
key, no decryption — `apps.auth.identities` is plaintext in `common.yaml`
precisely so this resolution needs none.
"""

from __future__ import annotations

import pathlib

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ACE2_PLAYBOOK = REPO_ROOT / "infra/ansible/playbooks/provision-ace2.yml"

#: The identity SSOT for application accounts (ADR-062 D3). Plaintext by design.
IDENTITY_SSOT = "apps.auth.identities."

#: The fact built from the *node's* own vault (`deploy_env`, staging here). The
#: forge's credential must NOT come from it — see the module docstring.
NODE_SECRET_ROOT = "secrets."

#: The fact built from the forge's own vault, mirroring `provision-bee.yml`.
FORGE_SECRET_ROOT = "gitea_secrets."


def _dev_node_vars() -> dict[str, str]:
    """Every `vars:` entry on the `dev_node` role in ace2's playbook."""
    found: dict[str, str] = {}
    for doc in yaml.safe_load_all(ACE2_PLAYBOOK.read_text()):
        for play in doc if isinstance(doc, list) else [doc]:
            if not isinstance(play, dict):
                continue
            for role in play.get("roles") or []:
                if not isinstance(role, dict):
                    continue
                if "dev_node" not in str(role.get("role", "")):
                    continue
                for name, value in (role.get("vars") or {}).items():
                    if isinstance(value, str):
                        found[name] = value.strip()
    return found


def _play_vars() -> dict[str, str]:
    """Play-level `vars:` in ace2's playbook (where `gitea_identity_env` belongs)."""
    found: dict[str, str] = {}
    for doc in yaml.safe_load_all(ACE2_PLAYBOOK.read_text()):
        for play in doc if isinstance(doc, list) else [doc]:
            if isinstance(play, dict):
                for name, value in (play.get("vars") or {}).items():
                    found[name] = str(value).strip()
    return found


def test_the_playbook_declares_dev_node_vars_at_all() -> None:
    """Guards the guard: a rename that emptied the match would pass vacuously.

    Every assertion below filters what these helpers return, so an empty result
    makes the whole file green while proving nothing — the failure mode
    lesson-380 describes, and worth one line to close.
    """
    assert len(_dev_node_vars()) >= 2


def test_the_forge_identity_resolves_from_the_declared_map() -> None:
    """The account ace2 authenticates as is declared, not written in by hand.

    ADR-062 D1 puts a node running agent work in the machine class, and
    ANSIBLE-037's D1 records why that is forced rather than chosen: the identity
    map holds exactly three keys and #1075 forbids inventing a fourth.
    """
    gitea_identity = {
        name: expr
        for name, expr in _dev_node_vars().items()
        if "gitea" in name and name.endswith(("_user", "_username", "_identity"))
    }
    assert gitea_identity, (
        "ace2's dev_node role declares no Gitea identity variable. AC2 asks for the "
        "credential to resolve from the identity SSOT; nothing resolves from anything yet."
    )
    for name, expr in gitea_identity.items():
        assert IDENTITY_SSOT in expr, (
            f"{name} does not resolve from the identity map: {expr!r}. "
            "An identity resolved from anywhere else is one something else may rename "
            "(AUTH-004: `credentials generate` rotated `basic_auth.user` and renamed a "
            "live service's only admin)."
        )


def test_the_forge_credential_comes_from_the_forges_own_vault() -> None:
    """The node is staging; the forge is prod. Reading the node's vault yields ''.

    This is the whole reason ANSIBLE-037 cannot copy the `dev_node_github_token`
    line and change the key path: that token IS a staging-vault secret, and the
    Gitea bot token is not.
    """
    # Matched on credential-shaped suffixes, NOT on "key". Three of this role's
    # Gitea variables contain that word and none of them is secret:
    # `ssh_host_key` is a public host key (published on purpose), `key_path` is
    # a filesystem path, `key_title` is a label. A filter that caught them would
    # demand they come from a vault, which is the opposite of correct — and it
    # did, on the first run of this test.
    forge_creds = {
        name: expr
        for name, expr in _dev_node_vars().items()
        if "gitea" in name and name.endswith(("_token", "_secret", "_password"))
    }
    assert forge_creds, (
        "ace2's dev_node role declares no Gitea credential variable, so nothing "
        "delivers the key that AC1's clone/push needs."
    )
    for name, expr in forge_creds.items():
        if NODE_SECRET_ROOT in expr and FORGE_SECRET_ROOT not in expr:
            raise AssertionError(
                f"{name} reads the node's own vault ({expr!r}). ace2 is deploy_env=staging "
                "and the Gitea bot token lives in the PROD vault, so this resolves to '' "
                "through the playbook's `default('')` idiom and provisions a node with no "
                "credential while reporting failed=0."
            )
        assert FORGE_SECRET_ROOT in expr, (
            f"{name} does not resolve from the forge's own vault fact "
            f"(`{FORGE_SECRET_ROOT}`): {expr!r}"
        )


def test_the_playbook_declares_the_forges_environment_identity() -> None:
    """`gitea_identity_env` must exist and say prod, mirroring provision-bee.yml.

    Without it there is no fact to build `gitea_secrets` from, and the test above
    can only be satisfied by a variable that refers to something undefined.
    """
    play_vars = _play_vars()
    assert "gitea_identity_env" in play_vars, (
        "ace2's playbook does not declare `gitea_identity_env`. The Beelink's does, "
        "for the same reason: ADR-061 makes prod an environment rather than a location, "
        "so the forge's vault is not the node's vault."
    )
    assert play_vars["gitea_identity_env"] == "prod", (
        f"gitea_identity_env is {play_vars['gitea_identity_env']!r}, expected 'prod' — "
        "the forge's identity environment, not the node's."
    )
