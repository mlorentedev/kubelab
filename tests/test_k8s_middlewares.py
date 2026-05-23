"""Tests for k8s_middlewares — Traefik Middleware CRD rendering + apply."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from toolkit.features.k8s_middlewares import (
    MIDDLEWARE_CATALOG,
    MiddlewareSpec,
    _render_middleware,
    apply_middleware_secrets,
)


def _mock_kubectl(*outputs: str) -> MagicMock:
    """Build a subprocess.run mock that returns each output in order, exit 0.

    Mirrors the pattern in test_argo_manager.py for consistency.
    """
    completed = [MagicMock(stdout=o, stderr="", returncode=0) for o in outputs]
    return MagicMock(side_effect=completed)


# ── Catalog ───────────────────────────────────────────────────────────────────


class TestMiddlewareCatalog:
    """Catalog is the source of truth for which services get a Middleware."""

    def test_ollama_api_key_registered(self) -> None:
        ollama = next((s for s in MIDDLEWARE_CATALOG if s.service == "ollama"), None)
        assert ollama is not None, "MIDDLEWARE_CATALOG must register ollama (AI-001)"
        assert ollama.name == "api-key-ollama"
        assert ollama.secret_key_path == "apps.services.ai.ollama.api_key"

    def test_ollama_is_prod_only_per_adr035_stage1(self) -> None:
        ollama = next(s for s in MIDDLEWARE_CATALOG if s.service == "ollama")
        assert "prod" in ollama.envs
        assert "staging" not in ollama.envs, (
            "Staging is VPN-only per CLAUDE.md; api-key middleware is prod-only "
            "per ADR-035 Stage 1."
        )

    def test_catalog_names_are_unique(self) -> None:
        names = [s.name for s in MIDDLEWARE_CATALOG]
        assert len(names) == len(set(names)), (
            f"Duplicate Middleware names in catalog: {names}"
        )

    def test_spec_is_frozen_dataclass(self) -> None:
        spec = MIDDLEWARE_CATALOG[0]
        with pytest.raises((AttributeError, Exception)):
            spec.name = "mutated"  # type: ignore[misc]


# ── Pure render ───────────────────────────────────────────────────────────────


class TestRenderMiddleware:
    """_render_middleware is pure: takes spec + api_key + template_text, returns YAML."""

    _TEMPLATE = """\
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: ${NAME}
  namespace: ${NAMESPACE}
  labels:
    kubelab.live/service: ${SERVICE}
spec:
  plugin:
    api-key:
      keys:
        - ${API_KEY}
