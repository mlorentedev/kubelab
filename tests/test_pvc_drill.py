"""The drill's teardown must not be reachable only on the happy path.

`ac2-drill-unbound` survived ten days in staging because its removal was a step
someone had to remember after the observation was made (#1583). The cure is that
removal happens in a `finally` in the same call as the assertion, so every one
of these tests asks the same question from a different exit: **did the claim go
away?** -- when the alert fired, when it never fired, when Grafana broke, and
when the operator pressed Ctrl-C.

A test suite that only covered the happy path would pass against the exact code
that produced the incident.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

from toolkit.features import pvc_drill

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DISK_RULES = REPO_ROOT / "infra/k8s/base/services/grafana-alerting/disk-rules.yaml"


class Spy:
    """Records the order of the drill's side effects, so ordering is assertable."""

    def __init__(self, *, exists: bool = False, alerts: list | None = None) -> None:
        self.calls: list[str] = []
        self._exists = exists
        self._alerts = alerts if alerts is not None else []
        #: Which delete blows up. The drill deletes twice -- once to absorb
        #: residue before creating, once to tear down -- and only the second is
        #: the teardown this module exists to guarantee. A spy that failed on
        #: both would raise before anything was created, i.e. would test the
        #: pre-delete and call it a teardown.
        self.delete_raises: Exception | None = None
        self.delete_raises_on_call = 2

    def exists(self) -> bool:
        self.calls.append("exists")
        return self._exists

    def create(self) -> None:
        self.calls.append("create")

    def delete(self) -> None:
        self.calls.append("delete")
        if self.delete_raises is not None and self.deletes == self.delete_raises_on_call:
            raise self.delete_raises

    def fetch_alerts(self) -> list:
        self.calls.append("fetch")
        return self._alerts

    @property
    def deletes(self) -> int:
        return self.calls.count("delete")


FIRING = [{"name": pvc_drill.DRILL_ALERT_NAME, "state": "alerting"}]


def _run(spy: Spy, **kw):
    return pvc_drill.run_drill(
        exists=spy.exists,
        create=spy.create,
        delete=spy.delete,
        fetch_alerts=spy.fetch_alerts,
        sleep=lambda _s: None,
        log=lambda _m: None,
        **kw,
    )


class TestTheClaimAlwaysGoesAway:
    """One question, four exits."""

    def test_when_the_alert_fires(self) -> None:
        spy = Spy(alerts=FIRING)
        result = _run(spy)
        assert result.fired is True
        assert spy.calls[-1] == "delete"

    def test_when_the_alert_never_fires(self) -> None:
        """A drill that times out has still created a claim, and must still remove it."""
        clock = iter([0.0, 0.0, 1.0, 2.0, 999.0, 999.0])
        spy = Spy(alerts=[])
        result = _run(spy, timeout_s=10, now=lambda: next(clock))
        assert result.fired is False
        assert spy.calls[-1] == "delete"

    def test_when_the_alert_poll_raises(self) -> None:
        """Grafana being unreachable is a drill failure, never a reason to leak state."""
        spy = Spy()
        spy.fetch_alerts = _raiser(spy, RuntimeError("grafana unreachable"))  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="grafana unreachable"):
            _run(spy)
        assert spy.calls[-1] == "delete"

    def test_when_the_operator_interrupts(self) -> None:
        """The case the incident actually needs: a human gives up mid-wait.

        A 45-minute drill WILL be interrupted. If Ctrl-C leaks the claim, the
        mechanism has not replaced the reminder, it has only moved it.
        """
        spy = Spy()
        spy.fetch_alerts = _raiser(spy, KeyboardInterrupt())  # type: ignore[method-assign]
        with pytest.raises(KeyboardInterrupt):
            _run(spy)
        assert spy.calls[-1] == "delete"


def _raiser(spy: Spy, exc: BaseException):
    def _fn():
        spy.calls.append("fetch")
        raise exc

    return _fn


class TestIdempotence:
    def test_residue_is_deleted_before_the_new_claim_is_created(self) -> None:
        """Delete-then-create, so an earlier run's leftover is absorbed, not collided with.

        This ordering is what lets the drill be the thing that clears the
        existing `ac2-drill-unbound` rather than needing a hand-run kubectl
        first -- the teardown path gets exercised against a real leftover on its
        very first use.
        """
        spy = Spy(exists=True, alerts=FIRING)
        result = _run(spy)
        assert result.absorbed_residue is True
        assert spy.calls.index("delete") < spy.calls.index("create")

    def test_a_clean_cluster_is_reported_as_such(self) -> None:
        spy = Spy(exists=False, alerts=FIRING)
        assert _run(spy).absorbed_residue is False

    def test_the_delete_tolerates_an_absent_claim(self) -> None:
        """Without --ignore-not-found the finally fails whenever the body did not create."""
        argv = pvc_drill.kubectl_delete_argv("/kc", "x", "kubelab")
        assert "--ignore-not-found" in argv

    def test_the_claim_is_deleted_twice_on_the_happy_path_and_that_is_the_point(self) -> None:
        """Pre-delete and teardown are both unconditional; neither guards the other."""
        spy = Spy(alerts=FIRING)
        _run(spy)
        assert spy.deletes == 2


