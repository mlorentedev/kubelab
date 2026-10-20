"""TOOL-093 (#1957) -- n8n holds a Gitea credential of its own, imported from SOPS like the SMTP one.

The workflow that comments on a PR whose review failed calls the Gitea API, so n8n needs
a Header Auth credential carrying the comment-only token minted for it
(`tests/test_gitea_review_notice_token.py`). It belongs to no single workflow's webhook,
so it is a shared credential: declared once, rendered from the SOPS key the rotation
registry names, upserted once per run.

What is pinned is what n8n and the operator observe, against the fake `kubectl` the SMTP
tests use: the entry that lands in the pod, that it lands before any workflow that
references it, that a missing token fails closed naming the path and printing no value,
and that a workflow carrying both its own webhook credential and this one still imports.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.test_n8n_shared_credentials import _Kubectl, _run, _vault, _without
from toolkit.features.gitea_tokens import ROTATABLE_TOKENS
from toolkit.features.n8n_import import (
    N8N_SHARED_CREDENTIALS,
    N8nImportSpec,
    read_workflow_ids,
)

TOKEN = "GITEA-NOTICE-SENTINEL-9051"
NOTIFY_HEADER = "NOTIFY-HEADER-SENTINEL-7730"
TOKEN_PATH = ROTATABLE_TOKENS["review_notice"].secret_key
OWN_CREDENTIAL_ID = "d4000000-0000-4000-8000-000000000001"


def _gitea() -> Any:
    return next(c for c in N8N_SHARED_CREDENTIALS if c.name == "gitea-review-notice")


def _with_token(token: str = TOKEN) -> dict[str, Any]:
    vault = _vault()
    vault["apps"]["services"].setdefault("core", {}).setdefault("gitea", {})["review_notice_token"] = token
    return vault


def _notifier(tmp_path: Path, ref: dict[str, str] | None = None) -> N8nImportSpec:
    """A workflow with its own webhook credential AND a node calling Gitea with the shared one."""
    ref = ref or {"id": _gitea().credential_id, "name": "gitea-review-notice"}
    doc = {
        "id": "d4000000-0000-4000-8000-0000000000aa",
        "name": "gitea-notifier",
        "nodes": [
            {
                "name": "Webhook",
                "type": "n8n-nodes-base.webhook",
                "credentials": {"httpHeaderAuth": {"id": OWN_CREDENTIAL_ID, "name": "gitea-notifier-webhook"}},
            },
            {"name": "Comment", "type": "n8n-nodes-base.httpRequest", "credentials": {"httpHeaderAuth": ref}},
        ],
        "connections": {},
    }
    (tmp_path / "gitea-notifier.json").write_text(json.dumps(doc))
    return N8nImportSpec(
        workflow_path=Path("gitea-notifier.json"),
        secret_key_path="apps.services.automation.notify.webhook_secret",
        credential_name="gitea-notifier-webhook",
        envs=frozenset({"prod"}),
    )


def test_the_credential_is_a_bearer_header_built_from_the_token_the_registry_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The SOPS path is the rotation registry's, not a second copy: rotating the token
    and importing the credential can never read different keys."""
    assert _gitea().secret_key_path == "apps.services.core.gitea.review_notice_token"

    ok, kubectl = _run(vault=_with_token(), monkeypatch=monkeypatch)

    assert ok
    cred = next(c for c in kubectl.credentials() if c["name"] == "gitea-review-notice")
    assert cred["type"] == "httpHeaderAuth"
    assert cred["id"] == _gitea().credential_id
    assert cred["data"] == {"name": "Authorization", "value": f"Bearer {TOKEN}"}


def test_it_is_imported_in_prod_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """PR-Agent and its failure alert exist in prod; staging has no token to import."""
    assert _gitea().envs == frozenset({"prod"})

    ok, kubectl = _run("staging", vault=_with_token(), monkeypatch=monkeypatch)

    assert ok
    assert "credential:gitea-review-notice" not in kubectl.order()


def test_a_missing_token_fails_the_run_naming_the_path_and_leaving_the_others(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Until the operator mints the token, `make import-n8n` is red, loudly, and prints no value.
    The credentials that do not depend on it still land."""
    ok, kubectl = _run(vault=_without(_with_token(), TOKEN_PATH), monkeypatch=monkeypatch)

    out = " ".join("".join(capsys.readouterr()).split())
    assert ok is False
    assert TOKEN_PATH in out
    assert "credential:gitea-review-notice" not in kubectl.order()
    assert "credential:kubelab-smtp" in kubectl.order()


def test_the_token_travels_on_stdin_never_argv_nor_the_terminal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, kubectl = _run(vault=_with_token(), kubectl=_Kubectl(echo=True), monkeypatch=monkeypatch)

    assert TOKEN not in " ".join(" ".join(c) for c in kubectl.calls)
    assert TOKEN not in "".join(capsys.readouterr())


def test_a_workflow_with_its_own_webhook_credential_and_this_one_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`read_workflow_ids` once took every Header Auth id on a workflow for its own and
    refused two. The shared one is not the workflow's, so it must not count."""
    spec = _notifier(tmp_path)
    doc = json.loads((tmp_path / spec.workflow_path).read_text())
    assert read_workflow_ids(doc) == (doc["id"], OWN_CREDENTIAL_ID)

    vault = _with_token()
    vault["apps"]["services"]["automation"]["notify"]["webhook_secret"] = NOTIFY_HEADER
    ok, kubectl = _run(vault=vault, catalog=[spec], root=tmp_path, monkeypatch=monkeypatch)

    assert ok
    order = kubectl.order()
    assert order.index("credential:gitea-review-notice") < order.index("workflow:gitea-notifier")
    assert "credential:gitea-notifier-webhook" in order


def test_a_reference_that_disagrees_with_the_registry_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A node whose name disagrees with the imported credential would pass the import and
    fail at the workflow's first run, with the PR still saying nothing."""
    spec = _notifier(tmp_path, ref={"id": _gitea().credential_id, "name": "some-other-name"})

    ok, kubectl = _run(vault=_with_token(), catalog=[spec], root=tmp_path, monkeypatch=monkeypatch)

    assert ok is False
    assert "workflow:gitea-notifier" not in kubectl.order()
    assert "is not imported by anything" in " ".join("".join(capsys.readouterr()).split())


def test_a_failed_smtp_import_does_not_hold_back_a_workflow_that_only_needs_the_gitea_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each shared credential is imported on its own. In one batch a bad SMTP relay would have taken
    the Gitea credential down with it, and the failed-review notice with it, for a reason that has
    nothing to do with Gitea."""
    import subprocess

    class _FailsSmtp(_Kubectl):
        def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if cmd[1] == "exec" and '"type": "smtp"' in (kwargs.get("input") or ""):
                raise subprocess.CalledProcessError(1, cmd, stderr="import failed")
            return super().__call__(cmd, **kwargs)

    spec = _notifier(tmp_path)
    vault = _with_token()
    vault["apps"]["services"]["automation"]["notify"]["webhook_secret"] = NOTIFY_HEADER

    ok, kubectl = _run(vault=vault, kubectl=_FailsSmtp(), catalog=[spec], root=tmp_path, monkeypatch=monkeypatch)

    assert ok is False, "the run still reports the SMTP failure"
    assert "credential:gitea-review-notice" in kubectl.order()
    assert "workflow:gitea-notifier" in kubectl.order()
