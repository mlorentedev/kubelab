"""Infrastructure: Grafana alerting is provisioned from git, not clicked into the UI.

OBS-007. Grafana held zero alert rules and zero contact points when this spec was
written — measured, not assumed — so there was nothing watching certificate
renewal and a five-week staging outage in June 2026 was found by a browser error.

These assertions read Grafana's *provisioning* API rather than the filesystem.
That distinction is the point: a mounted ConfigMap proves a file arrived, whereas
the provisioning API proves Grafana parsed it and accepted it. A malformed rule
mounts perfectly and provisions nothing.

Two deliberate choices about how the API is reached, both from review on #953:

  - **`kubectl port-forward` plus a local HTTP client, not `kubectl exec … wget`.**
    The provisioning API is admin-only, and passing `Authorization: Basic …` as an
    exec argument puts the credential where `ps` can read it locally AND inside the
    `pods/exec` request URI, which the API server's audit log retains. With a
    port-forward the header never leaves this process.
  - **Argument lists, never `shell=True`.** `env` arrives from the `--env` pytest
    option, so interpolating it into a shell string would let its value execute.

Auth note: the admin username is READ FROM THE SECRET, never hardcoded — see
AUTH-002 (#951), where prod's Grafana database kept the built-in `admin` because
`GF_SECURITY_ADMIN_USER` is honoured only at database creation while the Secret
has declared `manu` for months.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from typing import Any

import pytest

pytestmark = pytest.mark.infra

_KUBECONFIG_PATTERN = "~/.kube/kubelab-{env}-config"
_PORT_FORWARD_READY_TIMEOUT = 20.0

#: The Apprise endpoint the contact points must target. Stated literally rather
#: than parsed from the manifest under test: a test that reads its expectation
#: from the file it validates compares intent against intent and passes for any
#: value (docs/lessons.md, 2026-08-09 — `tls: {}`).
EXPECTED_APPRISE_URL = "http://apprise:8000/notify/kubelab"

#: Which Apprise tier each environment must actually route to. Prod pages,
#: staging archives (ADR-044 tiers). An environment absent from this map is a
#: hard failure, not a skip: `--env` accepts any string, and silently passing on
#: an unknown environment would make this whole module vacuous for that value.
EXPECTED_TAG_BY_ENV = {"staging": "log", "prod": "page"}

#: Title of the rule OBS-007 phase 2 provisions. Literal on purpose.
EXPECTED_RULE_TITLE = "ACME certificate failure"


def _kubeconfig(env: str) -> str:
    """Path to the per-environment kubeconfig."""
    return os.path.expanduser(_KUBECONFIG_PATTERN.format(env=env))


def _kubectl(args: list[str], env: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    """Run kubectl with a fixed argument list — no shell, so `env` cannot execute."""
    return subprocess.run(
        ["kubectl", "--kubeconfig", _kubeconfig(env), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _secret_value(env: str, key: str) -> str:
    """Decode one key of the `grafana-admin` Secret."""
    result = _kubectl(
        ["get", "secret", "grafana-admin", "-n", "kubelab", "-o", f"jsonpath={{.data.{key}}}"],
        env,
    )
    if result.returncode != 0 or not result.stdout.strip():
        pytest.skip(f"Secret grafana-admin has no '{key}' in {env}: {result.stderr.strip()}")
    return base64.b64decode(result.stdout.strip()).decode()


#: A callable that GETs a provisioning path and returns the parsed body.
ProvisioningGet = Callable[[str], Any]


@pytest.fixture(scope="module")
def grafana_api(env: str) -> Iterator[ProvisioningGet]:
    """Yield an authenticated getter for Grafana's provisioning API.

    Opens one `kubectl port-forward` for the module and closes it afterwards. The
    local port is chosen by the kernel and read back from kubectl's output, so
    concurrent sessions (this repo is worked in parallel worktrees) cannot collide
    on a hardcoded port.
    """
    if not os.path.exists(_kubeconfig(env)):
        pytest.skip(f"Kubeconfig not found: {_kubeconfig(env)}")
    if _kubectl(["get", "deploy", "grafana", "-n", "kubelab", "-o", "name"], env, timeout=15).returncode != 0:
        pytest.skip(f"Grafana unreachable in {env}")

    user = _secret_value(env, "admin-user")
    auth = base64.b64encode(f"{user}:{_secret_value(env, 'password')}".encode()).decode()

    proc = subprocess.Popen(
        ["kubectl", "--kubeconfig", _kubeconfig(env), "port-forward",
         "-n", "kubelab", "deploy/grafana", ":3000"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        port = _await_port(proc)
        if port is None:
            pytest.skip(f"port-forward to Grafana in {env} never became ready")

        def get(path: str) -> Any:
            """GET one provisioning path over the open port-forward."""
            return _get_provisioning(port, auth, path, env=env, user=user)

        yield get
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _await_port(proc: subprocess.Popen[str]) -> int | None:
    """Read the local port kubectl chose, or None if it never reported one."""
    deadline = time.monotonic() + _PORT_FORWARD_READY_TIMEOUT
    assert proc.stdout is not None
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                return None
            continue
        if match := re.search(r"Forwarding from 127\.0\.0\.1:(\d+)", line):
            return int(match.group(1))
    return None


def _get_provisioning(port: int, auth: str, path: str, *, env: str, user: str) -> Any:
    """GET a provisioning path, keeping three outcomes distinct.

    Collapsing them is how a check comes to report success on the very thing it
    exists to catch:

      - transport failure -> skip (the cluster could not be asked)
      - HTTP 401          -> skip naming #951 (the DECLARED identity was refused;
                             an identity defect, not an alerting one)
      - HTTP 200          -> return the parsed body, and let the caller assert

    A 401 must never surface as "no contact points" — that would read as this
    spec's own failure and send the next person to entirely the wrong file.
    """
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/v1/provisioning/{path}",
        headers={"Authorization": f"Basic {auth}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            pytest.skip(
                f"Grafana in {env} refused the admin user '{user}' declared in the "
                f"grafana-admin Secret (HTTP 401). This is AUTH-002 (#951) — the "
                f"database kept a different username — NOT an alerting defect. "
                f"OBS-007 cannot be verified in {env} until #951 is fixed."
            )
        pytest.skip(f"Grafana provisioning API returned HTTP {exc.code} in {env}")
    except (urllib.error.URLError, TimeoutError) as exc:
        pytest.skip(f"Could not reach Grafana's provisioning API in {env}: {exc}")


def _expected_tag(env: str) -> str:
    """The tier `env` must route to. Unknown environments fail rather than skip."""
    if env not in EXPECTED_TAG_BY_ENV:
        pytest.fail(
            f"No expected Apprise tier declared for environment {env!r}. Add it to "
            f"EXPECTED_TAG_BY_ENV — skipping here would make this module silently "
            f"vacuous for that environment."
        )
    return EXPECTED_TAG_BY_ENV[env]


class TestAlertDelivery:
    """The delivery path must exist before any alert rule is worth writing.

    Ordering is deliberate (see specs/OBS-007-cert-expiry-alerting/tasks.md): with
    the contact point proven first, a silent alert in phase 2 can only be the
    query. Build the rule first and a silent alert has two candidate causes and no
    way to separate them.
    """

    def test_contact_points_target_apprise(self, grafana_api: ProvisioningGet, env: str) -> None:
        """Grafana must hold contact points pointing at Apprise.

        Failed before the manifests existed: measured `[]` in staging and prod on
        2026-08-10.
        """
        contact_points = grafana_api("contact-points")

        assert contact_points, (
            f"Grafana in {env} has NO contact points, so a firing alert reaches nobody. "
            f"Expected ones targeting {EXPECTED_APPRISE_URL}."
        )

        urls = [
            cp.get("settings", {}).get("url")
            for cp in contact_points
            if cp.get("type") == "webhook"
        ]
        assert EXPECTED_APPRISE_URL in urls, (
            f"No webhook contact point targets Apprise in {env}. Found: {urls or 'none'}. "
            f"Expected {EXPECTED_APPRISE_URL} (ADR-044: Apprise owns the tag->URL map, "
            f"so this endpoint needs no credential)."
        )

    def test_policy_routes_to_the_tier_for_this_environment(
        self, grafana_api: ProvisioningGet, env: str
    ) -> None:
        """Prod must page and staging must archive — asserted, not assumed.

        Two failures are covered here. Grafana ships a default root policy whose
        receiver is the literal string `empty` (measured in staging on
        2026-08-10), so a contact point can provision cleanly while every alert is
        discarded. And an overlay that merges the wrong way round would leave
        staging paging, which is silent until it wakes someone at 3 AM.
        """
        expected_receiver = f"apprise-{_expected_tag(env)}"
        receiver = grafana_api("policies").get("receiver")

        assert receiver and receiver != "empty", (
            f"Grafana in {env} still routes to the default receiver {receiver!r} — "
            f"alerts are evaluated and then discarded."
        )
        assert receiver == expected_receiver, (
            f"Grafana in {env} routes to {receiver!r}, expected {expected_receiver!r}. "
            f"Prod pages and staging archives (ADR-044 tiers); routing staging to the "
            f"push tier would interrupt for a non-critical, on-demand environment."
        )

    def test_selected_contact_point_carries_the_right_tag(
        self, grafana_api: ProvisioningGet, env: str
    ) -> None:
        """The receiver name is not enough — Apprise routes on the payload tag.

        A contact point could be named `apprise-page` and still carry `tag: log`
        in its payload variables, in which case the policy looks right and every
        page lands silently in the archive channel instead.
        """
        expected_tag = _expected_tag(env)
        expected_receiver = f"apprise-{expected_tag}"

        selected = [
            cp for cp in grafana_api("contact-points") if cp.get("name") == expected_receiver
        ]
        assert selected, (
            f"No contact point named {expected_receiver!r} exists in {env}, so the root "
            f"policy routes to a receiver that is not there."
        )

        tag = selected[0].get("settings", {}).get("payload", {}).get("vars", {}).get("tag")
        assert tag == expected_tag, (
            f"Contact point {expected_receiver!r} in {env} sends Apprise tag {tag!r}, "
            f"expected {expected_tag!r}. The name and the tag have diverged, so alerts "
            f"would be delivered to the wrong Telegram channel while every name looks right."
        )


class TestAcmeAlertRule:
    """The rule that watches certificate renewal (OBS-007 phase 2).

    Phase 1 proved the delivery path with a throwaway rule, so anything failing
    from here is the query rather than the plumbing. That separation is the whole
    reason the phases are ordered this way.
    """

    def test_acme_rule_is_provisioned(self, grafana_api: ProvisioningGet, env: str) -> None:
        """The rule must come from the ConfigMap, not from Grafana's database.

        Reading the provisioning API rather than the mounted file is deliberate:
        a malformed rule mounts perfectly and provisions nothing.
        """
        rules = grafana_api("alert-rules")
        titles = {r.get("title") for r in rules}

        assert EXPECTED_RULE_TITLE in titles, (
            f"Grafana in {env} has no {EXPECTED_RULE_TITLE!r} rule — certificate "
            f"renewal is unwatched. Found: {sorted(t for t in titles if t) or 'no rules at all'}."
        )

    def test_acme_rule_treats_no_data_as_healthy(
        self, grafana_api: ProvisioningGet, env: str
    ) -> None:
        """`noDataState` must be OK, or the rule alerts whenever things are fine.

        A LogQL query matching nothing returns no series rather than zero, so the
        healthy state IS NoData. Left at Grafana's default this rule would fire
        continuously while certificates were renewing perfectly — the exact
        inversion that makes people mute an alert channel.
        """
        rule = next(
            (r for r in grafana_api("alert-rules") if r.get("title") == EXPECTED_RULE_TITLE), None
        )
        if rule is None:
            pytest.skip(f"{EXPECTED_RULE_TITLE!r} not provisioned in {env} — see the test above")

        assert rule.get("noDataState") == "OK", (
            f"{EXPECTED_RULE_TITLE!r} in {env} has noDataState="
            f"{rule.get('noDataState')!r}, expected 'OK'. Healthy means no matching "
            f"log lines, which Loki returns as no series, not as zero."
        )


#: Titles of the two rules OBS-010 provisions. Literal on purpose (docs/lessons.md
#: 2026-08-09 — a test must not read its expectation from the file it validates).
EXPECTED_QUOTA_RULE_TITLES = {
    "requests.memory": "Namespace quota utilization high (requests.memory)",
    "limits.memory": "Namespace quota utilization high (limits.memory)",
}


class TestQuotaUtilizationRules:
    """The rules that watch kubelab's ResourceQuota headroom (OBS-010).

    Delivery (contact points, policy routing, tags) is already proven generically
    by `TestAlertDelivery` above — these tests are specific to what makes this
    pair of rules different from OBS-007's, not a re-check of the shared fabric.
    """

    def test_both_rules_are_provisioned(self, grafana_api: ProvisioningGet, env: str) -> None:
        rules = grafana_api("alert-rules")
        titles = {r.get("title") for r in rules}

        missing = set(EXPECTED_QUOTA_RULE_TITLES.values()) - titles
        assert not missing, (
            f"Grafana in {env} is missing quota utilization rule(s): {missing}. "
            f"Found: {sorted(t for t in titles if t) or 'no rules at all'}."
        )

    def test_rules_treat_no_data_as_a_problem(self, grafana_api: ProvisioningGet, env: str) -> None:
        """`noDataState` must be `Alerting` — the INVERSE of the ACME rule above.

        For quota utilization, silence means the emitter (quota-watcher) stopped
        producing log lines, not that everything is fine. The quota could be at
        100% with nobody told. `noDataState: OK` here would silently disarm the
        alert exactly when a real problem (e.g. the API server under pressure)
        also breaks the emitter.
        """
        rules_by_title = {r.get("title"): r for r in grafana_api("alert-rules")}

        for dimension, title in EXPECTED_QUOTA_RULE_TITLES.items():
            rule = rules_by_title.get(title)
            if rule is None:
                pytest.skip(f"{title!r} not provisioned in {env} — see the test above")

            assert rule.get("noDataState") == "Alerting", (
                f"{title!r} in {env} has noDataState={rule.get('noDataState')!r}, "
                f"expected 'Alerting'. Silence from the {dimension} emitter must be "
                f"treated as a problem, not as health."
            )
            assert rule.get("execErrState") == "Alerting", (
                f"{title!r} in {env} has execErrState={rule.get('execErrState')!r}, "
                f"expected 'Alerting' — a query error means 'we don't know', same as "
                f"no data, and 'we don't know' must alert here, not go quiet."
            )

    def test_rules_persist_through_a_routine_surge(self, grafana_api: ProvisioningGet, env: str) -> None:
        """`for:` must be long enough that a brief admission surge cannot fire this.

        IDP-031 measured a full staging deploy + rollout restart peaking at 87.5%
        of the limits.memory ceiling for well under a minute (2026-08-12). Both
        rules must require the breach to hold for at least 5 minutes — comfortably
        longer than any surge this estate has ever measured — so a routine deploy
        does not train people to ignore this alert. See OBS-010's proposal.md
        Risks section for the full measurement this bound is derived from.
        """
        rules_by_title = {r.get("title"): r for r in grafana_api("alert-rules")}

        for title in EXPECTED_QUOTA_RULE_TITLES.values():
            rule = rules_by_title.get(title)
            if rule is None:
                pytest.skip(f"{title!r} not provisioned in {env} — see the test above")

            assert rule.get("for") == "5m", (
                f"{title!r} in {env} has for={rule.get('for')!r}, expected '5m'. "
                f"Shorter than this and IDP-031's measured surge (87.5% of "
                f"limits.memory, sub-minute) would fire this alert on a routine deploy."
            )
