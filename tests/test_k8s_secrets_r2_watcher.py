"""The R2 watcher's Secret carries a read-only credential and nothing that writes (BACKUP-055).

The watcher holds the restic password, which decrypts every node's backup, so
what bounds the cluster's reach is the R2 token beside it: Object Read only,
scoped to one bucket, measured refusing both a write and a restic lock. The
same bucket also has a read-write credential, `backup.r2.access_key_id`, which
the nodes need to ship. Handing that one to the cluster by mistake would look
identical from the outside -- the probe works either way -- and would give the
cluster `forget --prune` over every repository. So the mapping is pinned here.
"""

from __future__ import annotations

from toolkit.features.k8s_secrets import SECRET_DEFINITIONS, _apply_single_secret
from toolkit.features.secrets_manager import SECRET_CATALOG, SecretKind

_ENV = {
    "BACKUP_R2_READONLY_ACCESS_KEY_ID": "not-a-real-value-fixture-id",
    "BACKUP_R2_READONLY_SECRET_ACCESS_KEY": "not-a-real-value-fixture-secret",
    "BACKUP_RESTIC_PASSWORD": "not-a-real-value-fixture-password",
}


def _mapping():
    return next(m for m in SECRET_DEFINITIONS if m.name == "r2-backup-watcher-secrets")


def _spec(key_path: str):
    return next(s for s in SECRET_CATALOG if s.key_path == key_path)


def test_the_secret_carries_exactly_what_restic_reads() -> None:
    assert _mapping().keys == {
        "AWS_ACCESS_KEY_ID": "BACKUP_R2_READONLY_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY": "BACKUP_R2_READONLY_SECRET_ACCESS_KEY",
        "RESTIC_PASSWORD": "BACKUP_RESTIC_PASSWORD",
    }
    assert not _mapping().optional_keys


def test_the_write_credential_never_reaches_the_cluster() -> None:
    for mapping in SECRET_DEFINITIONS:
        sources = {*mapping.keys.values(), *mapping.optional_keys.values()}
        assert "BACKUP_R2_ACCESS_KEY_ID" not in sources, mapping.name
        assert "BACKUP_R2_SECRET_ACCESS_KEY" not in sources, mapping.name


def test_the_rendered_secret_holds_the_three_keys(mocker) -> None:
    run = mocker.patch("toolkit.features.k8s_secrets.subprocess.run")
    run.return_value = mocker.Mock(stdout="secret/r2-backup-watcher-secrets configured", stderr="", returncode=0)

    assert _apply_single_secret(_mapping(), dict(_ENV), {}, dry_run=False, env="staging") is True
    manifest = run.call_args.kwargs["input"]
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "RESTIC_PASSWORD"):
        assert key in manifest


def test_a_missing_value_refuses_the_apply(mocker) -> None:
    # A watcher without its token does not degrade: every run reports the whole
    # fleet unreadable and pages. Refuse at delivery instead, where the cause is.
    run = mocker.patch("toolkit.features.k8s_secrets.subprocess.run")
    env = {k: v for k, v in _ENV.items() if k != "BACKUP_R2_READONLY_SECRET_ACCESS_KEY"}

    assert _apply_single_secret(_mapping(), env, {}, dry_run=False, env="staging") is False
    run.assert_not_called()


def test_both_clusters_are_audited_for_every_value() -> None:
    # The watcher is in base/, so staging runs it too; `envs` is the audit
    # dimension, and a key missing from it would go unaudited in staging.
    for key in ("backup.r2.readonly_access_key_id", "backup.r2.readonly_secret_access_key"):
        spec = _spec(key)
        assert spec.kind is SecretKind.EXTERNAL
        assert set(spec.envs) == {"staging", "prod"}
        assert "r2-backup-watcher" in spec.services
    assert {"staging", "prod"} <= set(_spec("backup.restic_password").envs)
    assert "r2-backup-watcher" in _spec("backup.restic_password").services
