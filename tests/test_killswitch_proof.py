"""The AC2b proof must never leave the kill switch aimed at the scratch project.

`gcp_killswitch_proof.run_proof` repoints the live function, fires it, and puts
it back. The middle step is the interesting one to a reader; the last is the one
that matters, because a switch left pointing at a deleted scratch project is a
switch that will never fire on the hub — and its failure mode is silence. There
is no alarm for "the thing that would have saved you is aimed elsewhere".

So the restore is a `finally`, and these tests exercise it through every path
out of the function: success, timeout, and an exception mid-flight. Same shape
as the tfvars cleanup, and for the same reason.

`gcloud` is stubbed at the process boundary. No GCP, no credentials, no network.
"""

from __future__ import annotations

import pytest

from toolkit.features import gcp_killswitch_proof as proof

HUB = "kubelab-hub"
SCRATCH = "kubelab-killswitch-proof"


class FakeGcloud:
    """Records every `gcloud` invocation and answers from scripted state."""

    def __init__(self, *, billing_after_fire: bool = False, fail_on: str | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.target = HUB
        self.billing = {SCRATCH: True}
        self._fired = False
        self._billing_after_fire = billing_after_fire
        self._fail_on = fail_on

    def __call__(self, *args: str, check: bool = True) -> str:
        self.calls.append(args)
        if self._fail_on and self._fail_on in " ".join(args):
            raise proof.KillSwitchProofError(f"stubbed failure on {self._fail_on}")

        if args[:2] == ("functions", "describe"):
            return self.target
        # Repointing goes through Cloud Run, not `functions deploy`: the latter
        # re-runs a deployment and demands --source. See _repoint's docstring.
        if args[:3] == ("run", "services", "update"):
            for a in args:
                if a.startswith("TARGET_PROJECT="):
                    self.target = a.split("=", 1)[1]
            return ""
        if args[:3] == ("billing", "projects", "describe"):
            return "True" if self.billing.get(args[3], True) else "False"
        if args[:3] == ("pubsub", "topics", "publish"):
            self._fired = True
            # The switch acts on whatever the function currently targets.
            self.billing[self.target] = self._billing_after_fire
            return ""
        return ""

    @property
    def deploys(self) -> list[str]:
        """Every TARGET_PROJECT the function was pointed at, in order."""
        out = []
        for call in self.calls:
            for a in call:
                if a.startswith("TARGET_PROJECT="):
                    out.append(a.split("=", 1)[1])
        return out


@pytest.fixture
def gcloud(monkeypatch: pytest.MonkeyPatch):
    def _install(**kwargs: object) -> FakeGcloud:
        fake = FakeGcloud(**kwargs)  # type: ignore[arg-type]
        monkeypatch.setattr(proof, "_gcloud", fake)
        monkeypatch.setattr(proof.time, "sleep", lambda _s: None)
        return fake

    return _install


def _run(**kwargs: object):
    return proof.run_proof(
        function="billing-kill-switch",
        region="europe-west4",
        topic="billing-kill-switch",
        scratch_project=SCRATCH,
        expected_home=HUB,
        timeout_s=1.0,
        poll_s=0.0,
        **kwargs,  # type: ignore[arg-type]
    )


class TestTheHappyPath:
    def test_it_reports_the_detach(self, gcloud) -> None:
        gcloud(billing_after_fire=False)
        result = _run()
        assert result.detached
        assert result.restored_to == HUB

    def test_it_points_at_the_scratch_project_and_then_back(self, gcloud) -> None:
        fake = gcloud(billing_after_fire=False)
        _run()
        assert fake.deploys == [SCRATCH, HUB], f"unexpected repoint sequence: {fake.deploys}"
        assert fake.target == HUB


class TestTheRestoreIsUnconditional:
    def test_restored_after_a_timeout(self, gcloud) -> None:
        """The switch did not fire. That is a finding, not a reason to leave it
        aimed at a project about to be deleted."""
        fake = gcloud(billing_after_fire=True)  # billing never goes away
        result = _run()
        assert not result.detached
        assert fake.target == HUB, "a failed proof left the kill switch disarmed"

    def test_restored_after_an_exception_mid_flight(self, gcloud) -> None:
        """The path nobody writes by hand: something throws between repoint and
        restore. Without a `finally`, the switch stays pointed at the scratch."""
        fake = gcloud(fail_on="pubsub topics publish")
        with pytest.raises(proof.KillSwitchProofError):
            _run()
        assert fake.target == HUB, "an exception left the kill switch disarmed"

    def test_a_failed_restore_is_raised_not_swallowed(self, gcloud, monkeypatch) -> None:
        """Putting it back is not the same as having put it back.

        If the restoring deploy silently no-ops, the function is still aimed at
        the scratch project — and reporting success there would be the worst
        outcome available.
        """
        fake = gcloud(billing_after_fire=False)
        original = proof._gcloud

        def sticky(*args: str, check: bool = True) -> str:
            # The second deploy (the restore) does nothing.
            if args[:3] == ("run", "services", "update") and fake.target == SCRATCH:
                fake.calls.append(args)
                return ""
            return original(*args, check=check)

        monkeypatch.setattr(proof, "_gcloud", sticky)
        with pytest.raises(proof.KillSwitchProofError, match="RESTORE FAILED"):
            _run()


class TestItRefusesUnsafeSetups:
    def test_scratch_equal_to_the_hub_is_refused(self, gcloud) -> None:
        """It would work, and prove it by taking the hub down."""
        gcloud()
        with pytest.raises(proof.KillSwitchProofError, match="taking the hub down"):
            proof.run_proof(
                function="f",
                region="r",
                topic="t",
                scratch_project=HUB,
                expected_home=HUB,
                timeout_s=1.0,
                poll_s=0.0,
            )

    def test_an_unexpected_live_target_is_refused(self, gcloud) -> None:
        """Restoring 'back' to a value that was already wrong would cement it."""
        fake = gcloud()
        fake.target = "some-other-project"
        with pytest.raises(proof.KillSwitchProofError, match="Refusing to run"):
            _run()

    def test_a_scratch_already_without_billing_is_refused(self, gcloud) -> None:
        """Otherwise the proof passes without the switch having done anything."""
        fake = gcloud()
        fake.billing[SCRATCH] = False
        with pytest.raises(proof.KillSwitchProofError, match="already has billing disabled"):
            _run()


def test_the_published_message_matches_the_real_schema(gcloud) -> None:
    """A message carrying a target field would exercise a branch production
    never reaches — the test would prove a test-only path."""
    import json

    fake = gcloud(billing_after_fire=False)
    _run()
    published = [c for c in fake.calls if c[:3] == ("pubsub", "topics", "publish")]
    assert len(published) == 1
    payload = json.loads(published[0][published[0].index("--message") + 1])
    assert set(payload) == set(proof._SCHEMA_KEYS)
    assert not any("project" in k.lower() for k in payload), f"the synthetic message names a project: {payload}"
