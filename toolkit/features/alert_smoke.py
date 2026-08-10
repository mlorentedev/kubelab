"""OBS-007 end-to-end smoke test for the certificate-alerting path.

Induces a real ACME failure, waits for the alert rule to fire, confirms Apprise
delivered a notification, tears the failure down, and confirms the rule clears
with a resolved notification. The whole loop, against the real cluster.

**Why this exists as a command rather than a runbook step.** Phase 3 of OBS-007
proved the alert works by hand, once. A proof nobody can repeat decays into a
claim: the query, the contact point, the notification policy and the payload
template are four independent things that can each rot silently, and every one of
them is invisible until a certificate actually fails. This makes re-proving it a
single command.

**Why a `.local` host.** Let's Encrypt rejects it at the `new-order` step with
`rejectedIdentifier`, *before* any DNS-01 challenge is attempted — so nothing is
written to Cloudflare and no failed-validation rate limit is consumed. It also
reproduces the exact shape of the real prod failure that motivated the spec
(#927) rather than a different one that happens to be convenient.

**Staging only, enforced rather than documented.** Prod's notification policy
routes to the `page` tier, so running this there would wake someone up to prove
that waking someone up works.

Design mirrors `notify_smoke.py`: pure helpers plus a runner with injectable
collaborators, so the orchestration is unit-testable without a cluster.
"""

from __future__ import annotations

import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass

from toolkit.core.logging import logger

#: Throwaway objects carry this name in every environment. Fixed rather than
#: random so an interrupted run leaves something findable and deletable.
PROBE_NAME = "obs007-induced-failure"
PROBE_HOST = f"{PROBE_NAME}.kubelab.local"
RULE_TITLE = "ACME certificate failure"

#: Only staging. Prod pages.
ALLOWED_ENVS = ("staging",)

#: Rule evaluation is every 5m with `for: 5m`, so firing takes ~10m; recovery
#: needs the failures to age out of the rule's own [10m] window. Generous, and
#: bounded — an unbounded wait in a smoke test is a hang, not a check.
FIRING_TIMEOUT_S = 900
RESOLVE_TIMEOUT_S = 1200
POLL_INTERVAL_S = 30

PROBE_MANIFEST = f"""
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: {PROBE_NAME}
  namespace: kubelab
  labels:
    kubelab.live/throwaway: "obs007-alert-smoke"
  annotations:
    kubelab.live/purpose: >-
      OBS-007 alert smoke test. Induces an ACME failure on purpose so the
      alerting path can be re-proved. Safe to delete at any time:
      kubectl delete ingressroute {PROBE_NAME} -n kubelab
spec:
  entryPoints: [websecure]
  routes:
    - match: Host(`{PROBE_HOST}`)
      kind: Rule
      services:
        - name: grafana
          port: 3000
  tls:
    certResolver: letsencrypt
"""

