"""OBS-042 AC1/AC2: what every Grafana notification says, read from the render.

A notice has to answer, on its own: where (environment), what state, whether it
fired on a real condition or on a silent emitter, and what to do first. Before
OBS-042 the title was `firing: <rule>` in both environments, a no-data firing
looked exactly like a fault, and no notice carried the `runbook_url` every rule
declares (audit of 2026-10-18..11-01, #2929).

These tests read the rendered ConfigMap, so they hold the template's shape. They
cannot prove the template renders: Grafana rejects a bad custom payload at
DELIVERY, not at provisioning (`contact-points.yaml`). That half is proven by a
delivery from Grafana 13.0.2 and recorded in the spec's verification.md.
"""

from __future__ import annotations

import pytest
import yaml

from tests.test_grafana_alerting_render import EXPECTED_RECEIVER, _alerting_configmap

#: The contact points that carry the notice contract, and the tier tag each sends.
APPRISE_CONTACT_POINTS = {"apprise-page": "page", "apprise-log": "log"}


def _templates(env: str) -> str:
    templates = yaml.safe_load(_alerting_configmap(env)["data"]["templates.yaml"])
    return next(t["template"] for t in templates["templates"] if t["name"] == "apprise-body")


def _contact_points(env: str) -> dict[str, dict]:
    cps = yaml.safe_load(_alerting_configmap(env)["data"]["contact-points.yaml"])
    return {cp["name"]: cp for cp in cps["contactPoints"]}


def _rules(env: str) -> list[dict]:
    data = _alerting_configmap(env)["data"]
    rules = []
    for key, text in data.items():
        if not key.endswith("rules.yaml") or key in ("deleted-rules.yaml",):
            continue
        for group in (yaml.safe_load(text) or {}).get("groups", []):
            rules.extend(group.get("rules", []))
    return rules


@pytest.mark.parametrize("env", sorted(EXPECTED_RECEIVER))
class TestNoticeContract:
    def test_both_apprise_contact_points_take_their_title_from_the_shared_define(self, env: str) -> None:
        cps = _contact_points(env)
        for name in APPRISE_CONTACT_POINTS:
            payload = cps[name]["receivers"][0]["settings"]["payload"]["template"]
            assert 'tmpl.Exec "apprise.title"' in payload, (
                f"{env}: contact point {name} builds its own title. The title is part of the "
                f"notice contract and must come from the shared `apprise.title` define, or the "
                f"two tiers drift apart in what they say."
            )

    def test_the_title_names_environment_state_and_reason(self, env: str) -> None:
        body = _templates(env)
        assert '{{- define "apprise.title" -}}' in body, f"{env}: no `apprise.title` define."
        assert "{{ template \"notice.env\" . }}" in body, f"{env}: the title does not name the environment."
        assert ".CommonAnnotations.grafana_state_reason" in body, (
            f"{env}: the title does not mark a no-data or query-error firing."
        )

    def test_the_environment_is_derived_from_the_external_url(self, env: str) -> None:
        """Not a literal per overlay: `.ExternalURL` already differs per env (OBS-007 AC4)."""
        body = _templates(env)
        assert 'match "\\\\.staging\\\\." .ExternalURL' in body, (
            f"{env}: the environment name is not derived from `.ExternalURL`."
        )

    def test_the_body_states_the_cause_of_a_no_data_or_error_firing(self, env: str) -> None:
        body = _templates(env)
        for reason in ("NoData", "Error"):
            assert f'eq .Annotations.grafana_state_reason "{reason}"' in body, (
                f"{env}: a firing caused by {reason} reads exactly like a fault."
            )

    def test_the_body_carries_the_runbook(self, env: str) -> None:
        assert "{{ .Annotations.runbook_url }}" in _templates(env), (
            f"{env}: the notice names no first move, though every rule declares a runbook_url."
        )

    def test_every_rule_declares_a_runbook_and_a_summary(self, env: str) -> None:
        missing = [
            r["title"]
            for r in _rules(env)
            if not r.get("annotations", {}).get("runbook_url") or not r.get("annotations", {}).get("summary")
        ]
        assert not missing, f"{env}: rules whose notice would carry no runbook or no summary: {missing}"