class TestTeardownFailureIsLoud:
    def test_a_failed_teardown_raises_rather_than_logging(self) -> None:
        """Residue left behind is the defect itself -- it cannot exit 0.

        A log line here would reproduce the incident exactly: the drill would
        report success while the claim stayed live.
        """
        spy = Spy(alerts=FIRING)
        spy.delete_raises = RuntimeError("connection refused")
        with pytest.raises(pvc_drill.DrillTeardownError, match="LIVE in the cluster"):
            _run(spy)

    def test_the_message_names_the_object_and_how_to_clear_it(self) -> None:
        spy = Spy(alerts=FIRING)
        spy.delete_raises = RuntimeError("boom")
        with pytest.raises(pvc_drill.DrillTeardownError) as exc:
            _run(spy)
        assert pvc_drill.DRILL_PVC_NAME in str(exc.value)
        assert "kubectl delete pvc" in str(exc.value)

    def test_a_failed_pre_delete_is_not_dressed_up_as_a_teardown_failure(self) -> None:
        """Failing to absorb residue is a different fault, and nothing was created.

        Reporting it as DrillTeardownError would tell the operator a claim is
        live in the cluster when this run never made one.
        """
        spy = Spy(exists=True, alerts=FIRING)
        spy.delete_raises = RuntimeError("connection refused")
        spy.delete_raises_on_call = 1
        with pytest.raises(RuntimeError, match="connection refused"):
            _run(spy)
        assert "create" not in spy.calls


class TestTheConditionIsReal:
    def test_the_storage_class_cannot_be_satisfied(self) -> None:
        """A claim on a real class would bind as soon as a consumer appeared.

        The drill would then prove nothing, and -- worse -- would leave a bound
        volume rather than a Pending one.
        """
        spec = pvc_drill.drill_pvc_manifest()["spec"]
        assert spec["storageClassName"] == pvc_drill.UNBINDABLE_STORAGE_CLASS
        assert "does-not-exist" in spec["storageClassName"]

    def test_the_claim_explains_itself_to_whoever_finds_it(self) -> None:
        """The original carried no annotation and read as production storage."""
        ann = pvc_drill.drill_pvc_manifest()["metadata"]["annotations"]
        purpose = ann["kubelab.live/purpose"]
        assert "drill" in purpose.lower()
        assert "1583" in purpose

    def test_only_an_alerting_instance_counts(self) -> None:
        """`the alert exists` is a weaker claim than `the alert is firing`."""
        resolved = [{"name": pvc_drill.DRILL_ALERT_NAME, "state": "resolved"}]
        assert pvc_drill.alert_is_firing(resolved) is False
        assert pvc_drill.alert_is_firing(FIRING) is True

    def test_a_different_alert_firing_does_not_satisfy_the_drill(self) -> None:
        other = [{"name": "Node root filesystem disk space critical (>90%)", "state": "alerting"}]
        assert pvc_drill.alert_is_firing(other) is False


class TestTheDrillWatchesTheRuleThatExists:
    """The drill's target is a string; the rule's title is a string in another file.

    Nothing else ties them together, and if they drift the drill waits out its
    full timeout and reports `did NOT fire` -- a false negative that reads
    exactly like a broken alert rule. This is the guard for that.
    """

    def _titles(self) -> set[str]:
        doc = yaml.safe_load(DISK_RULES.read_text())
        return {
            rule["title"]
            for group in doc["groups"]
            for rule in group["rules"]
            if "title" in rule
        }

    def test_the_drill_alert_name_is_a_title_the_repo_declares(self) -> None:
        titles = self._titles()
        # Floor: an empty set would make the membership check vacuous, and this
        # test would then pass against a file that declares no rules at all.
        assert len(titles) >= 2, f"expected disk-rules.yaml to declare rules, got {titles}"
        assert pvc_drill.DRILL_ALERT_NAME in titles

    def test_the_drilled_rule_is_the_pvc_rule_by_uid_too(self) -> None:
        """Title equality alone would survive two rules swapping titles."""
        doc = yaml.safe_load(DISK_RULES.read_text())
        by_title = {
            rule["title"]: rule["uid"]
            for group in doc["groups"]
            for rule in group["rules"]
        }
        assert by_title[pvc_drill.DRILL_ALERT_NAME] == "obs015-pvc-unbound-failure"
