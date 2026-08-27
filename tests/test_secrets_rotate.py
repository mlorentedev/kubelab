"""TOOL-041: rotating one credential must not mean rotating twenty-seven.

`secrets_manager`'s module docstring has promised `rotate (regenerate +
propagate)` since it was written, and nothing implemented it. The only way to
change a single credential was `credentials generate`, which rewrites 24 prod
secrets and 2 hub secrets in one shot -- so rotating an exposed Argo CD password
also rotated Grafana, MinIO, Uptime Kuma and every OIDC client secret. With no
verb to carry them, `rotate_note` entries stayed prose, and
`aws.headscale_preauth_key` sat unrotated from March to August 2026.

Two properties are load-bearing and are pinned here.

**It must refuse more than it accepts.** Three classes of secret cannot be
rotated by generating a new random value, and each fails in a way that surfaces
late: minted-elsewhere values authenticate against nothing, immutable values
destroy the state they already encrypted, and uncatalogued keys have no declared
consumers so nothing can say what to restart.

**It must not touch the cluster.** Measured 2026-08-23: a rotation applied to
prod while git still held the old values was reverted by Argo CD under
`selfHeal`, leaving Authelia rejecting the credentials the cluster had just been
given. A rotate verb that helpfully applied its own work would reproduce that
incident on demand.
"""

from __future__ import annotations

import pytest

from toolkit.features.secrets_manager import (
    SECRET_CATALOG,
    RotationPlan,
    RotationRefused,
    SecretKind,
    SecretsManager,
)


@pytest.fixture
def mgr(mocker) -> SecretsManager:
    """A manager whose SOPS writes are captured instead of performed."""
    manager = SecretsManager()
    mocker.patch.object(manager, "set_secret", return_value=True)
    return manager


def _first_of_kind(*kinds: SecretKind, env: str = "prod"):
    """A catalog entry of one of these kinds that is actually rotatable.

    Immutability is excluded here rather than in the test bodies: several
    generatable-looking entries (`session_secret`, `storage_encryption_key`) are
    in IMMUTABLE_SECRETS, so a naive pick lands on one and the test fails on the
    refusal it was not exercising.
    """
    from toolkit.features.credentials import IMMUTABLE_SECRETS

    for spec in SECRET_CATALOG:
        if spec.kind in kinds and env in spec.envs and spec.key_path not in IMMUTABLE_SECRETS:
            return spec
    pytest.skip(f"no rotatable catalog entry of kind {kinds} for {env}")


class TestItRefusesWhatItMustNot:
    def test_a_key_absent_from_the_catalog_is_refused(self, mgr) -> None:
        """The catalog is the registry; a key outside it has no declared consumers."""
        with pytest.raises(RotationRefused, match="SECRET_CATALOG"):
            mgr.rotate_secret("prod", "not.a.real.key")

    def test_an_immutable_secret_is_refused_as_a_migration(self, mgr) -> None:
        """Overwriting storage_encryption_key does not rotate, it orphans a database."""
        with pytest.raises(RotationRefused, match="immutable|migration"):
            mgr.rotate_secret(
                "prod", "apps.services.security.authelia.storage_encryption_key"
            )

    def test_an_externally_minted_secret_is_refused_with_its_procedure(self, mgr) -> None:
        """Refusing is useless unless it prints the procedure that does work."""
        spec = _first_of_kind(SecretKind.EXTERNAL)
        with pytest.raises(RotationRefused) as excinfo:
            mgr.rotate_secret("prod", spec.key_path)
        assert "minted by another system" in str(excinfo.value)
        if spec.rotate_note:
            assert spec.rotate_note[:40] in str(excinfo.value), (
                "the refusal must carry the catalog's rotate_note — a refusal that "
                "only says no leaves the operator exactly where they started"
            )

    def test_a_hub_managed_secret_is_refused_and_says_it_is_a_known_gap(self, mgr) -> None:
        """The catalog declares HUB_MANAGED inert to per-env machinery. Honour it, loudly."""
        spec = _first_of_kind(SecretKind.HUB_MANAGED)
        with pytest.raises(RotationRefused, match="#1338"):
            mgr.rotate_secret("prod", spec.key_path)

    def test_an_env_the_secret_is_not_declared_for_is_refused(self, mgr) -> None:
        spec = next((s for s in SECRET_CATALOG if s.envs == ("prod",)), None)
        if spec is None:
            pytest.skip("no prod-only catalog entry")
        with pytest.raises(RotationRefused, match="not declared for env"):
            mgr.rotate_secret("staging", spec.key_path)


