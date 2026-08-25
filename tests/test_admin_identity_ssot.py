"""AUTH-004 C6 — the admin identity resolves from `apps.auth.identities`, and from nothing else.

ADR-062 D3 makes `apps.auth.identities` the single declaration of who the
platform's humans are. The map landed in `common.yaml` on 2026-08-23 and, until
this test, **nothing read it**: `grep -rn identities toolkit/ infra/ansible/`
returned one unrelated Headscale comment. A catalog nothing acts on is the
shape lesson-380 describes, and it was live in master.

What actually resolved was `apps.auth.admin_username`, and for Grafana not even
that — `SECRET_DEFINITIONS` mapped `grafana-admin.admin-user` to
`BASIC_AUTH_USER`, the *Traefik basic-auth account*. That alias is not a
harmless indirection. On 2026-08-23 a routine credential rotation rewrote
`basic_auth.user`, and because Gitea's admin username was aliased to the same
value, the rotation silently RENAMED the only admin of a live service, took
prod SSO down, and broke the repair path in the same run (#1352, lessons
378/379). An identity resolved from a secret store is one that something else
is entitled to change.

**Why the fixture sets the two values DIFFERENT, and why that is the whole
test.** Asserting on generated Secret content cannot tell you which source the
code read when both sources hold the same string — the assertion passes against
the alias and demonstrates nothing. That failure mode is not hypothetical: it
is lesson-382, and it recurred in this very series when a mutation intended to
prove a guard red edited the wrong key of the same name and the guard passed.
So `basic_auth.user` here is deliberately a value nobody would mistake for a
person, and the assertion is that it does NOT appear.

These are pure unit tests over `_build_dynamic_literals`: no SOPS, no cluster,
no age key. The real-value coverage lives in `test_k8s_secrets_users_db.py`
behind `requires_sops`; what is guarded here is the *resolution path*, which
must hold in every environment including one nobody can decrypt.
"""

from __future__ import annotations

from typing import Any

import pytest

from toolkit.features.k8s_secrets import SECRET_DEFINITIONS, _build_dynamic_literals

#: The declared superadmin. What every service's admin identity must resolve to.
SUPERADMIN = "declared-superadmin"

#: The Traefik basic-auth account. A machine credential that the credential
#: generator rewrites on rotation — deliberately unlike a person's name, so that
#: finding it in a Secret is unambiguous evidence of the alias, never a
#: coincidence of two sources agreeing.
BASIC_AUTH_ACCOUNT = "traefik-basic-auth-rotated-value"


class FakeConfigurationManager:
    """Minimal ConfigurationManager stand-in — `_build_dynamic_literals` only reads merged config."""

    def __init__(self, merged: dict[str, Any]) -> None:
        self._merged = merged

    def get_merged_config(self) -> dict[str, Any]:
        return self._merged


@pytest.fixture
def cm() -> FakeConfigurationManager:
    """A config whose identity SSOT and basic-auth account are DIFFERENT on purpose."""
    return FakeConfigurationManager(
        {
            "apps": {
                "auth": {
                    "identities": {"superadmin": SUPERADMIN, "operator": "declared-operator"},
                    # Present because its removal is a later task in this part; the
                    # point of the test is that neither this nor basic_auth is what
                    # a service's admin identity comes from.
                    "admin_username": "declared-operator",
                },
                "services": {"security": {"authelia": {}}},
            },
            "basic_auth": {"user": BASIC_AUTH_ACCOUNT},
        }
    )


