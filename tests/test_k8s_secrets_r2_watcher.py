"""The R2 watcher's Secret carries a read-only credential and nothing that writes (BACKUP-055).

The watcher holds the restic passwords, which decrypt every node's backup, so
what bounds the cluster's reach is the R2 token beside them: Object Read only,
scoped to the backup buckets, measured refusing a bucket outside them. Every
node also has a read-write credential, which it needs to ship. Handing one of
those to the cluster by mistake would look identical from the outside -- the
probe works either way -- and would give the cluster `forget --prune` over that
node's repository. So the mapping is pinned here.
"""

from __future__ import annotations

import pathlib

import yaml

from toolkit.features.backup_destination import node_secret_paths
from toolkit.features.backup_node_credentials import access_key_path, secret_key_path
from toolkit.features.k8s_secrets import SECRET_DEFINITIONS, _apply_single_secret, _resolve_config_keys
from toolkit.features.secrets_manager import SECRET_CATALOG, SecretKind

COMMON = yaml.safe_load((pathlib.Path(__file__).resolve().parents[1] / "infra/config/values/common.yaml").read_text())
NODES = sorted(COMMON["backup"]["sources"])

_ENV = {
    "BACKUP_R2_WATCHER_ACCESS_KEY_ID": "not-a-real-value-fixture-id",
    "BACKUP_R2_WATCHER_SECRET_ACCESS_KEY": "not-a-real-value-fixture-secret",
    "BACKUP_RESTIC_PASSWORD": "not-a-real-value-fixture-password",
}


def _env_var(path: str) -> str:
    return path.upper().replace(".", "_")


# Each node's password as the Secret reads it: its own once it is in its own
# bucket, the shared one before.
PASSWORDS = {node: _env_var(node_secret_paths(COMMON, node)[2]) for node in NODES}
_ENV |= {var: f"not-a-real-value-fixture-{var.lower()}" for var in PASSWORDS.values()}


def _mapping():
    return _resolve_config_keys(next(m for m in SECRET_DEFINITIONS if m.name == "r2-backup-watcher-secrets"), COMMON)


def _spec(key_path: str):
    return next(s for s in SECRET_CATALOG if s.key_path == key_path)


def test_the_secret_carries_exactly_what_restic_reads() -> None:
    """The watcher pair, and each node's password: the shared one until the node moves.

    The shared `RESTIC_PASSWORD` stays until BACKUP-057 PR 5. The probe before
    PR 4a refuses to start without it, and `apply-secrets` and Argo CD's sync of
    the probe happen in either order, so dropping it would fail the whole fleet.
    """
    assert _mapping().keys == {
        "AWS_ACCESS_KEY_ID": "BACKUP_R2_WATCHER_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY": "BACKUP_R2_WATCHER_SECRET_ACCESS_KEY",
        "RESTIC_PASSWORD": "BACKUP_RESTIC_PASSWORD",
        **{f"RESTIC_PASSWORD_{node.upper()}": PASSWORDS[node] for node in NODES},
    }
    assert not _mapping().optional_keys


def test_no_write_credential_ever_reaches_the_cluster() -> None:
    writers = {"BACKUP_R2_ACCESS_KEY_ID", "BACKUP_R2_SECRET_ACCESS_KEY"}
    writers |= {_env_var(path(node)) for node in NODES for path in (access_key_path, secret_key_path)}
    for mapping in SECRET_DEFINITIONS:
        sources = {*mapping.keys.values(), *mapping.optional_keys.values()}
        assert not sources & writers, mapping.name


def test_the_rendered_secret_holds_a_password_per_node(mocker) -> None:
    run = mocker.patch("toolkit.features.k8s_secrets.subprocess.run")
    run.return_value = mocker.Mock(stdout="secret/r2-backup-watcher-secrets configured", stderr="", returncode=0)

    assert _apply_single_secret(_mapping(), dict(_ENV), {}, dry_run=False, env="staging") is True
    manifest = run.call_args.kwargs["input"]
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", *(f"RESTIC_PASSWORD_{n.upper()}" for n in NODES)):
        assert key in manifest


def test_a_missing_value_refuses_the_apply(mocker) -> None:
    # A watcher without its token does not degrade: every run reports the whole
    # fleet unreadable and pages. Refuse at delivery instead, where the cause is.
    run = mocker.patch("toolkit.features.k8s_secrets.subprocess.run")
    env = {k: v for k, v in _ENV.items() if k != "BACKUP_R2_WATCHER_SECRET_ACCESS_KEY"}

    assert _apply_single_secret(_mapping(), env, {}, dry_run=False, env="staging") is False
    run.assert_not_called()


def test_both_clusters_are_audited_for_every_value() -> None:
    # The watcher is in base/, so staging runs it too; `envs` is the audit
    # dimension, and a key missing from it would go unaudited in staging.
    for key in ("backup.r2.watcher.access_key_id", "backup.r2.watcher.secret_access_key"):
        spec = _spec(key)
        assert spec.kind is SecretKind.EXTERNAL
        assert set(spec.envs) == {"staging", "prod"}
        assert "r2-backup-watcher" in spec.services
    assert {"staging", "prod"} <= set(_spec("backup.restic_password").envs)
    assert "r2-backup-watcher" in _spec("backup.restic_password").services