class TestInitCannotDestroyImmutableState:
    """The pre-existing hole this work uncovered, and the more dangerous half.

    All four IMMUTABLE_SECRETS are `RANDOM_TOKEN` -- a kind `init_machine_secrets`
    regenerates -- and both `force` and `rotate` bypass the idempotency check that
    was the only thing stopping them. Measured 2026-08-23 against prod with
    `--force --dry-run`: `storage_encryption_key` appeared among the 19 keys it
    would write. Running that for real does not rotate a credential; it orphans
    Authelia's database and every second factor registered in it.

    `credentials generate` has always preserved them. Two commands reaching the
    same value with one of them unguarded is the defect.
    """

    def test_force_preserves_every_immutable_secret(self, mocker) -> None:
        from toolkit.features.credentials import IMMUTABLE_SECRETS

        manager = SecretsManager()
        mocker.patch.object(manager, "set_secret", return_value=True)
        generated = manager.init_machine_secrets("prod", dry_run=True, force=True)
        for key in IMMUTABLE_SECRETS:
            assert key not in generated, (
                f"--force would regenerate {key}. It is not a credential that happens "
                "to exist, it is load-bearing state; regenerating it destroys what it "
                "encrypted."
            )

    def test_naming_an_immutable_key_refuses_the_whole_run(self, mocker) -> None:
        """Not a partial success: whoever named it holds a belief worth correcting."""
        manager = SecretsManager()
        mocker.patch.object(manager, "set_secret", return_value=True)
        generated = manager.init_machine_secrets(
            "prod",
            dry_run=True,
            rotate=["apps.services.security.authelia.storage_encryption_key"],
        )
        assert generated == {}, "naming an immutable key must abort, not silently skip"

    def test_the_guard_reads_the_shared_list_not_a_copy(self) -> None:
        """One list, imported. A second copy drifts the moment either side changes."""
        source = (
            __import__("inspect")
            .getsource(SecretsManager.init_machine_secrets)
            .replace(" ", "")
        )
        assert "IMMUTABLE_SECRETS" in source, (
            "the guard must consult credentials.IMMUTABLE_SECRETS rather than "
            "re-listing the keys here"
        )


class TestItRotatesAndPropagates:
    def test_a_generatable_secret_is_written_to_the_vault(self, mgr) -> None:
        spec = _first_of_kind(
            SecretKind.RANDOM_HEX, SecretKind.RANDOM_TOKEN, SecretKind.OIDC_CLIENT_SECRET
        )
        plan = mgr.rotate_secret("prod", spec.key_path)
        assert isinstance(plan, RotationPlan)
        written = [call.args[1] for call in mgr.set_secret.call_args_list]
        assert spec.key_path in written

    def test_derived_hashes_are_regenerated_from_the_new_value(self, mgr, mocker) -> None:
        """A hash left on the old plaintext is worse than not rotating at all.

        The credential changes, nothing accepts it, and the rotation reads as done
        while the service is down.
        """
        source = next(
            (
                s
                for s in SECRET_CATALOG
                if s.kind in (SecretKind.RANDOM_TOKEN, SecretKind.OIDC_CLIENT_SECRET)
                and any(d.derived_from == s.key_path for d in SECRET_CATALOG)
                and "prod" in s.envs
            ),
            None,
        )
        if source is None:
            pytest.skip("no generatable secret with a derived hash in prod")
        expected = [
            d.key_path
            for d in SECRET_CATALOG
            if d.derived_from == source.key_path and "prod" in d.envs
        ]
        plan = mgr.rotate_secret("prod", source.key_path)
        for path in expected:
            assert path in plan.derived or path in [
                c.args[1] for c in mgr.set_secret.call_args_list
            ], f"derived key {path} was not regenerated"


class TestItStopsBeforeTheCluster:
    def test_rotation_never_applies_to_kubernetes(self, mgr, mocker) -> None:
        """The whole point. Applying unlanded values is what took prod SSO down."""
        apply_spy = mocker.patch.object(mgr, "apply_to_k8s")
        spec = _first_of_kind(
            SecretKind.RANDOM_HEX, SecretKind.RANDOM_TOKEN, SecretKind.OIDC_CLIENT_SECRET
        )
        mgr.rotate_secret("prod", spec.key_path)
        apply_spy.assert_not_called()

    def test_the_plan_warns_that_an_unmerged_rotation_gets_reverted(self) -> None:
        plan = RotationPlan(key_path="x.y", env="prod")
        joined = " ".join(plan.next_steps)
        assert "revert" in joined, (
            "next_steps must say why merging is not optional: under selfHeal an "
            "uncommitted rotation is undone by Argo CD"
        )

    def test_restarts_come_after_the_merge_not_before(self) -> None:
        """Order is load-bearing, not cosmetic.

        Restarting a consumer before the value is in git makes it pick up a
        credential that the reverted config will reject.
        """
        plan = RotationPlan(key_path="x.y", env="prod", restart_services=("grafana",))
        steps = plan.next_steps
        merge_at = next(i for i, s in enumerate(steps) if "merge" in s)
        restart_at = next(i for i, s in enumerate(steps) if "restart" in s)
        assert merge_at < restart_at, "restart must be ordered after the merge"

    def test_consumers_to_restart_come_from_the_catalog_not_a_literal(self, mgr) -> None:
        """`services` already declares who reads each secret; deriving beats duplicating."""
        spec = _first_of_kind(
            SecretKind.RANDOM_HEX, SecretKind.RANDOM_TOKEN, SecretKind.OIDC_CLIENT_SECRET
        )
        plan = mgr.rotate_secret("prod", spec.key_path)
        assert plan.restart_services == spec.services
