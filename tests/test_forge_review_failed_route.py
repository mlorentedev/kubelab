"""TOOL-093 (#1957) -- the failure alert reaches n8n, authenticated, without losing the page.

The rule `tool093-reviewer-failed` tells the operator that PR-Agent logged `Failed to
review PR`. The author of the PR still sees nothing, so a second receiver sends the same
alert to the n8n workflow that comments on the PR. This file pins the route in the
RENDERED manifests (`kubectl kustomize`, as `test_grafana_alerting_render.py` does and for
its reason: a patch that reads right and changes nothing), and the wiring of the one
secret it carries.

Measured 2026-10-18 on `grafana/grafana-oss:13.0.2`, the pinned image, with these exact
settings provisioned and a rule firing: the webhook arrived at the path below with
`Authorization: Bearer <value of $N8N_WEBHOOK_SECRET>` and Grafana's stock JSON body
(`alerts[].labels.pr` carrying the PR URL), and `$N8N_WEBHOOK_SECRET` in the provisioning
file was expanded from the container's environment.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
import yaml

from tests.test_grafana_alerting_render import _alerting_configmap, _kustomize
from tests.test_reviewer_failure_alert import UID, _rule
from toolkit.features.k8s_secrets import SECRET_DEFINITIONS
from toolkit.features.n8n_import import N8N_IMPORT_CATALOG
from toolkit.features.secrets_manager import SECRET_CATALOG

RECEIVER = "forge-review-failed"
URL = "http://n8n:5678/webhook/forge-review-failed"
ENVS = ["staging", "prod"]
NOTIFY_SECRET = "apps.services.automation.notify.webhook_secret"


def _contact_points(env: str) -> list[dict[str, Any]]:
    cm = _alerting_configmap(env)
    points: list[dict[str, Any]] = []
    for key, text in cm["data"].items():
        points += (yaml.safe_load(text) or {}).get("contactPoints", []) if key.startswith("contact-points") else []
    return points


def _policy(env: str) -> dict[str, Any]:
    policy: dict[str, Any] = yaml.safe_load(_alerting_configmap(env)["data"]["policies.yaml"])["policies"][0]
    return policy


def _grafana_env(env: str) -> list[dict[str, Any]]:
    deployment = next(
        d for d in _kustomize(f"infra/k8s/overlays/{env}") if d.get("kind") == "Deployment" and d["metadata"]["name"] == "grafana"
    )
    env_list: list[dict[str, Any]] = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
    return env_list


@pytest.mark.parametrize("env", ENVS)
def test_the_contact_point_posts_to_the_workflow_with_a_bearer_read_from_the_environment(env: str) -> None:
    point = next((p for p in _contact_points(env) if p["name"] == RECEIVER), None)
    assert point is not None, f"{env} renders no contact point {RECEIVER!r}"

    (receiver,) = point["receivers"]
    settings = receiver["settings"]
    assert receiver["type"] == "webhook"
    assert settings["url"] == URL
    assert settings["authorization_scheme"] == "Bearer"
    assert re.fullmatch(r"\$[A-Z0-9_]+", settings["authorization_credentials"]), (
        "the credential must be an environment reference Grafana expands, never a value in a ConfigMap"
    )
    # A resolved notification would arrive as a second POST for a PR that has not changed.
    assert receiver["disableResolveMessage"] is True


@pytest.mark.parametrize("env", ENVS)
def test_the_environment_variable_the_contact_point_names_is_one_grafana_receives(env: str) -> None:
    """Grafana expands `$NAME` from its own environment. A name the pod does not define expands to
    nothing, the contact point still provisions, and every delivery is refused with a 403 that
    reads like a workflow problem."""
    point = next(p for p in _contact_points(env) if p["name"] == RECEIVER)
    name = point["receivers"][0]["settings"]["authorization_credentials"].lstrip("$")

    entry = next((e for e in _grafana_env(env) if e["name"] == name), None)
    assert entry is not None, f"{name} is referenced by the contact point and defined nowhere in the pod"
    ref = entry["valueFrom"]["secretKeyRef"]
    assert (ref["name"], ref["key"]) == ("grafana-admin", "n8n-webhook-secret")


def test_the_secret_is_the_one_the_workflows_inbound_credential_will_be_built_from() -> None:
    """Every n8n webhook is authenticated by the notify secret (`Header Auth`, imported from SOPS).
    Grafana sends the same value, so the two can only disagree if one side reads another key."""
    mapping = next(m for m in SECRET_DEFINITIONS if m.name == "grafana-admin")
    flattened = mapping.keys["n8n-webhook-secret"]
    assert flattened == NOTIFY_SECRET.upper().replace(".", "_")
    assert NOTIFY_SECRET in {s.secret_key_path for s in N8N_IMPORT_CATALOG}

    spec = next(s for s in SECRET_CATALOG if s.key_path == NOTIFY_SECRET)
    assert "grafana" in spec.services, "rotating it breaks Grafana's delivery; the audit must say so"


def _matches(route: dict[str, Any], labels: dict[str, str]) -> bool:
    return all(labels.get(name) == value for name, op, value in route.get("object_matchers", []) if op == "=")


def _receivers(policy: dict[str, Any], labels: dict[str, str]) -> list[str]:
    """Who an alert reaches, by Alertmanager's walk: the first matching child, then on through
    siblings only while a match says `continue`; the node's own receiver only when no child matched.
    (Not nested here, so one level is the whole tree.)"""
    reached: list[str] = []
    for route in policy.get("routes", []):
        if _matches(route, labels):
            reached.append(route["receiver"])
            if not route.get("continue"):
                break
    return reached or [policy["receiver"]]


@pytest.mark.parametrize("env", ENVS)
def test_the_failure_alert_reaches_the_operator_and_the_pr_and_nothing_else_changes(env: str) -> None:
    """The effect, not the shape: `continue` on the new route does not also notify the root. An earlier
    draft had only that route, and the failure alert stopped paging while reaching n8n."""
    tier = {"staging": "apprise-log", "prod": "apprise-page"}[env]
    policy = _policy(env)
    title = _rule()["title"]

    assert _receivers(policy, {"alertname": title}) == [tier, RECEIVER], (
        "matched by alertname, derived from the rule (uid %s): a renamed rule would otherwise be orphaned" % UID
    )
    assert _receivers(policy, {"alertname": "Traefik certificate expiring"}) == [tier]
    assert RECEIVER in {p["name"] for p in _contact_points(env)}


@pytest.mark.parametrize("env", ENVS)
def test_a_failure_is_not_announced_again_while_it_stays_firing(env: str) -> None:
    """The alert stays firing for the rule's 15 minute window; repeating it would comment twice."""
    (route,) = [r for r in _policy(env)["routes"] if r["receiver"] == RECEIVER]
    assert route["repeat_interval"] == "24h"
