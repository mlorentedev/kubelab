"""Tests for n8n_import — Git+SOPS → n8n workflow/credential import (TOOL-009).

Mirrors the structure of test_k8s_middlewares.py: a pure render function tested
in isolation, plus an orchestrator tested against a mocked subprocess + config
loader. No live cluster, no real SOPS.

Contract under test (resolved against n8n docs + repo SSOT, 2026-06-15):
  - The webhook is protected by n8n Header Auth. The credential's expected header
    value is `Bearer <secret>` (RFC 6750), NOT the bare secret — confirmed with
    the user; n8n's own header-auth docs use `Authorization: Bearer {{token}}`.
  - Both ids are SSOT-ed IN the workflow JSON: the root `id` (workflow upsert +
    `update:workflow --id`) and the node's `httpHeaderAuth.id` (credential link).
  - The secret reaches the pod via stdin → /dev/shm only; it must never appear in
    argv (process table / `ps` leak) and never on persistent disk.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from toolkit.features.n8n_import import (
    N8N_IMPORT_CATALOG,
    import_n8n_workflow,
    read_workflow_ids,
    render_credential,
)

_SECRET_KEY = "apps.services.automation.notify.webhook_secret"
_SOPS_OK = {_SECRET_KEY: "S3CR3T_TOKEN"}
_WORKFLOW_ID = "d1000000-0000-4000-8000-000000000001"
_CREDENTIAL_ID = "c1000000-0000-4000-8000-000000000001"


def _mock_kubectl(*outputs: str) -> MagicMock:
    """subprocess.run mock returning each output in order, exit 0.

    Mirrors test_k8s_middlewares._mock_kubectl for consistency.
    """
    completed = [MagicMock(stdout=o, stderr="", returncode=0) for o in outputs]
    return MagicMock(side_effect=completed)


def _cm(sops: dict[str, str] | None) -> MagicMock:
    """A ConfigurationManager stub whose get_secret_by_path reads from a dict."""
    cm = MagicMock()
    cm.get_secret_by_path.side_effect = lambda path: (sops.get(path) if sops else None)
    return cm


def _workflow_doc() -> dict:
    return {
        "id": _WORKFLOW_ID,
        "name": "notify-router",
        "active": False,
        "nodes": [
            {
                "name": "Webhook notify",
                "type": "n8n-nodes-base.webhook",
                "credentials": {"httpHeaderAuth": {"id": _CREDENTIAL_ID, "name": "notify-webhook"}},
            },
            {"name": "Route by severity", "type": "n8n-nodes-base.code"},
        ],
        "connections": {},
    }


@pytest.fixture
def fake_project(tmp_path: Path) -> Path:
    """project_root with the notify-router workflow JSON in its real relative path."""
    wf_dir = tmp_path / "infra" / "n8n" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "notify-router.json").write_text(json.dumps(_workflow_doc()))
    return tmp_path


def _argv(call) -> list[str]:
    return list(call.args[0])


def _find_call(run_mock: MagicMock, needle: str):
    """First mocked call whose argv contains a token holding `needle`."""
    return next(c for c in run_mock.call_args_list if any(needle in a for a in _argv(c)))


# ── Catalog ─────────────────────────────────────────────────────────────────


class TestImportCatalog:
    """Catalog is the SSOT for which workflows get imported, and where from."""

    def test_notify_router_registered(self) -> None:
        spec = next((s for s in N8N_IMPORT_CATALOG if s.credential_name == "notify-webhook"), None)
        assert spec is not None, "N8N_IMPORT_CATALOG must register the notify-router workflow"
        assert spec.secret_key_path == _SECRET_KEY
        assert spec.workflow_path == Path("infra/n8n/workflows/notify-router.json")

    def test_notify_is_staging_only_for_mvp(self) -> None:
        spec = next(s for s in N8N_IMPORT_CATALOG if s.credential_name == "notify-webhook")
        assert "staging" in spec.envs
        assert "prod" not in spec.envs, "NOTIFY-001 MVP is staging-only (webhook_secret is staging-only)"

    def test_spec_is_frozen(self) -> None:
        spec = N8N_IMPORT_CATALOG[0]
        with pytest.raises((AttributeError, Exception)):
            spec.credential_name = "mutated"  # type: ignore[misc]


# ── Pure render ─────────────────────────────────────────────────────────────


class TestRenderCredential:
    """render_credential is pure: (id, name, secret) → n8n import file content."""

    def test_value_is_bearer_prefixed(self) -> None:
        out = render_credential(_CREDENTIAL_ID, "notify-webhook", "TKN")
        obj = json.loads(out)[0]
        assert obj["data"]["value"] == "Bearer TKN", "Header value must carry the Bearer scheme (RFC 6750)"
        assert obj["data"]["name"] == "Authorization"

    def test_carries_id_type_and_name(self) -> None:
        obj = json.loads(render_credential(_CREDENTIAL_ID, "notify-webhook", "TKN"))[0]
        assert obj["id"] == _CREDENTIAL_ID, "Credential id is SSOT-ed from the workflow JSON"
        assert obj["type"] == "httpHeaderAuth"
        assert obj["name"] == "notify-webhook"

    def test_output_is_a_json_array(self) -> None:
        # `n8n import:credentials --input=FILE` (no --separate) expects the same
        # shape `export:credentials` emits: a JSON array of credential objects.
        data = json.loads(render_credential(_CREDENTIAL_ID, "notify-webhook", "TKN"))
        assert isinstance(data, list) and len(data) == 1

    def test_bare_secret_is_never_the_value(self) -> None:
        obj = json.loads(render_credential(_CREDENTIAL_ID, "notify-webhook", "TKN"))[0]
        assert obj["data"]["value"] != "TKN", "Raw secret (no scheme) violates RFC 7235 — rejected contract"

    def test_idempotent(self) -> None:
        a = render_credential(_CREDENTIAL_ID, "notify-webhook", "TKN")
        b = render_credential(_CREDENTIAL_ID, "notify-webhook", "TKN")
        assert a == b


# ── Reading ids from the workflow JSON (single source of truth) ──────────────


class TestReadWorkflowIds:
    def test_extracts_both_ids(self) -> None:
        workflow_id, credential_id = read_workflow_ids(_workflow_doc())
        assert workflow_id == _WORKFLOW_ID
        assert credential_id == _CREDENTIAL_ID

    def test_raises_when_root_id_missing(self) -> None:
        doc = _workflow_doc()
        del doc["id"]
        with pytest.raises((KeyError, ValueError)):
            read_workflow_ids(doc)

    def test_raises_when_credential_id_missing(self) -> None:
        doc = _workflow_doc()
        doc["nodes"] = [{"name": "x", "type": "y"}]  # no httpHeaderAuth node
        with pytest.raises((KeyError, ValueError)):
            read_workflow_ids(doc)


# ── Orchestrator ─────────────────────────────────────────────────────────────


class TestImportN8nWorkflow:
    """End-to-end: SOPS → render → kubectl exec (credential, workflow, activate)."""

    def _run(self, fake_project: Path, sops, run_mock, env="staging", dry_run=False):
        with (
            patch("toolkit.features.n8n_import.ConfigurationManager", return_value=_cm(sops)),
            patch("toolkit.features.n8n_import.subprocess.run", run_mock),
        ):
            return import_n8n_workflow(env=env, project_root=fake_project, dry_run=dry_run)

    def test_full_sequence_import_publish_restart(self, fake_project: Path) -> None:
        run = _mock_kubectl("cred-ok", "wf-ok", "publish-ok", "restarted", "rolled-out")
        ok = self._run(fake_project, _SOPS_OK, run)
        assert ok is True
        assert run.call_count == 5, "credential import, workflow import, publish, rollout restart, rollout status"
        # Every call targets the n8n deployment in the kubelab namespace.
        for call in run.call_args_list:
            argv = _argv(call)
            assert "kubectl" in argv
            assert "deploy/n8n" in argv
            assert "kubelab" in argv  # -n kubelab
        # The three imports use `kubectl exec`; the restart uses `kubectl rollout`.
        assert sum("exec" in _argv(c) for c in run.call_args_list) == 3
        assert sum("rollout" in _argv(c) for c in run.call_args_list) == 2

    def test_secret_only_in_stdin_never_in_argv(self, fake_project: Path) -> None:
        run = _mock_kubectl("a", "b", "c", "d", "e")
        self._run(fake_project, _SOPS_OK, run)
        for call in run.call_args_list:
            assert "S3CR3T_TOKEN" not in " ".join(_argv(call)), "secret must never reach argv (ps leak)"
        cred_call = _find_call(run, "import:credentials")
        assert "Bearer S3CR3T_TOKEN" in cred_call.kwargs.get("input", ""), "secret travels via stdin only"

    def test_credential_lands_in_dev_shm(self, fake_project: Path) -> None:
        run = _mock_kubectl("a", "b", "c", "d", "e")
        self._run(fake_project, _SOPS_OK, run)
        script = " ".join(_argv(_find_call(run, "import:credentials")))
        assert "/dev/shm" in script, "credential temp file must live on tmpfs (RAM), not persistent disk"

    def test_publish_uses_workflow_id_from_json(self, fake_project: Path) -> None:
        run = _mock_kubectl("a", "b", "c", "d", "e")
        self._run(fake_project, _SOPS_OK, run)
        argv = _argv(_find_call(run, "publish:workflow"))
        assert any(_WORKFLOW_ID in a for a in argv), "publish targets the SSOT workflow id"
        # n8n deprecated `update:workflow --active`; `publish:workflow --id` is current.
        assert not any("update:workflow" in a for a in argv)

    def test_restarts_n8n_so_webhook_registers(self, fake_project: Path) -> None:
        # CLI import writes SQLite; the running process caches the webhook registry,
        # so without a rollout restart the /webhook/notify trigger never registers.
        run = _mock_kubectl("a", "b", "c", "d", "e")
        self._run(fake_project, _SOPS_OK, run)
        argv = _argv(_find_call(run, "restart"))
        assert "rollout" in argv and "restart" in argv
        assert "deploy/n8n" in argv

    def test_missing_secret_returns_false_and_no_exec(self, fake_project: Path) -> None:
        run = _mock_kubectl()
        ok = self._run(fake_project, None, run)
        assert ok is False, "missing SOPS secret is a hard failure (no partial import)"
        assert run.call_count == 0, "kubectl must NOT run when the secret is absent"

    def test_skips_when_env_out_of_scope(self, fake_project: Path) -> None:
        run = _mock_kubectl()
        ok = self._run(fake_project, _SOPS_OK, run, env="prod")
        assert ok is True, "out-of-scope env is a successful no-op"
        assert run.call_count == 0

    def test_dry_run_does_not_touch_cluster(self, fake_project: Path) -> None:
        run = _mock_kubectl()
        ok = self._run(fake_project, _SOPS_OK, run, dry_run=True)
        assert ok is True
        assert run.call_count == 0, "dry-run must not exec into the pod"
