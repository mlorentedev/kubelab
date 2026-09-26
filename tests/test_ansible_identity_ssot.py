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
    # Named rather than counted: a count floor broke when OPS-023 retired
    # `minio_root_user`, which says nothing about whether the match still works.
    assert {"gitea_admin_user", "gitea_bot_user"} <= set(_identity_vars())


def test_no_identity_resolves_from_a_secret_store() -> None:
    offenders = {name: expr for name, expr in _identity_vars().items() if any(root in expr for root in SECRET_ROOTS)}
    assert not offenders, (
        "an identity resolved from SOPS is one `credentials generate` may rename: "
        f"{offenders}. Resolve it from `apps.auth.identities` instead."
    )


def test_every_identity_resolves_from_the_declared_map() -> None:
    """The positive half. Absence of `secrets.` is not presence of the SSOT —
    a literal, or a third alias, would pass the test above and fail this one."""
    for name, expr in _identity_vars().items():
        assert "apps.auth.identities." in expr, f"{name} does not resolve from the identity map: {expr!r}"


def test_the_gitea_admin_email_is_the_superadmins() -> None:
    """AUTH-004 AC3. Rendered, not grepped: the expression must produce the email.

    It was `apps.contact.email`, which is also the operator's Authelia email. The
    live admin happened to hold another address because it predates that line.
    But a rebuilt forge would create the admin with the operator's email, and
    `ACCOUNT_LINKING=auto` would then link the operator's first SSO login to the
    admin account.
    """
    import jinja2

    expr = None
    for doc in yaml.safe_load_all(BEELINK_PLAYBOOK.read_text()):
        for play in doc if isinstance(doc, list) else [doc]:
            for role in (play or {}).get("roles") or [] if isinstance(play, dict) else []:
                if isinstance(role, dict) and "gitea_admin_email" in (role.get("vars") or {}):
                    expr = role["vars"]["gitea_admin_email"]
    assert expr, "provision-bee.yml no longer sets gitea_admin_email"

    common = yaml.safe_load((REPO_ROOT / "infra/config/values/common.yaml").read_text())
    rendered = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(expr).render(gitea_config=common).strip()
    users = common["apps"]["services"]["security"]["authelia"]["users"]
    superadmin = next(u for u in users if u.get("identity") == "superadmin")
    assert rendered == superadmin["email"]
    assert rendered != common["apps"]["contact"]["email"]
