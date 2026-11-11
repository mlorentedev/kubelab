"""IDP-053 AC2: the generated image comes from the registry entry's registry (D4).

The product registry owns the host a product's image lives in; the values carry only
the name and the tag. A product with no ``image_registry`` keeps the platform's
``REGISTRY``, so the committed overlays for ``web`` stay byte-identical (the
``validate-sync`` runs in the slice's acceptance prove that on the real files).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from toolkit.features import generator_k8s, product_registry
from toolkit.features.generator_k8s import K8sGenerator

_REGISTRY = """\
products:
  web:
    repository: mlorentedev/web
    forge: github
    receiver: generic
    image_name: kubelab-web
    events: {staging: web-image-published, prod: web-release-published}
  beta:
    repository: personal/beta
    forge: gitea
    receiver: generic
    image_registry: gitea.kubelab.live/personal
    private: true
    pull_credential: {username: reviewer, secret: gitea.registry_pull}
    events: {staging: beta-image-published}
"""


def _env(app: str, name: str, version: str) -> dict[str, str]:
    prefix = f"APPS_PLATFORM_{app.upper()}"
    return {
        f"{prefix}_IMAGE_NAME": name,
        f"{prefix}_DOMAIN": f"{app}.staging.example.test",
        f"{prefix}_DEFAULT_PORT": "8080",
        f"{prefix}_VERSION": version,
    }


@pytest.fixture
def images(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    """The ``image`` of each app ``_build_context`` emits for a registry with a forge-hosted product."""
    path = tmp_path / "products.yaml"
    path.write_text(_REGISTRY, encoding="utf-8")
    monkeypatch.setattr(product_registry, "registry_path", lambda: path)
    env_vars = {
        "REGISTRY": "docker.io/mlorentedev",
        **_env("web", "kubelab-web", "sha-1111111"),
        **_env("beta", "beta", "sha-0123456789ab"),
    }
    manager = MagicMock()
    manager.return_value.get_env_vars.return_value = env_vars
    monkeypatch.setattr(generator_k8s, "ConfigurationManager", manager)
    monkeypatch.setattr(K8sGenerator, "_build_migrations", lambda self, env_vars: {})
    context = K8sGenerator()._build_context("staging")
    return {app["name"]: app["image"] for app in context["apps"]}


def test_a_product_with_an_image_registry_is_deployed_from_it(images: dict[str, str]) -> None:
    assert images["beta"] == "gitea.kubelab.live/personal/beta:sha-0123456789ab"


def test_a_product_without_one_keeps_the_platform_registry(images: dict[str, str]) -> None:
    assert images["web"] == "docker.io/mlorentedev/kubelab-web:sha-1111111"


def test_the_generated_image_is_the_derived_image_plus_the_tag(images: dict[str, str], tmp_path: Path) -> None:
    path = tmp_path / "products.yaml"
    for app in ("web", "beta"):
        assert images[app].rsplit(":", 1)[0] == product_registry.derived_image(app, path)
