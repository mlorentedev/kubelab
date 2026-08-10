"""OBS-007: the alert smoke must be able to FAIL, and must always clean up.

A smoke test that cannot report failure is a slogan. These pin the parts that
decide whether it can: the log parsing it judges by, the prod refusal, and the
teardown running even when the rule never fires.

No cluster needed — `kubectl` is injected.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from toolkit.features import alert_smoke as smoke

#: A real Traefik failure line, verbatim from prod on 2026-08-09, ANSI intact.
#: Copied rather than synthesised: the escape sitting between `domains=` and its
#: value is exactly the detail that made three hand-written regexes silently
#: match nothing, and a cleaned-up fixture would hide it again.
REAL_FAILURE = (
    '\x1b[90m2026-08-09T17:04:00Z\x1b[0m \x1b[31mERR\x1b[0m '
    '\x1b[1mUnable to obtain ACME certificate for domains\x1b[0m '
    '\x1b[36merror=\x1b[0m\x1b[31m\x1b[1m"unable to generate a certificate"\x1b[0m\x1b[0m '
    '\x1b[36mdomains=\x1b[0m["loki.internal.kubelab.local"]'
)
REAL_HEARTBEAT = (
    "\x1b[90m2026-08-09T12:00:00Z\x1b[0m \x1b[32mINF\x1b[0m "
    "\x1b[1mTesting certificate renew...\x1b[0m \x1b[36macmeCA=\x1b[0mhttps://acme-v02"
)
REAL_PROVIDER_START = (
    "\x1b[90m2026-08-09T12:00:00Z\x1b[0m \x1b[32mINF\x1b[0m "
    "\x1b[1mStarting provider *acme.Provider\x1b[0m"
)


def _proc(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _rules(state: str) -> str:
    return json.dumps(
        {"data": {"groups": [{"rules": [{"name": smoke.RULE_TITLE, "state": state}]}]}}
    )


class TestLogParsing:
    """What the smoke counts decides what it concludes."""

    def test_counts_a_real_failure_line(self) -> None:
        assert smoke.count_acme_errors(REAL_FAILURE) == 1

    def test_ignores_the_periodic_heartbeat(self) -> None:
        """The heartbeat is an ACME line that is not a failure.

        Counting it would make the smoke pass on a cluster where certificates are
        renewing perfectly and the alert is broken.
        """
        assert smoke.count_acme_errors(REAL_HEARTBEAT) == 0

    def test_ignores_the_provider_startup_line(self) -> None:
        """Traefik logs this on every boot; staging produced 8 in seven days.

        This is why the match requires an error indicator rather than excluding
        the heartbeat by name — a denylist counts this one.
        """
        assert smoke.count_acme_errors(REAL_PROVIDER_START) == 0

    def test_counts_only_the_failure_in_a_mixed_stream(self) -> None:
        stream = "\n".join([REAL_HEARTBEAT, REAL_PROVIDER_START, REAL_FAILURE, REAL_HEARTBEAT])
        assert smoke.count_acme_errors(stream) == 1

    def test_strip_ansi_exposes_the_field_boundary(self) -> None:
        """The escape between `domains=` and its value is the whole trap."""
        assert 'domains=["loki.internal.kubelab.local"]' in smoke.strip_ansi(REAL_FAILURE)


class TestRuleState:
    def test_reads_the_named_rule(self) -> None:
        assert smoke.rule_state(_rules("firing")) == "firing"

    def test_absent_rule_is_not_confused_with_inactive(self) -> None:
        """`absent` must be distinguishable: nothing provisioned is not the same
        as provisioned and quiet, and the runner aborts on one but not the other."""
        assert smoke.rule_state(json.dumps({"data": {"groups": []}})) == "absent"

    def test_unreadable_response_is_not_silently_healthy(self) -> None:
        assert smoke.rule_state("<html>502</html>") == "unreadable"


class TestGuardrails:
    def test_refuses_prod(self) -> None:
        """Prod routes to the page tier. Refused, not merely discouraged."""
        result = smoke.run_alert_smoke("prod", kubectl=lambda *a, **k: _proc())

        assert not result.ok
        assert "refused" in result.detail

    def test_refusing_prod_touches_nothing(self) -> None:
        calls: list[list[str]] = []

        smoke.run_alert_smoke("prod", kubectl=lambda args, stdin=None: (calls.append(args), _proc())[1])

        assert calls == [], "a refused run must not issue a single kubectl call"

    def test_aborts_when_no_rule_is_provisioned(self) -> None:
        """Otherwise the smoke would induce a real failure it cannot observe,
        then report a confusing timeout instead of the actual problem."""
        result = smoke.run_alert_smoke(
            "staging",
            kubectl=lambda args, stdin=None: _proc(json.dumps({"data": {"groups": []}})),
        )

        assert not result.ok
        assert "not provisioned" in result.detail


class TestTeardownAlwaysRuns:
    """The induced failure must never outlive the run."""

    def test_deletes_the_probe_even_when_the_rule_never_fires(self, monkeypatch) -> None:
        """A left-behind probe makes Traefik retry an impossible order forever —
        the exact bug OBS-007 exists to catch, caused by its own test."""
        calls: list[list[str]] = []

        def fake_kubectl(args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
            calls.append(args)
            if "exec" in args:
                return _proc(_rules("inactive"))  # never fires
            return _proc()

        smoke.run_alert_smoke(
            "staging", kubectl=fake_kubectl, sleep=lambda _: None, now=_fake_clock()
        )

        deletes = [c for c in calls if c[0] == "delete"]
        assert deletes, "teardown did not run after the rule failed to fire"
        assert smoke.PROBE_NAME in deletes[0]
        assert "--ignore-not-found" in deletes[0], "teardown must be idempotent"

    def test_reports_each_stage_separately(self, monkeypatch) -> None:
        """One boolean would hide which link broke — fired, notified, cleared and
        resolved are four independent things."""

        def fake_kubectl(args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
            if "exec" in args:
                return _proc(_rules("inactive"))
            return _proc()

        result = smoke.run_alert_smoke(
            "staging", kubectl=fake_kubectl, sleep=lambda _: None, now=_fake_clock()
        )

        assert (result.fired, result.notified, result.resolved, result.resolve_notified) == (
            False, False, False, False,
        )
        assert not result.ok


def _fake_clock():
    """Monotonic clock that races past every timeout, so tests do not wait."""
    ticks = iter(range(0, 10_000_000, 10_000))
    return lambda: float(next(ticks))
