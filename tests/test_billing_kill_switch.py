"""The kill switch must fire when it should, and only then.

`infra/terraform/gcp-bootstrap/function/main.py` detaches a project's billing
account. It is the one piece of this repository that can stop every billable
resource under an account, and it runs unattended, months after anyone last read
it, triggered by a message nobody sees.

Its two failure modes are opposite and both silent:

- **Fires when it should not** -- budgets publish on every threshold and
  periodically besides, so most messages are routine. A detach on one of those
  takes the hub down for no reason.
- **Does not fire when it should** -- the bill keeps growing, and the only
  signal is the absence of an event.

These tests run the real module against fabricated Cloud Events with the billing
API stubbed. No GCP, no credentials, no network.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

FUNCTION_DIR = Path(__file__).resolve().parent.parent / "infra/terraform/gcp-bootstrap/function"


@pytest.fixture
def killswitch(monkeypatch: pytest.MonkeyPatch):
    """Import the function module with its GCP dependencies stubbed.

    `functions_framework`, `google.auth` and `googleapiclient` are the function's
    runtime, installed in the Cloud Functions image and deliberately NOT a
    dependency of this repository -- vendoring them to run a test would be a
    second declaration of the runtime.
    """
    monkeypatch.setitem(sys.modules, "functions_framework", SimpleNamespace(cloud_event=lambda fn: fn))

    # `import google.auth` needs `google` itself present as a module, not just
    # the submodule entry -- and `from googleapiclient import discovery` needs
    # the parent to carry `discovery` as an attribute. Registering only the
    # dotted names leaves both imports failing on the package.
    auth = SimpleNamespace(default=lambda scopes: (MagicMock(), "project"))
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(auth=auth))
    monkeypatch.setitem(sys.modules, "google.auth", auth)

    discovery = SimpleNamespace(build=MagicMock())
    monkeypatch.setitem(sys.modules, "googleapiclient", SimpleNamespace(discovery=discovery))
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", discovery)

    spec = importlib.util.spec_from_file_location("killswitch_under_test", FUNCTION_DIR / "main.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _event(**payload: object) -> SimpleNamespace:
    """A Cloud Event shaped like a real budget notification.

    The keys are exactly those Google sends: a genuine message names NO project
    to act on, which is why the target lives in the environment.
    """
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    return SimpleNamespace(data={"message": {"data": encoded}})


@pytest.fixture
def detach(killswitch, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    spy = MagicMock()
    monkeypatch.setattr(killswitch, "_detach", spy)
    monkeypatch.setenv("TARGET_PROJECT", "kubelab-hub")
    return spy


class TestItFiresWhenItShould:
    def test_cost_over_budget_detaches_the_target(self, killswitch, detach: MagicMock) -> None:
        killswitch.kill_switch(_event(budgetDisplayName="cap", costAmount=16, budgetAmount=15, currencyCode="USD"))
        detach.assert_called_once_with("kubelab-hub")

    def test_cost_exactly_at_budget_detaches(self, killswitch, detach: MagicMock) -> None:
        """The threshold rule fires AT 100%, so equality must act.

        Off by one in the safe-looking direction means the cap never fires on the
        message the budget actually sends at its threshold.
        """
        killswitch.kill_switch(_event(budgetDisplayName="cap", costAmount=15, budgetAmount=15))
        detach.assert_called_once()


class TestItStaysQuietWhenItShould:
    def test_routine_under_threshold_message_does_nothing(self, killswitch, detach: MagicMock) -> None:
        """50% and 90% notifications arrive at the same topic as the 100% one."""
        killswitch.kill_switch(_event(budgetDisplayName="cap", costAmount=7.5, budgetAmount=15))
        detach.assert_not_called()

    def test_a_zero_budget_is_ignored_rather_than_treated_as_exceeded(self, killswitch, detach: MagicMock) -> None:
        """`cost >= budget` is true for 0 >= 0 -- a message reporting NO spend.

        Without the guard, an empty or malformed notification detaches billing.
        """
        killswitch.kill_switch(_event(budgetDisplayName="cap", costAmount=0, budgetAmount=0))
        detach.assert_not_called()

    def test_an_empty_message_does_nothing(self, killswitch, detach: MagicMock) -> None:
        killswitch.kill_switch(SimpleNamespace(data={"message": {}}))
        detach.assert_not_called()


class TestTheTargetComesFromTheEnvironment:
    def test_an_unset_target_refuses_rather_than_guessing(self, killswitch, monkeypatch: pytest.MonkeyPatch) -> None:
        """A kill switch that silently no-ops is indistinguishable from a working
        one, right up until it is needed."""
        monkeypatch.delenv("TARGET_PROJECT", raising=False)
        with pytest.raises(RuntimeError, match="TARGET_PROJECT"):
            killswitch.kill_switch(_event(costAmount=99, budgetAmount=15))

    def test_a_project_named_in_the_payload_is_ignored(self, killswitch, detach: MagicMock) -> None:
        """THE PROPERTY THE WHOLE DESIGN RESTS ON.

        A real notification names no project. If the function honoured one from
        the message, anyone able to publish to the topic could pick the victim --
        and the scratch-project test would exercise a branch production never
        reaches, proving a test-only path.
        """
        killswitch.kill_switch(
            _event(costAmount=16, budgetAmount=15, targetProject="some-other-project", projectId="another")
        )
        detach.assert_called_once_with("kubelab-hub")


class TestTheDetachCallItself:
    def test_it_sends_an_empty_billing_account_name(self, killswitch, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty `billingAccountName` IS the disable operation -- there is no
        separate call, so a non-empty value here would silently re-link instead."""
        update = MagicMock()
        update.execute.return_value = {"billingEnabled": False}
        client = MagicMock()
        client.projects.return_value.updateBillingInfo.return_value = update
        monkeypatch.setattr(killswitch, "_billing_client", lambda: client)

        killswitch._detach("scratch-project")

        client.projects.return_value.updateBillingInfo.assert_called_once_with(
            name="projects/scratch-project", body={"billingAccountName": ""}
        )


def test_there_is_no_dry_run_mode() -> None:
    """Rejected by design: it would skip the one API call that can be wrong.

    Asserted so the idea is refused in code rather than only in prose, since a
    DRY_RUN flag is the obvious thing to add while testing and the obvious thing
    to leave enabled afterwards.

    OVER THE AST, AND THE FIRST VERSION PROVED WHY. Scanning the text, skipping
    only `#` comments, matched the module docstring's own sentence explaining
    that no DRY_RUN mode exists -- failing a module that is correct, for saying
    so. Same defect as lesson-363 one mirror over. Docstrings are excluded here
    by identity, not by pattern.
    """
    import ast

    tree = ast.parse((FUNCTION_DIR / "main.py").read_text())

    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }

    live = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "DRY_RUN" in node.value
        and id(node) not in docstrings
    ]
    assert not live, f"a DRY_RUN path exists in code, not just in prose: {live}"
