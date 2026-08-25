"""BACKUP-044 — the offsite destination verifier.

The probes run against an injected runner, so every case here is exercised
without a network or a live credential. The one that matters most is
`test_delete_failure_fails_the_verification`: a token without delete permission
is the failure that stays invisible until the bucket fills.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from toolkit.features.backup_destination import (
    DestinationConfig,
    DestinationError,
    load_credentials,
    load_destination,
    repo_url,
    verify_destination,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

_DEST = {
    "account_id": "abc123",
    "bucket": "kubelab-backups",
    "endpoint": "https://abc123.r2.cloudflarestorage.com",
}


class FakeConfig:
    """Minimal ConfigurationManager stand-in."""

    def __init__(self, dest=_DEST, secrets=None):
        self._dest = dest
        self._secrets = (
            secrets
            if secrets is not None
            else {"backup.r2.access_key_id": "AKI", "backup.r2.secret_access_key": "SEC"}
        )

    def get_merged_config(self):
        return {"backup": {"r2": self._dest}} if self._dest is not None else {"backup": {}}

    def get_secret_by_path(self, path):
        return self._secrets.get(path)


class Runner:
    """Scripted runner. `fail_on` matches a substring of the joined argv."""

    def __init__(self, fail_on=(), scope_wide=False):
        self.fail_on = tuple(fail_on)
        self.scope_wide = scope_wide
        self.calls: list[str] = []

    def __call__(self, argv, env):
        joined = " ".join(argv)
        self.calls.append(joined)

        if "--version" in joined:
            return 0, "aws-cli/2.0", ""
        if "list-buckets" in joined:
            return (0, '{"Buckets": []}', "") if self.scope_wide else (1, "", "AccessDenied")
        for needle in self.fail_on:
            if needle in joined:
                return 1, "", f"denied: {needle}"
        # `s3 cp` from the bucket must materialise the destination file, or the
        # integrity check has nothing to read.
        if joined.startswith("aws --endpoint-url") and " s3 cp s3://" in joined:
            dst = Path(argv[-1])
            src_hint = dst.parent / "probe.bin"
            dst.write_bytes(src_hint.read_bytes())
        return 0, "", ""


# --------------------------------------------------------------------------
# SSOT resolution
# --------------------------------------------------------------------------


def test_destination_resolves_from_the_config_ssot():
    dest = load_destination(FakeConfig())
    assert dest.bucket == "kubelab-backups"
    assert dest.endpoint.endswith(".r2.cloudflarestorage.com")


def test_missing_config_section_explains_itself():
    with pytest.raises(DestinationError, match="backup.r2"):
        load_destination(FakeConfig(dest=None))


def test_partial_config_names_the_missing_fields():
    with pytest.raises(DestinationError, match="endpoint"):
        load_destination(FakeConfig(dest={"account_id": "a", "bucket": "b"}))


def test_missing_credentials_point_at_the_command_that_sets_them():
    with pytest.raises(DestinationError, match="toolkit secrets set"):
        load_credentials(FakeConfig(secrets={}))


def test_credentials_carry_the_r2_compatibility_env():
    """R2 needs a region placeholder and relaxed checksum behaviour."""
    creds = load_credentials(FakeConfig())
    assert creds["AWS_DEFAULT_REGION"] == "auto"
    assert creds["AWS_REQUEST_CHECKSUM_CALCULATION"] == "when_required"


def test_real_common_yaml_declares_the_destination():
    """The committed SSOT must actually carry backup.r2 — guards a rename."""
    import yaml

    cfg = yaml.safe_load((REPO_ROOT / "infra/config/values/common.yaml").read_text(encoding="utf-8"))
    node = cfg["backup"]["r2"]
    for field in ("account_id", "bucket", "endpoint", "repo_prefix"):
        assert node.get(field), f"backup.r2.{field} must be set in common.yaml"
    assert node["repo_prefix"].startswith("s3:"), "restic addresses R2 through its S3 backend"


# --------------------------------------------------------------------------
# Probes
# --------------------------------------------------------------------------


def test_happy_path_passes_every_probe():
    runner = Runner()
    assert verify_destination(cm=FakeConfig(), run=runner) is True
    joined = " ".join(runner.calls)
    assert "s3 cp" in joined and "s3 rm" in joined


def test_delete_failure_fails_the_verification():
    """The whole reason this module exists: no delete means retention silently never runs."""
    assert verify_destination(cm=FakeConfig(), run=Runner(fail_on=("s3 rm",))) is False


def test_unreachable_bucket_fails_before_writing_anything():
    runner = Runner(fail_on=("s3 ls",))
    assert verify_destination(cm=FakeConfig(), run=runner) is False
    assert not any("s3 cp" in c for c in runner.calls), "must not upload when the bucket is unreachable"


def test_account_wide_token_is_reported_but_not_fatal():
    """Scope is a finding, not a failure — but it must not pass unremarked."""
    assert verify_destination(cm=FakeConfig(), run=Runner(scope_wide=True)) is True


def test_missing_aws_cli_fails_loudly():
    def no_cli(argv, env):
        return (1, "", "not found") if "--version" in " ".join(argv) else (0, "", "")

    assert verify_destination(cm=FakeConfig(), run=no_cli) is False


def test_probe_object_is_namespaced_and_removed():
    runner = Runner()
    verify_destination(cm=FakeConfig(), run=runner)
    uploads = [c for c in runner.calls if "s3 cp" in c and "s3://" in c]
    assert any("_smoketest/" in c for c in uploads), "probe must be namespaced under _smoketest/"
    removed = [c for c in runner.calls if "s3 rm" in c]
    assert len(removed) == 1, "the probe object must be cleaned up exactly once"


def test_repo_prefix_agrees_with_the_derived_repository_url():
    """The repository URL is expressed twice in the SSOT, and nothing pinned them equal.

    The Ansible role writes `backup.r2.repo_prefix/<inventory_hostname>`
    (`roles/node_backup/defaults/main.yml`); every reader — coverage,
    `verify-restic` — derives `s3:{endpoint}/{bucket}/<node>` through
    `repo_url()`. Two expressions of one address, edited independently: a
    bucket or endpoint change that misses `repo_prefix` makes the writer and
    the reader disagree about where the backups are.

    Both failure directions are loud — coverage reports UNCOVERED rather than
    reporting success against an empty repository — which is why this was a
    Minor finding in the BACKUP-044 adversarial review and not a Blocker. Loud
    is not the same as guarded, though, and the guard is one assertion.
    """
    common = yaml.safe_load((REPO_ROOT / "infra/config/values/common.yaml").read_text())
    r2 = common["backup"]["r2"]

    derived = repo_url(
        DestinationConfig(
            account_id=r2["account_id"], bucket=r2["bucket"], endpoint=r2["endpoint"]
        ),
        node="",
    ).rstrip("/")

    assert r2["repo_prefix"] == derived, (
        f"backup.r2.repo_prefix is {r2['repo_prefix']!r} but the readers derive {derived!r}. "
        "The role writes backups to the first and every check looks in the second, so they "
        "must be equal. Fix the SSOT — do not relax this assertion."
    )
