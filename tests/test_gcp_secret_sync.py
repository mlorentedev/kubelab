"""Behaviour of the one-way sync, against a fake `gcloud`.

Every test here mocks the process layer, and that is a constraint rather than a
preference: `gcloud` is a Phase 0 prerequisite that is not installed on this
workstation, and no CI runner reaches a real GCP project. Phase 3 is the live
proof. What CAN be asserted without a project is every branch of the decision
this tool makes, and the two doctrine properties that would otherwise only be
noticed by leaking a credential.

The fake responds to argv, so the tests exercise the real argument construction
rather than a paraphrase of it.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

import pytest

from toolkit.features import gcp_secret_sync as sync

PROJECT = "kubelab-hub"
SECRET_VALUE = "s3cr3t-value-that-must-never-be-seen"


@dataclass
class FakeGcloud:
    """Records every argv and stdin, and answers `describe`/`access` on demand."""

    exists: bool = True
    stored: str = SECRET_VALUE
    enabled_versions: str = "[]"
    calls: list[tuple[list[str], str | None]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.calls = []

    def __call__(self, argv, **kwargs):  # noqa: ANN001, ANN204
        self.calls.append((list(argv), kwargs.get("input")))
        sub = argv[2] if len(argv) > 2 else ""
        rest = argv[3] if len(argv) > 3 else ""
        if argv[0] == "kubectl":
            return subprocess.CompletedProcess(argv, 0, stdout="spoke-token-value", stderr="")
        if sub == "describe":
            return subprocess.CompletedProcess(argv, 0 if self.exists else 1, stdout="", stderr="")
        if sub == "versions" and rest == "access":
            return subprocess.CompletedProcess(argv, 0, stdout=self.stored, stderr="")
        if sub == "versions" and rest == "list":
            return subprocess.CompletedProcess(argv, 0, stdout=self.enabled_versions, stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    def subcommands(self) -> list[str]:
        return [" ".join(a[1:4]) for a, _ in self.calls if a[0] == "gcloud"]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeGcloud:
    f = FakeGcloud()
    monkeypatch.setattr(sync.subprocess, "run", f)
    return f


def _item() -> sync.SyncItem:
    return sync.SyncItem(secret_id="argocd-admin-password-hash", origin="SOPS test", value=SECRET_VALUE)


class TestTheThreeBranches:
    def test_absent_secret_is_created_with_automatic_replication(self, fake: FakeGcloud) -> None:
        # Automatic replication is not a default worth inheriting silently: the
        # cost envelope prices Secret Manager PER LOCATION, so a user-managed
        # multi-region policy multiplies the bill for a hub in one region.
        fake.exists = False
        result = sync.sync_item(_item(), PROJECT, dry_run=False)
        assert result.action == "created"
        created = [a for a, _ in fake.calls if "create" in a]
        assert created, "no create call was made"
        assert "--replication-policy=automatic" in created[0]

    def test_an_identical_payload_writes_nothing(self, fake: FakeGcloud) -> None:
        # Idempotence is the property that keeps the six-version ceiling reachable.
        # `versions add` unconditionally would bill a version per run for no change.
        fake.stored = SECRET_VALUE
        result = sync.sync_item(_item(), PROJECT, dry_run=False)
        assert result.action == "unchanged"
        assert "versions add" not in " ".join(fake.subcommands())

    def test_a_changed_payload_adds_then_destroys_the_superseded(self, fake: FakeGcloud) -> None:
        # DESTROY, not disable: a disabled version still bills. That is the trap
        # named in docs/architecture/infra/gcp-cost-envelope.md.
        fake.stored = "an-older-value"
        fake.enabled_versions = '[{"name": "projects/p/secrets/s/versions/4"}, {"name": "projects/p/secrets/s/versions/3"}]'
        result = sync.sync_item(_item(), PROJECT, dry_run=False)
        assert result.action == "updated"
        joined = " ".join(fake.subcommands())
        assert "versions add" in joined
        destroyed = [a for a, _ in fake.calls if "destroy" in a]
        assert destroyed, "superseded versions were not destroyed"
        assert "3" in destroyed[0], "the newest version must be kept and the older ones destroyed"


class TestDryRunWritesNothing:
    def test_dry_run_reports_the_action_without_performing_it(self, fake: FakeGcloud) -> None:
        fake.exists = False
        result = sync.sync_item(_item(), PROJECT, dry_run=True)
        assert result.action == "created"
        assert not [a for a, _ in fake.calls if "create" in a], "dry-run wrote to Secret Manager"


class TestEmptyValuesFailInsteadOfShipping:
    def test_a_missing_sops_value_is_a_failure_not_an_empty_secret(self) -> None:
        # An empty payload is the worst outcome available: written without error,
        # read successfully at boot, and the hub comes up with an empty admin
        # password. A success-shaped failure. `_deploy-argocd-helm` refuses on an
        # empty decrypt for the same reason.
        items, failures = sync.collect_sops_items({})
        assert items == []
        assert failures, "an absent SOPS value produced no failure"
        assert all(f.action == "failed" for f in failures)


class TestPartialFailureIsTheNormalCase:
    def test_an_unreachable_spoke_names_its_cause_and_does_not_stop_the_rest(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # staging's spoke lives in an on-demand homelab, so "unreachable" is
        # routine rather than exceptional. Everything reachable must still be
        # delivered; a later re-run completes the rest.
        def unreachable(argv, **kwargs):  # noqa: ANN001, ANN202
            if argv[0] == "kubectl":
                return subprocess.CompletedProcess(argv, 1, stdout="", stderr="connection refused")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        monkeypatch.setattr(sync.subprocess, "run", unreachable)
        items, failures = sync.collect_spoke_items({"argocd": {"spokes": {"staging": {}}}})
        assert items == []
        assert failures and all(f.action == "failed" for f in failures)
        assert "homelab" in failures[0].detail, "the failure does not name the likely cause"


class TestSecretsNeverLeaveThroughOutput:
    """The two properties that a leak would otherwise be the first sign of."""

    def test_no_secret_value_ever_appears_in_argv(self, fake: FakeGcloud) -> None:
        # argv is visible to `ps` for the life of the call and lands in any
        # command log. Values go on stdin, and only on stdin.
        fake.exists = False
        sync.sync_item(_item(), PROJECT, dry_run=False)
        for argv, _ in fake.calls:
            assert SECRET_VALUE not in " ".join(argv), (
                f"a secret value appeared in argv: {argv}. It must travel on stdin "
                f"(--data-file=-), where `ps` cannot read it."
            )
        assert any(stdin == SECRET_VALUE for _, stdin in fake.calls), "the value never reached stdin either"

    def test_the_item_does_not_print_its_own_value(self) -> None:
        # A dataclass prints every field by default, so `logger.debug(f"{item}")`
        # added later, or an exception carrying locals, would put a credential in
        # a terminal and a transcript. `repr=False` makes that path harder.
        assert SECRET_VALUE not in repr(_item())
        assert SECRET_VALUE not in str(_item())

    def test_the_logger_never_sees_a_value(self, fake: FakeGcloud, monkeypatch: pytest.MonkeyPatch) -> None:
        emitted: list[str] = []
        monkeypatch.setattr(sync.logger, "debug", lambda msg, *a, **k: emitted.append(str(msg)))
        fake.exists = False
        sync.sync_item(_item(), PROJECT, dry_run=False)
        for line in emitted:
            assert SECRET_VALUE not in line, f"a secret value reached the logger: {line!r}"


class TestGcloudAbsenceIsNamed:
    def test_a_missing_gcloud_points_at_the_runbook(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # This machine does not have gcloud, so this is the first thing a real
        # run hits. "FileNotFoundError: gcloud" would send the reader to the
        # wrong place; Phase 0 §2 is where it is installed.
        def missing(argv, **kwargs):  # noqa: ANN001, ANN202
            raise FileNotFoundError(argv[0])

        monkeypatch.setattr(sync.subprocess, "run", missing)
        with pytest.raises(sync.GcloudMissingError, match="gcp-hub-bootstrap"):
            sync._gcloud(["describe", "x"], PROJECT)
