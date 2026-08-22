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
    one is guarded still goes blind on the other.
    """
    for when in _when_clauses(_triggers()[name]):
        if not _DEREFERENCE.search(when):
            continue
        assert "operationState != nil" in when, (
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
