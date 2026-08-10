"""Infrastructure: Grafana alerting is provisioned from git, not clicked into the UI.

OBS-007. Grafana held zero alert rules and zero contact points when this spec was
written — measured, not assumed — so there was nothing watching certificate
renewal and a five-week staging outage in June 2026 was found by a browser error.

These assertions read Grafana's *provisioning* API rather than the filesystem.
That distinction is the point: a mounted ConfigMap proves a file arrived, whereas
the provisioning API proves Grafana parsed it and accepted it. A malformed rule
mounts perfectly and provisions nothing.

Auth note: the provisioning API is admin-only, so these run through
`kubectl exec` with the credentials from the `grafana-admin` Secret rather than
through the public route as `testuser` (a Viewer, which gets 403). The admin
username is READ FROM THE SECRET, never hardcoded — see AUTH-002 (#951), where
prod's Grafana database kept the built-in `admin` because
`GF_SECURITY_ADMIN_USER` is honoured only at database creation while the Secret
has declared `manu` for months.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
from typing import Any

import pytest

pytestmark = pytest.mark.infra

_KUBECONFIG_PATTERN = "~/.kube/kubelab-{env}-config"

#: The Apprise endpoint the contact point must target. Stated literally rather
#: than parsed from the manifest under test: a test that reads its expectation
#: from the file it validates compares intent against intent and passes for any
#: value (docs/lessons.md, 2026-08-09 — `tls: {}`).
EXPECTED_APPRISE_URL = "http://apprise:8000/notify/kubelab"

#: Per-environment Apprise tag. Prod pages, staging archives (ADR-044 tiers).
EXPECTED_TAG_BY_ENV = {"staging": "log", "prod": "page"}


def _kubeconfig(env: str) -> str:
    return os.path.expanduser(_KUBECONFIG_PATTERN.format(env=env))


def _kubectl(args: str, env: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        f"kubectl --kubeconfig {_kubeconfig(env)} {args}",
        shell=True,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _secret_value(env: str, key: str) -> str:
    result = _kubectl(
        f"get secret grafana-admin -n kubelab -o jsonpath='{{.data.{key}}}'", env
    )
    if result.returncode != 0 or not result.stdout.strip():
        pytest.skip(f"Secret grafana-admin has no '{key}' in {env}: {result.stderr.strip()}")
    return base64.b64decode(result.stdout.strip()).decode()


@pytest.fixture(scope="module")
def grafana_reachable(env: str) -> None:
    """Skip when the cluster or the Grafana pod is not there to answer."""
    if not os.path.exists(_kubeconfig(env)):
        pytest.skip(f"Kubeconfig not found: {_kubeconfig(env)}")
    result = _kubectl("get deploy grafana -n kubelab -o name", env, timeout=15)
    if result.returncode != 0:
        pytest.skip(f"Grafana unreachable in {env}: {result.stderr.strip()}")


def _provisioning(path: str, env: str) -> Any:
    """GET Grafana's provisioning API from inside the pod, as the declared admin.

    Three outcomes are kept distinct on purpose, because collapsing them is how a
    check comes to report success on the thing it exists to catch:

      - transport failure  -> skip (the cluster could not be asked)
      - HTTP 401           -> skip naming #951 (the DECLARED identity was refused;
                              this is an identity defect, not an alerting one)
      - HTTP 200           -> return the parsed body, and let the caller assert

    A 401 must never surface as "no contact points" — that would read as this
    spec's own failure and send the next person to the wrong file entirely.
    """
    user = _secret_value(env, "admin-user")
    password = _secret_value(env, "password")
    auth = base64.b64encode(f"{user}:{password}".encode()).decode()

    result = _kubectl(
        "exec -n kubelab deploy/grafana -- wget -qO- "
        f'--header="Authorization: Basic {auth}" '
        f"http://localhost:3000/api/v1/provisioning/{path}",
        env,
    )

    if result.returncode != 0:
        combined = f"{result.stdout} {result.stderr}"
        if "401" in combined:
            pytest.skip(
                f"Grafana in {env} refused the admin user '{user}' declared in the "
                f"grafana-admin Secret (HTTP 401). This is AUTH-002 (#951) — the "
                f"database kept a different username — NOT an alerting defect. "
                f"OBS-007 cannot be verified in {env} until #951 is fixed."
            )
        pytest.skip(f"Could not query Grafana provisioning API in {env}: {combined.strip()}")

    return json.loads(result.stdout)


class TestAlertDelivery:
    """The delivery path must exist before any alert rule is worth writing.

    Ordering is deliberate (see specs/OBS-007-cert-expiry-alerting/tasks.md): with
    the contact point proven first, a silent alert in phase 2 can only be the
    query. Build the rule first and a silent alert has two candidate causes and no
    way to separate them.
    """

    def test_contact_point_is_provisioned(self, grafana_reachable: None, env: str) -> None:
        """Grafana must hold a contact point pointing at Apprise.

        Fails today: measured `[]` in staging and prod on 2026-08-10.
        """
        contact_points = _provisioning("contact-points", env)

        assert contact_points, (
            f"Grafana in {env} has NO contact points, so a firing alert reaches nobody. "
            f"Expected one targeting {EXPECTED_APPRISE_URL}."
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

    def test_notification_policy_routes_to_apprise(self, grafana_reachable: None, env: str) -> None:
        """A contact point nothing routes to is decoration.

        Grafana ships a default policy whose receiver is the literal string
        `empty` — measured in staging on 2026-08-10. A contact point can therefore
        exist and provision cleanly while every alert still goes nowhere, which is
        precisely the failure this asserts against.
        """
        policy = _provisioning("policies", env)
        receiver = policy.get("receiver")

        assert receiver and receiver != "empty", (
            f"Grafana in {env} still routes to the default receiver "
            f"{receiver!r} — alerts are evaluated and then discarded."
        )