#: (args) -> CompletedProcess. Injectable so the runner is testable offline.
KubectlFn = Callable[[list[str], str | None], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class SmokeResult:
    """What the smoke observed, so the caller can report rather than guess."""

    fired: bool
    notified: bool
    resolved: bool
    resolve_notified: bool
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.fired and self.notified and self.resolved and self.resolve_notified


def strip_ansi(text: str) -> str:
    """Remove terminal colour codes.

    Not cosmetic. Traefik colours its output, and the escapes sit *between* a
    field name and its value — `\\x1b[36mdomains=\\x1b[0m["host"]` — so a naive
    match spanning that boundary silently finds nothing.
    """
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def count_acme_errors(traefik_logs: str) -> int:
    """ACME lines that also carry an error indicator.

    Deliberately the same shape as the alert rule's own LogQL: match ACME lines
    that look like failures, rather than matching ACME lines and excluding the
    known heartbeat by name. A denylist would count `Starting provider
    *acme.Provider`, which Traefik logs on every boot.
    """
    clean = strip_ansi(traefik_logs)
    return sum(
        1
        for line in clean.splitlines()
        if re.search(r"(?i)acme", line) and re.search(r"(?i)\b(err|unable|fail(ed|ure)?)\b", line)
    )


def count_deliveries(apprise_logs: str) -> int:
    """Notifications Apprise reports as actually delivered."""
    return len(re.findall(r"Delivered Notification", apprise_logs))


def rule_state(rules_json: str, title: str = RULE_TITLE) -> str:
    """State of the named rule: `firing`, `inactive`, `pending`, or `absent`."""
    import json

    try:
        data = json.loads(rules_json)
    except (ValueError, TypeError):
        return "unreadable"
    for group in data.get("data", {}).get("groups", []):
        for rule in group.get("rules", []):
            if rule.get("name") == title:
                return str(rule.get("state", "unknown"))
    return "absent"


def _default_kubectl(env: str) -> KubectlFn:
    import os

    kubeconfig = os.path.expanduser(f"~/.kube/kubelab-{env}-config")

    def run(args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["kubectl", "--kubeconfig", kubeconfig, *args],
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
            timeout=90,
        )

    return run


def run_alert_smoke(
    env: str,
    *,
    kubectl: KubectlFn | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> SmokeResult:
    """Induce a certificate failure, prove the alert fires and clears, clean up."""
    logger.section(f"alert-smoke — {env.upper()}")

    if env not in ALLOWED_ENVS:
        logger.error(
            f"alert-smoke refuses to run against '{env}'. It induces a REAL certificate "
            f"failure, and prod's notification policy routes to the page tier — this "
            f"would wake someone up to demonstrate that waking someone up works. "
            f"Allowed: {', '.join(ALLOWED_ENVS)}."
        )
        return SmokeResult(False, False, False, False, detail=f"refused for env={env}")

    kubectl = kubectl or _default_kubectl(env)

    def deliveries() -> int:
        return count_deliveries(kubectl(["logs", "-n", "kubelab", "deploy/apprise", "--tail=300"], None).stdout)

    def state() -> str:
        result = kubectl(
            [
                "exec",
                "-n",
                "kubelab",
                "deploy/grafana",
                "--",
                "wget",
                "-qO-",
                "http://localhost:3000/api/prometheus/grafana/api/v1/rules",
            ],
            None,
        )
        return rule_state(result.stdout)

    baseline = deliveries()
    if (initial := state()) == "absent":
        logger.error(
            f"No {RULE_TITLE!r} rule is provisioned in {env}. There is nothing to smoke — "
            f"deploy the alerting ConfigMap first (make deploy-k8s ENV={env})."
        )
        return SmokeResult(False, False, False, False, detail="rule not provisioned")
    logger.info(f"Baseline: rule={initial}  apprise deliveries={baseline}")

    fired = notified = resolved = resolve_notified = False
    try:
        logger.info(f"Inducing an ACME failure: {PROBE_HOST}")
        applied = kubectl(["apply", "-f", "-"], PROBE_MANIFEST)
        if applied.returncode != 0:
            logger.error(f"Could not apply the probe route: {applied.stderr.strip()}")
            return SmokeResult(False, False, False, False, detail="apply failed")

        fired = _await(lambda: state() == "firing", FIRING_TIMEOUT_S, "rule to fire", sleep=sleep, now=now)
        if fired:
            notified = _await(lambda: deliveries() > baseline, 120, "the firing notification", sleep=sleep, now=now)
    finally:
        # Always remove the induced failure, including on timeout or Ctrl-C.
        # Leaving it behind means Traefik retries an impossible order forever,
        # which is the exact bug this whole spec exists to catch.
        logger.info("Removing the induced failure")
        kubectl(["delete", "ingressroute", PROBE_NAME, "-n", "kubelab", "--ignore-not-found"], None)

    if fired:
        after_firing = deliveries()
        resolved = _await(lambda: state() != "firing", RESOLVE_TIMEOUT_S, "rule to clear", sleep=sleep, now=now)
        if resolved:
            resolve_notified = _await(
                lambda: deliveries() > after_firing, 120, "the resolved notification", sleep=sleep, now=now
            )

    result = SmokeResult(fired, notified, resolved, resolve_notified)
    _report(result)
    return result


def _await(
    predicate: Callable[[], bool],
    timeout_s: int,
    what: str,
    *,
    sleep: Callable[[float], None],
    now: Callable[[], float],
) -> bool:
    """Poll until true or the deadline passes. Returns whether it became true."""
    deadline = now() + timeout_s
    while now() < deadline:
        if predicate():
            logger.success(f"  {what}: observed")
            return True
        sleep(POLL_INTERVAL_S)
    logger.error(f"  {what}: NOT observed within {timeout_s}s")
    return False


def _report(result: SmokeResult) -> None:
    """State each stage separately — a single pass/fail hides which link broke."""
    for label, value in (
        ("rule fired on a real failure", result.fired),
        ("firing notification delivered", result.notified),
        ("rule cleared after teardown", result.resolved),
        ("resolved notification delivered", result.resolve_notified),
    ):
        logger.info(f"  {label}: {'ok' if value else 'FAIL'}")

    if result.ok:
        logger.success("alert-smoke passed — confirm both messages landed in Telegram")
    else:
        logger.error(
            "alert-smoke FAILED. A rule that fires but never clears is as broken as one "
            "that never fires: people learn to ignore both."
        )
