"""BACKUP-044 — the offsite destination's config and credentials."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from toolkit.features.backup_destination import DestinationError, load_credentials

REPO_ROOT = Path(__file__).resolve().parents[1]

ACCESS, SECRET = "backup.r2.nodes.rpi3.access_key_id", "backup.r2.nodes.rpi3.secret_access_key"


class FakeConfig:
    """Minimal ConfigurationManager stand-in."""

    def __init__(self, secrets=None):
        self._secrets = secrets if secrets is not None else {ACCESS: "AKI", SECRET: "SEC"}

    def get_secret_by_path(self, path):
        return self._secrets.get(path)


def test_missing_credentials_point_at_the_command_that_sets_them():
    with pytest.raises(DestinationError, match="toolkit secrets set"):
        load_credentials(FakeConfig(secrets={}), ACCESS, SECRET)


def test_credentials_carry_the_r2_compatibility_env():
    """R2 needs a region placeholder and relaxed checksum behaviour."""
    creds = load_credentials(FakeConfig(), ACCESS, SECRET)
    assert creds["AWS_DEFAULT_REGION"] == "auto"
    assert creds["AWS_REQUEST_CHECKSUM_CALCULATION"] == "when_required"


def test_real_common_yaml_declares_the_destination():
    """The committed SSOT must carry the account and endpoint every node's repository is built on."""
    cfg = yaml.safe_load((REPO_ROOT / "infra/config/values/common.yaml").read_text(encoding="utf-8"))
    node = cfg["backup"]["r2"]
    for field in ("account_id", "endpoint"):
        assert node.get(field), f"backup.r2.{field} must be set in common.yaml"


def test_the_shared_bucket_is_gone_from_the_ssot():
    """`kubelab-backups` was retired (#1920): its bucket and prefix keys must not come back."""
    cfg = yaml.safe_load((REPO_ROOT / "infra/config/values/common.yaml").read_text(encoding="utf-8"))
    assert not {"bucket", "repo_prefix"} & set(cfg["backup"]["r2"])
