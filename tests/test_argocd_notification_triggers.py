"""Every trigger that reads `operationState` must survive it being nil.

Argo CD evaluates a trigger's `when:` with expr-lang, which RAISES on a nil
dereference rather than returning false. A raised expression is a SKIPPED
trigger -- so a trigger that reads `app.status.operationState.phase` without a
guard does not fire during the window where `operationState` is still nil, which
is the instant a sync begins.

That window is exactly when a sync failure happens. Measured on the live hub
2026-08-22, in the notifications controller log:

    failed to execute when condition: cannot fetch phase from <nil> (1:66)
     | app.status.sync.status == 'Unknown' || app.status.operationState.phase in ['Error', 'Failed']

Ten of those, at 03:11:32 and 03:59:38 -- the two timestamps at which a sync
started. `on-sync-failed` TRIGGERED zero times in 24h, and so did
`on-health-degraded`; the only thing that ever fired was `on-sync-succeeded`,
after the state it needs had materialised.

This is the fails-open shape: a trigger that cannot evaluate looks identical to
a trigger reporting nothing wrong. Nothing surfaces the error but this log line,
which nobody reads.

Upstream's own catalog guards it -- `notifications_catalog/triggers/*.yaml` in
argoproj/argo-cd all read `app.status.operationState != nil and ...`. We wrote
ours by hand and dropped the guard.

The assertion is deliberately structural rather than a match on our current
three expressions: it holds for any trigger anyone adds later, which is the
point of a guard over a fix.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
VALUES = REPO_ROOT / "infra/helm/argocd/values.yaml"

# `app.status.operationState` followed by anything other than a comparison --
# i.e. an actual field access. `operationState != nil` is the guard itself and
# must not count as a dereference, or the guard could never be written.
_DEREFERENCE = re.compile(r"app\.status\.operationState\s*(?:\.|\?\.)")


def _triggers() -> dict[str, str]:
    """Every `trigger.*` block in the notifications values, name -> raw body."""
    values = yaml.safe_load(VALUES.read_text())
    triggers = values["notifications"]["triggers"]
    return {name: body for name, body in triggers.items()}


def _when_clauses(body: str) -> list[str]:
    """The `when:` expressions inside one trigger body."""
    parsed = yaml.safe_load(body)
    return [entry["when"] for entry in parsed if "when" in entry]


def test_the_values_file_declares_triggers_at_all():
    """Fail loudly rather than vacuously passing if the block moves or is renamed."""
    triggers = _triggers()
    assert triggers, f"no notifications.triggers found in {VALUES}"


@pytest.mark.parametrize("name", sorted(_triggers()))
def test_a_trigger_reading_operation_state_guards_against_nil(name: str):
    """A dereference of `operationState` must be guarded by `!= nil` in the SAME clause.

    Per-clause, not per-trigger: a trigger with two `when:` entries where only
    one is guarded still goes blind on the other. `operationState == nil or`
    guards the same way, by short-circuit: the success trigger reads the phase
    only when an operation exists (evaluated with expr-lang v1.17.6 on nil,
    absent, Succeeded, Failed and Running).
    """
    for when in _when_clauses(_triggers()[name]):
        if not _DEREFERENCE.search(when):
            continue
        assert "operationState != nil" in when or "operationState == nil or" in when, (
            f"trigger {name!r} dereferences operationState without guarding it:\n"
            f"  {when}\n"
            "expr-lang raises on nil, and a raised expression is a SKIPPED trigger — "
            "so this one cannot fire while a sync is starting, which is when a sync "
            "failure happens. Upstream's catalog reads "
            "`app.status.operationState != nil and ...`."
        )


@pytest.mark.parametrize("name", sorted(_triggers()))
def test_a_when_expression_folds_to_a_single_line(name: str):
    """A folded (`>-`) expression must actually fold.

    The one long expression here is wrapped only to stay inside yamllint's 130
    columns, and YAML folding has a trap: continuation lines must keep the SAME
    indent, because a DEEPER one is treated as literal and keeps its newline.
    The file says so in a comment — this is that comment as a mechanism, since a
    comment fails exactly when someone re-wraps the line.

    Found by mutation: deepening one continuation line by two spaces left the
    other assertions green while putting two newlines inside the expression.
    """
    for when in _when_clauses(_triggers()[name]):
        assert "\n" not in when, (
            f"trigger {name!r} has a newline inside its `when:` expression:\n"
            f"  {when!r}\n"
            "a folded scalar's continuation lines must share one indent level — "
            "a deeper line is literal, not folded."
        )


@pytest.mark.parametrize("name", sorted(_triggers()))
def test_a_trigger_dedupes_per_revision_not_per_condition(name: str):
    """Without `oncePer`, the dedup key is the condition — identical across revisions.

    Measured on the live hub: both applications logged the SAME key,
    `on-sync-succeeded.[0].LpuibPsvUlFP2XzU_R_WZoKwzxY`, across every cycle and
    every revision. A key that does not vary with the revision is a key that
    suppresses the notification for the NEXT deploy, which is the one you wanted.
    """
    parsed = yaml.safe_load(_triggers()[name])
    for entry in parsed:
        assert "oncePer" in entry, (
            f"trigger {name!r} has no `oncePer`, so Argo CD dedupes on the condition "
            "hash instead of the revision — the second deploy of a different revision "
            "is suppressed as 'already sent'."
        )


# --- GITOPS-003 AC1: the commit status Argo CD posts per sync ----------------
#
# `toolkit infra argo wait-status` reads it, so its shape is a contract: the
# status must land on the synced sha, under `argocd/<app>`, with a description
# GitHub accepts. The templates are Go text/template with sprig, rendered by
# the notifications controller; these tests hold their structure without one.

GITHUB_TEMPLATES = ("template.github-status-success", "template.github-status-failure")
GITHUB_TRIGGERS = ("trigger.on-synced-github", "trigger.on-sync-failed-github")
SUCCESS_PATH = "/repos/mlorentedev/kubelab/statuses/{{.app.status.sync.revision}}"
FAILURE_PATH = "/repos/mlorentedev/kubelab/statuses/{{.app.status.operationState.operation.sync.revision}}"
_ACTION = re.compile(r"\{\{.*?\}\}", re.DOTALL)


def _notifications() -> dict:
    return yaml.safe_load(VALUES.read_text())["notifications"]


def _github_webhook(name: str) -> dict:
    return yaml.safe_load(_notifications()["templates"][name])["webhook"]["github"]


def test_a_recipient_is_sent_only_templates_written_for_it():
    """A trigger subscribed for `slack` must send Slack templates, and so on.

    A template with no `webhook.<recipient>` section sent to that recipient is
    behaviour nothing here can test, so the pairing is held instead.
    """
    notifications = _notifications()
    templates = {name.removeprefix("template."): yaml.safe_load(body) for name, body in notifications["templates"].items()}
    for subscription in notifications["subscriptions"]:
        for recipient in subscription["recipients"]:
            for trigger in subscription["triggers"]:
                for entry in yaml.safe_load(notifications["triggers"][f"trigger.{trigger}"]):
                    for template in entry["send"]:
                        assert recipient in templates[template].get("webhook", {}), (
                            f"{trigger} sends {template} to {recipient!r}, which has no webhook.{recipient} section"
                        )


def test_the_github_triggers_are_subscribed_to_the_github_service():
    notifications = _notifications()
    assert "service.webhook.github" in notifications["notifiers"]
    subscribed = {t for s in notifications["subscriptions"] if "github" in s["recipients"] for t in s["triggers"]}
    assert subscribed == {name.removeprefix("trigger.") for name in GITHUB_TRIGGERS}


def test_success_lands_on_every_revision_argo_reports_synced():
    """Green means the cluster is at this sha, not that an operation ran (AC2).

    A commit whose render does not change (a comment, a doc) moves
    `sync.revision` without starting an operation, so a success keyed on the
    operation never reaches it and the scheduled sweep would read "no status"
    as red. Measured 2026-10-22: the first live status came from a
    drift-correcting operation, not from a merge.
    """
    triggers = _notifications()["triggers"]
    senders = [
        (name, entry)
        for name, body in triggers.items()
        for entry in yaml.safe_load(body)
        if "github-status-success" in entry["send"]
    ]
    assert len(senders) == 1, f"exactly one trigger may post success, found {[n for n, _ in senders]}"
    name, entry = senders[0]
    assert name == "trigger.on-synced-github"
    assert entry["when"] == (
        "app.status.sync.status == 'Synced' and (app.status.operationState == nil or "
        "app.status.operationState.phase == 'Succeeded')"
    )
    assert entry["oncePer"] == "app.status.sync.revision"
    assert _github_webhook("template.github-status-success")["path"] == SUCCESS_PATH


def test_success_is_withheld_while_the_last_operation_did_not_succeed():
    """A failed PostSync hook leaves the app Synced: success must not bury the failure.

    Both triggers would otherwise post for the same sha, and the newer status
    wins. Running is withheld too, so success lands once the operation ends.
    """
    when = yaml.safe_load(_notifications()["triggers"]["trigger.on-synced-github"])[0]["when"]
    assert "app.status.operationState.phase == 'Succeeded'" in when
    assert "operationState == nil or" in when


def test_success_reads_nothing_from_the_last_operation():
    """On a no-op revision the last operation belongs to an older commit.

    Its message, or its revision, would describe a sync that is not this one.
    """
    assert "operationState" not in _notifications()["templates"]["template.github-status-success"]


def test_failure_lands_on_the_operation_revision_never_on_sync_result():
    """The failure status fires exactly when `syncResult` may be nil.

    An operation that errors before producing a result (the 2026-08-27 panic)
    has no `syncResult`, and Go templates on an unstructured map fail on
    `.syncResult.revision` there. An automated sync carries the resolved sha in
    `operation.sync.revision` (measured on both Applications, GITOPS-003). A
    manual sync from the UI is unverified: a non-sha there gets a 422 from
    GitHub, and only the notifications log says so.
    """
    webhook = _github_webhook("template.github-status-failure")
    assert webhook["method"] == "POST"
    assert webhook["path"] == FAILURE_PATH
    assert "syncResult" not in _notifications()["templates"]["template.github-status-failure"]
    (entry,) = yaml.safe_load(_notifications()["triggers"]["trigger.on-sync-failed-github"])
    assert entry["oncePer"] == "app.status.operationState?.operation?.sync?.revision"


@pytest.mark.parametrize(("name", "state"), [(GITHUB_TEMPLATES[0], "success"), (GITHUB_TEMPLATES[1], "failure")])
def test_the_status_body_is_json_with_exactly_the_status_fields(name: str, state: str):
    body = _github_webhook(name)["body"]
    actions = _ACTION.findall(body)
    # An action inside a string becomes text, the bare one (description) a string,
    # so what parses is the body's own structure.
    parsed = json.loads(_ACTION.sub(lambda m: '"x"' if "toJson" in m.group() else "x", body))
    assert set(parsed) == {"state", "context", "description", "target_url"}
    assert parsed["state"] == state
    assert '"context": "argocd/{{.app.metadata.name}}"' in body
    assert parsed["target_url"].startswith("https://argo.kubelab.live/applications/argocd/")
    (description,) = [a for a in actions if "toJson" in a]
    # Unquoted in the body: `toJson` supplies the quotes and escapes the message.
    assert f'"description": {description}' in body
    assert "trunc 140" in description and description.rstrip("} ").endswith("toJson")
    if "operationState.message" in description:
        # `default` before `trunc`: a nil message would make trunc fail the render.
        assert description.index("default") < description.index("trunc")
