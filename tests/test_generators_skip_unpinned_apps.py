"""#3456: no generator emits anything for a platform app that has no `version` in the env.

The K8s generator no longer deploys it, and the other two must agree: a Traefik router or an
Authelia access rule for an app with no Deployment is a route to a Service that does not exist.
One registered app is pinned, one is not, and each generator is asked what it would emit.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from toolkit.features import generator_authelia, generator_k8s, generator_traefik, product_registry
from toolkit.features.generator_authelia import AutheliaGenerator
from toolkit.features.generator_k8s import K8sGenerator
from toolkit.features.generator_traefik import TraefikGenerator

_REGISTRY = """\
products:
  pinned:
    forge: in-tree
  fresh:
    forge: in-tree
"""


def _env_vars() -> dict[str, str]:
    """`pinned` has a version; `fresh` has everything a route needs except one."""
    env: dict[str, str] = {"REGISTRY": "docker.io/mlorentedev"}
    for app in ("pinned", "fresh"):
        upper = app.upper()
        env |= {
            f"APPS_PLATFORM_{upper}_IMAGE_NAME": f"kubelab-{app}",
            f"APPS_PLATFORM_{upper}_DOMAIN": f"{app}.example.test",
            f"APPS_PLATFORM_{upper}_DEFAULT_PORT": "8080",
            # Authelia reads the short key, Traefik and K8s the platform one.
            f"APPS_{upper}_HOST": f"{app}.example.test",
            f"APPS_{upper}_DEFAULT_PORT": "8080",
        }
    env["APPS_PLATFORM_PINNED_VERSION"] = "sha-1111111"
    return env


@pytest.fixture(autouse=True)
def _registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "products.yaml"
    path.write_text(_REGISTRY, encoding="utf-8", newline="\n")
    monkeypatch.setattr(product_registry, "registry_path", lambda: path)


def _manager(monkeypatch: pytest.MonkeyPatch, module: Any) -> None:
    manager = MagicMock()
    manager.return_value.get_env_vars.return_value = _env_vars()
    manager.return_value.get_merged_config.return_value = {}
    monkeypatch.setattr(module, "ConfigurationManager", manager)


def _k8s(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    _manager(monkeypatch, generator_k8s)
    monkeypatch.setattr(K8sGenerator, "_build_migrations", lambda self, env_vars: {})
    return [a["name"] for a in K8sGenerator()._build_context("prod")["apps"]]


def _traefik(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    _manager(monkeypatch, generator_traefik)
    return [a["name"] for a in TraefikGenerator()._build_context("prod")["apps"]]


def _authelia(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    _manager(monkeypatch, generator_authelia)
    monkeypatch.setattr(generator_authelia, "oidc_clients_for_template", lambda config, env: [])
    seen: dict[str, Any] = {}
    renderer = MagicMock()
    renderer.render_template.side_effect = lambda template, output, context: seen.setdefault("apps", context["apps"])
    monkeypatch.setattr(generator_authelia, "create_renderer", lambda templates_dir: renderer)
    generator = AutheliaGenerator()
    generator.project_root = tmp_path
    (tmp_path / "infra/config/authelia/templates").mkdir(parents=True)
    assert generator.generate("prod")["success"]
    return [a["name"] for a in seen["apps"]]


@pytest.fixture
def emitted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, list[str]]:
    return {
        "k8s": _k8s(monkeypatch),
        "traefik": _traefik(monkeypatch),
        "authelia": _authelia(monkeypatch, tmp_path),
    }


@pytest.mark.parametrize("generator", ["k8s", "traefik", "authelia"])
def test_no_generator_emits_an_app_with_no_version(emitted: dict[str, list[str]], generator: str) -> None:
    assert "fresh" not in emitted[generator], f"{generator} still emits an unpinned app: {emitted[generator]}"


@pytest.mark.parametrize("generator", ["k8s", "traefik", "authelia"])
def test_every_generator_still_emits_the_pinned_app(emitted: dict[str, list[str]], generator: str) -> None:
    """Without this the three tests above would pass on a generator that emits nothing at all."""
    assert "pinned" in emitted[generator], f"{generator} emits {emitted[generator]}"