"""

    def _spec(self, **overrides: object) -> MiddlewareSpec:
        defaults: dict[str, object] = {
            "name": "api-key-test",
            "service": "test-svc",
            "secret_key_path": "x.y.z",
            "template_path": Path("/dev/null"),
        }
        defaults.update(overrides)
        return MiddlewareSpec(**defaults)  # type: ignore[arg-type]

    def test_substitutes_all_placeholders(self) -> None:
        out = _render_middleware(self._spec(), api_key="SECRET123", template_text=self._TEMPLATE)

        assert "name: api-key-test" in out
        assert "namespace: kubelab" in out
        assert "kubelab.live/service: test-svc" in out
        assert "- SECRET123" in out
        assert "${" not in out, "All placeholders must be replaced"

    def test_respects_custom_namespace(self) -> None:
        out = _render_middleware(
            self._spec(namespace="kube-system"),
            api_key="K",
            template_text=self._TEMPLATE,
        )
        assert "namespace: kube-system" in out
        assert "namespace: kubelab" not in out

    def test_api_key_with_yaml_special_chars_is_passed_through(self) -> None:
        # The template wraps the key as a list item; we do not quote — caller's
        # responsibility to generate keys without yaml-breaking characters.
        # Base64 / hex / urlsafe random are all safe.
        out = _render_middleware(self._spec(), api_key="a-z_0-9.AZ", template_text=self._TEMPLATE)
        assert "- a-z_0-9.AZ" in out

    def test_idempotent_render(self) -> None:
        a = _render_middleware(self._spec(), api_key="K", template_text=self._TEMPLATE)
        b = _render_middleware(self._spec(), api_key="K", template_text=self._TEMPLATE)
        assert a == b


# ── apply_middleware_secrets — integration with SOPS + kubectl ────────────────


@pytest.fixture
def fake_project(tmp_path: Path) -> Path:
    """A project_root with a fake template file in place."""
    tpl_dir = tmp_path / "infra" / "k8s" / "overlays" / "prod" / "middlewares"
    tpl_dir.mkdir(parents=True)
    (tpl_dir / "api-key.yaml.tpl").write_text(TestRenderMiddleware._TEMPLATE)
    return tmp_path


class TestApplyMiddlewareSecrets:
    """End-to-end: SOPS dict → render → kubectl apply → audit copy."""

    _SOPS_OK = {"apps.services.ai.ollama.api_key": "PROD_KEY_42"}

    def _patch_targets(self, sops_data: dict[str, str] | None):
        """Return contextmanager-stack helper. Patches both the config loader
        and subprocess.run."""

        cm_mock = MagicMock()
        cm_mock.get_secret_by_path.side_effect = lambda path: (
            sops_data.get(path) if sops_data else None
        )

        return cm_mock

    def test_skips_when_env_not_in_spec_envs(self, fake_project: Path) -> None:
        """Calling with env='staging' must skip the ollama Middleware
        (registered envs={'prod'}) and NOT touch kubectl."""
        cm = self._patch_targets(self._SOPS_OK)
        run_mock = _mock_kubectl()  # zero outputs, will assert call_count == 0

        with patch(
            "toolkit.features.k8s_middlewares.ConfigurationManager", return_value=cm
        ), patch("toolkit.features.k8s_middlewares.subprocess.run", run_mock):
            ok = apply_middleware_secrets(env="staging", project_root=fake_project)

        assert ok is True, "Skipping is a successful no-op, not a failure"
        assert run_mock.call_count == 0, "kubectl must NOT be invoked when env is out of scope"

    def test_kubectl_apply_uses_stdin_with_rendered_yaml(self, fake_project: Path) -> None:
        cm = self._patch_targets(self._SOPS_OK)
        run_mock = _mock_kubectl("middleware.traefik.io/api-key-ollama configured")

        with patch(
            "toolkit.features.k8s_middlewares.ConfigurationManager", return_value=cm
        ), patch("toolkit.features.k8s_middlewares.subprocess.run", run_mock):
            ok = apply_middleware_secrets(env="prod", project_root=fake_project)

        assert ok is True
        assert run_mock.call_count == 1
        call = run_mock.call_args_list[0]
        argv = call.args[0]
        assert "kubectl" in argv
        assert "apply" in argv
        assert "-f" in argv and "-" in argv, "Must apply via stdin (-f -)"
        stdin = call.kwargs.get("input", "")
        assert "PROD_KEY_42" in stdin
        assert "api-key-ollama" in stdin

    def test_audit_copy_written_to_generated_dir(self, fake_project: Path) -> None:
        cm = self._patch_targets(self._SOPS_OK)
        run_mock = _mock_kubectl("middleware.traefik.io/api-key-ollama configured")

        with patch(
            "toolkit.features.k8s_middlewares.ConfigurationManager", return_value=cm
        ), patch("toolkit.features.k8s_middlewares.subprocess.run", run_mock):
            apply_middleware_secrets(env="prod", project_root=fake_project)

        audit = fake_project / "infra/k8s/overlays/prod/middlewares/.rendered/api-key-ollama.yaml"
        assert audit.exists(), "Audit copy must be written for forensic review"
        content = audit.read_text()
        assert "PROD_KEY_42" in content
        assert "kind: Middleware" in content

    def test_missing_api_key_in_sops_returns_false(self, fake_project: Path) -> None:
        cm = self._patch_targets(None)  # empty SOPS
        run_mock = _mock_kubectl()

        with patch(
            "toolkit.features.k8s_middlewares.ConfigurationManager", return_value=cm
        ), patch("toolkit.features.k8s_middlewares.subprocess.run", run_mock):
            ok = apply_middleware_secrets(env="prod", project_root=fake_project)

        assert ok is False, "Missing SOPS value is a hard failure (no silent skip)"
        assert run_mock.call_count == 0, "kubectl must NOT be invoked when api_key missing"

    def test_dry_run_does_not_invoke_kubectl_but_writes_audit(
        self, fake_project: Path
    ) -> None:
        cm = self._patch_targets(self._SOPS_OK)
        run_mock = _mock_kubectl()

        with patch(
            "toolkit.features.k8s_middlewares.ConfigurationManager", return_value=cm
        ), patch("toolkit.features.k8s_middlewares.subprocess.run", run_mock):
            ok = apply_middleware_secrets(env="prod", project_root=fake_project, dry_run=True)

        assert ok is True
        assert run_mock.call_count == 0, "dry-run must NOT touch the cluster"
        audit = fake_project / "infra/k8s/overlays/prod/middlewares/.rendered/api-key-ollama.yaml"
        assert audit.exists(), "dry-run still writes audit copy for inspection"

    def test_missing_template_file_returns_false(self, tmp_path: Path) -> None:
        """If the template doesn't exist on disk (PR-C didn't merge yet, or path drift),
        function must fail loudly — not crash with FileNotFoundError, not silently skip."""
        cm = self._patch_targets(self._SOPS_OK)
        run_mock = _mock_kubectl()

        with patch(
            "toolkit.features.k8s_middlewares.ConfigurationManager", return_value=cm
        ), patch("toolkit.features.k8s_middlewares.subprocess.run", run_mock):
            ok = apply_middleware_secrets(env="prod", project_root=tmp_path)

        assert ok is False
        assert run_mock.call_count == 0
