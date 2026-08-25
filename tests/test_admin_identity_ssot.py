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

from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.features.configuration import resolve_user_identity
from toolkit.features.k8s_secrets import SECRET_DEFINITIONS, _build_dynamic_literals
from toolkit.features.secrets_manager import SECRET_CATALOG

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


class TestTheCatalogKeyFollowsTheIdentity:
    """The lockstep `secrets_manager.py` used to ask a human to remember."""

    def test_the_admin_password_hash_key_matches_the_resolved_identity(self) -> None:
        """A rename that forgets SECRET_CATALOG must fail here, not in production.

        The catalog's key is static (`users_operator_password_hash`) because
        `SECRET_CATALOG` is a module-level constant, and deriving it at import
        time would make importing the secrets module read and merge
        `common.yaml`. That is a defensible trade — but it leaves a coupling
        between a literal string and the SSOT, and the old comment handled that
        coupling by asking whoever renames the identity to update the catalog
        "in lockstep".

        A written reminder is not a mechanism, and this repository has measured
        that twice: lesson-365 records the same instruction being broken three
        times in one session by the person who wrote it. So the lockstep is an
        assertion now. If it fails, the fix is to update the catalog key and the
        SOPS path together — not to relax this test.

        The consequence of the drift it prevents is quiet: `secrets audit`,
        `secrets init` and rotation would all target a path nothing writes,
        report on it, and find it missing — reading as "the secret was never
        set" rather than "the catalog is looking in the wrong place".
        """
        common = yaml.safe_load(
            (Path(__file__).parent.parent / "infra/config/values/common.yaml").read_text()
        )
        operator = common["apps"]["auth"]["identities"]["operator"]
        expected = f"apps.services.security.authelia.users_{operator}_password_hash"

        paths = {spec.key_path for spec in SECRET_CATALOG}
        assert expected in paths, (
            f"apps.auth.identities.operator is {operator!r}, so SECRET_CATALOG must register "
            f"{expected!r}. It does not. Update the catalog key and the SOPS key together — "
            "audit, init and rotation all resolve the hash through this path."
        )


class TestTheOldSSOTIsGone:
    """`apps.auth.admin_username` must not come back, in config or in code."""

    def test_common_yaml_no_longer_declares_admin_username(self) -> None:
        """Two declarations of one identity is the whole defect class.

        `apps.auth.identities` and `apps.auth.admin_username` coexisted for a
        day, and during that day the map was read by nothing while the alias
        kept resolving. Leaving the old key present — even unread — invites a
        future consumer to pick whichever it finds first, which is how one
        identity acquires two resolution paths again.
        """
        common = yaml.safe_load(
            (Path(__file__).parent.parent / "infra/config/values/common.yaml").read_text()
        )
        auth = common["apps"]["auth"]
        assert "admin_username" not in auth, (
            "apps.auth.admin_username is back. The identity is declared once, in "
            "apps.auth.identities — resolve through configuration.resolve_user_identity."
        )
        assert auth.get("identities", {}).get("superadmin"), "apps.auth.identities.superadmin must be declared"
        assert auth.get("identities", {}).get("operator"), "apps.auth.identities.operator must be declared"

    def test_no_authelia_user_entry_still_uses_the_is_admin_flag(self) -> None:
        """`is_admin` conflated *which person* with *is this person an admin*.

        Only the first was ever needed by the generators; the second is what
        `groups:` already says. An entry that reintroduces the flag would
        resolve to no identity and be skipped with a warning — a user silently
        absent from Authelia, which fails as a login nobody can explain.
        """
        common = yaml.safe_load(
            (Path(__file__).parent.parent / "infra/config/values/common.yaml").read_text()
        )
        users = common["apps"]["services"]["security"]["authelia"]["users"]
        offenders = [u for u in users if "is_admin" in u]
        assert not offenders, (
            f"these Authelia user entries still carry is_admin: {offenders}. Use "
            "`identity: <key of apps.auth.identities>` — admin-ness is what `groups:` says."
        )

    def test_every_authelia_user_resolves_to_a_name(self) -> None:
        """The end-to-end property, asserted against the real config.

        Each entry must resolve through the one resolver — via `identity:` for a
        declared person, via `username:` for a fixture. An entry resolving to ""
        is skipped by both generators, so it disappears from the users database
        without failing anything.
        """
        common = yaml.safe_load(
            (Path(__file__).parent.parent / "infra/config/values/common.yaml").read_text()
        )
        users = common["apps"]["services"]["security"]["authelia"]["users"]
        unresolved = [u for u in users if not resolve_user_identity(u, common)]
        assert not unresolved, (
            f"these Authelia user entries resolve to no username: {unresolved}. An `identity:` "
            "naming a key absent from apps.auth.identities resolves to '' and is silently skipped."
        )
