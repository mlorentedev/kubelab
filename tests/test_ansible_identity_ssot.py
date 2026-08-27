"""AUTH-004 AC1 — on the Ansible delivery path too, an identity resolves from
`apps.auth.identities` and never from a secret store.

`tests/test_admin_identity_ssot.py` already guards this for services whose
admin identity is plumbed through generated **K8s Secrets**. It cannot guard
the Beelink, because nothing about the Beelink goes through K8s: Gitea and
MinIO run there from Docker Compose, rendered by `roles/beelink_services` from
variables set in this playbook. Two delivery paths, one decision — and only one
of them was covered, which is how `minio_root_user` kept resolving from SOPS
for two days after the sibling leg shipped.

**Why resolving an identity from a secret store is the defect.** A secret is a
thing `credentials generate` is entitled to rewrite. On 2026-08-23 it did:
`basic_auth.user` was rotated, Gitea's admin username was aliased to it, and
the rotation silently renamed the only admin of a live service, took prod SSO
down, and broke the repair path in the same run (#1352, lessons 378/379).
MinIO's root user was seeded from that same `common_username` and survived only
because its value happened to equal the declared superadmin — equal by
coincidence, not by resolution, which is a defect that looks exactly like
working code right up until the next rotation.

Static, no cluster and no SOPS key: it reads the playbook, which is the file
that decides. `identities` is plaintext in `common.yaml` precisely so this
resolution needs no decryption.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BEELINK_PLAYBOOK = REPO_ROOT / "infra/ansible/playbooks/provision-bee.yml"

#: A variable naming *who* someone is. Deliberately matched by shape rather
#: than listed, so a service added later is judged by the rule instead of
#: slipping past a whitelist that nobody remembered to extend.
IDENTITY_VAR = re.compile(r"_(user|username)$")

#: Any Ansible variable holding decrypted SOPS content in this playbook. Both
#: are built by `include_vars`/`set_fact` from `sops_*.stdout` — see the
#: playbook's own `secrets:` and `gitea_secrets:` definitions.
SECRET_ROOTS = ("secrets.", "gitea_secrets.")


def _identity_vars() -> dict[str, str]:
    """Every `*_user` role variable in the playbook, mapped to its expression."""
    found: dict[str, str] = {}
    for doc in yaml.safe_load_all(BEELINK_PLAYBOOK.read_text()):
        for play in doc if isinstance(doc, list) else [doc]:
            if not isinstance(play, dict):
                continue
            for role in play.get("roles") or []:
                if not isinstance(role, dict):
                    continue
                for name, value in (role.get("vars") or {}).items():
                    if isinstance(value, str) and IDENTITY_VAR.search(name):
                        found[name] = value.strip()
    return found


def test_the_playbook_declares_identity_variables_at_all() -> None:
    """Guards the guard: a rename that emptied the match would pass silently.

    Every assertion below is a loop over what `_identity_vars` returns, so an
    empty result makes the whole file vacuously green — the failure mode
    lesson-380 describes, and worth one line to close.
    """
    assert len(_identity_vars()) >= 3


def test_no_identity_resolves_from_a_secret_store() -> None:
    offenders = {
        name: expr
        for name, expr in _identity_vars().items()
        if any(root in expr for root in SECRET_ROOTS)
    }
    assert not offenders, (
        "an identity resolved from SOPS is one `credentials generate` may rename: "
        f"{offenders}. Resolve it from `apps.auth.identities` instead."
    )


def test_every_identity_resolves_from_the_declared_map() -> None:
    """The positive half. Absence of `secrets.` is not presence of the SSOT —
    a literal, or a third alias, would pass the test above and fail this one."""
    for name, expr in _identity_vars().items():
        assert "apps.auth.identities." in expr, f"{name} does not resolve from the identity map: {expr!r}"