class TestAdminIdentityResolvesFromTheSSOT:
    """C6: assert on the GENERATED Secret, so the guard survives a refactor of the plumbing."""

    def test_grafana_admin_user_resolves_from_the_identity_ssot(
        self, cm: FakeConfigurationManager
    ) -> None:
        """RED until `grafana-admin.admin-user` stops coming from `BASIC_AUTH_USER`.

        Grafana is the clearest case because its mapping names the alias
        outright (`k8s_secrets.py:53`). Nothing about Grafana requires the
        Traefik account; the two coincided by history.
        """
        literals = _build_dynamic_literals(cm)

        assert "grafana-admin" in literals, (
            "grafana-admin has no dynamic literal, so its admin-user still comes from the "
            "static SECRET_DEFINITIONS mapping to BASIC_AUTH_USER. The admin identity must "
            "be resolved from apps.auth.identities.superadmin and injected here."
        )
        assert literals["grafana-admin"]["admin-user"] == SUPERADMIN, (
            f"grafana-admin.admin-user is {literals['grafana-admin']['admin-user']!r}, "
            f"expected the declared superadmin {SUPERADMIN!r}."
        )

    def test_minio_root_user_resolves_from_the_identity_ssot(
        self, cm: FakeConfigurationManager
    ) -> None:
        """RED until MinIO's root user stops being an independently-stored SOPS value.

        MinIO's failure mode differs from Grafana's and is worth naming: its
        root user is not aliased to basic-auth, it is a *separate copy* of the
        identity in SOPS (`APPS_SERVICES_DATA_MINIO_ROOT_USER`). One identity
        stored twice drifts, and it already has — #1355 facet 3 records MinIO's
        root credential diverging from SOPS during the same rotation.
        """
        literals = _build_dynamic_literals(cm)

        assert "minio-secrets" in literals, (
            "minio-secrets has no dynamic literal, so MINIO_ROOT_USER is still a standalone "
            "SOPS value rather than the declared superadmin. One identity, one declaration."
        )
        assert literals["minio-secrets"]["MINIO_ROOT_USER"] == SUPERADMIN, (
            f"MINIO_ROOT_USER is {literals['minio-secrets']['MINIO_ROOT_USER']!r}, "
            f"expected the declared superadmin {SUPERADMIN!r}."
        )

    def test_no_generated_secret_carries_the_basic_auth_account(
        self, cm: FakeConfigurationManager
    ) -> None:
        """The anti-assertion, and the one that would have caught #1352 before it shipped.

        The two tests above say where the identity MUST come from. This one says
        where it must NOT: the Traefik basic-auth account is a machine credential
        the generator rewrites on rotation, and no human identity may be derived
        from it anywhere. Stated as a sweep rather than per-service so that a new
        service reaching for the same alias fails here rather than during the
        next rotation.
        """
        literals = _build_dynamic_literals(cm)

        leaked = sorted(
            f"{secret}.{key}"
            for secret, entries in literals.items()
            for key, value in entries.items()
            if BASIC_AUTH_ACCOUNT in str(value)
        )
        assert not leaked, (
            f"these generated secret values contain the Traefik basic-auth account: {leaked}. "
            "An identity resolved from a secret store is one the credential generator is "
            "entitled to rewrite — that is what renamed Gitea's only admin on 2026-08-23."
        )


class TestTheAliasIsGoneFromTheStaticMapping:
    """The static half. `_build_dynamic_literals` cannot un-declare a mapping that still exists."""

    def test_no_secret_definition_maps_a_user_field_to_basic_auth(self) -> None:
        """RED while `SECRET_DEFINITIONS` still names BASIC_AUTH_USER.

        Kept separate from the generated-content tests on purpose. A dynamic
        literal shadows the static mapping at apply time, so the tests above can
        go green while the alias is still declared — and a declaration that no
        longer takes effect is exactly the kind of thing a later refactor
        "restores" in good faith.
        """
        offenders = sorted(
            f"{mapping.name}.{k8s_key} -> {env_var}"
            for mapping in SECRET_DEFINITIONS
            for k8s_key, env_var in mapping.keys.items()
            if "BASIC_AUTH" in env_var
        )
        assert not offenders, (
            f"SECRET_DEFINITIONS still resolves an identity from the basic-auth account: "
            f"{offenders}. Remove the mapping — the value now comes from "
            "apps.auth.identities via _build_dynamic_literals."
        )
