"""#3456: an app with no `version` in an env is not deployed there, and is never put on `:latest`.

`_build_context` used to read `version ... or "latest"`. A platform app registered in
products.yaml before it had a release got a Deployment on `kubelab-<app>:latest` with
`imagePullPolicy: Always` in EVERY overlay, prod included, where Argo CD's selfHeal
deploys it the moment the registering PR merges. `generate()` succeeded and the drift gate
accepted it, since it only compares the regenerated files with the committed ones.

"No pin" now means "not deployed in that env": no Deployment, Service, route or ConfigMap.
That is the per-env gate a first rollout needs, with no flag of its own.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from toolkit.features import generator_base, generator_k8s, product_registry
from toolkit.features.generator_k8s import K8sGenerator

REPO = Path(__file__).resolve().parent.parent
_ENVS = ("staging", "prod")

_REGISTRY = """\
products:
  api:
    forge: in-tree
  fresh:
    forge: in-tree
"""


def _env(app: str, **overrides: str | None) -> dict[str, str]:
    prefix = f"APPS_PLATFORM_{app.upper()}"
    fields = {"IMAGE_NAME": f"kubelab-{app}", "DOMAIN": f"{app}.example.test", "DEFAULT_PORT": "8080", **overrides}
    return {f"{prefix}_{key}": value for key, value in fields.items() if value is not None}


@pytest.fixture
def context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """`_build_context` for two registered apps, `api` pinned and `fresh` not, per call."""
    path = tmp_path / "products.yaml"
    path.write_text(_REGISTRY, encoding="utf-8")
    monkeypatch.setattr(product_registry, "registry_path", lambda: path)

    def build(fresh_version: str | None) -> dict:
        env_vars = {
            "REGISTRY": "docker.io/mlorentedev",
            **_env("api", VERSION="sha-1111111"),
            **_env("fresh", VERSION=fresh_version),
        }
        manager = MagicMock()
        manager.return_value.get_env_vars.return_value = env_vars
        monkeypatch.setattr(generator_k8s, "ConfigurationManager", manager)
        monkeypatch.setattr(K8sGenerator, "_build_migrations", lambda self, env_vars: {})
        return K8sGenerator()._build_context("staging")

    return build


def test_an_app_with_no_version_is_not_emitted(context) -> None:
    assert [a["name"] for a in context(None)["apps"]] == ["api"]


def test_an_app_with_an_empty_version_is_not_emitted(context) -> None:
    assert [a["name"] for a in context("")["apps"]] == ["api"]


def test_an_app_with_a_version_is_emitted_on_exactly_that_tag(context) -> None:
    apps = {a["name"]: a["image"] for a in context("sha-2222222")["apps"]}
    assert apps["fresh"] == "docker.io/mlorentedev/kubelab-fresh:sha-2222222"


def test_the_skip_is_logged_as_a_warning_naming_the_app(context, monkeypatch: pytest.MonkeyPatch) -> None:
    log = MagicMock()
    monkeypatch.setattr(generator_base, "logger", log)
    context(None)
    warned = [str(call.args[0]) for call in log.warning.call_args_list]
    assert any("fresh" in m and "version" in m for m in warned), warned


def test_a_pinned_app_logs_no_warning(context, monkeypatch: pytest.MonkeyPatch) -> None:
    log = MagicMock()
    monkeypatch.setattr(generator_base, "logger", log)
    context("sha-2222222")
    assert not log.warning.call_args_list


@pytest.mark.parametrize("env", _ENVS)
def test_the_committed_overlay_runs_every_registered_app_on_its_pin(env: str) -> None:
    """The real config: no app lost its Deployment to the new rule, and none is on a mutable tag.

    api and web carry a pin in both envs today. If one ever loses it, this names the app
    instead of the overlay silently shrinking.
    """
    docs = list(yaml.safe_load_all((REPO / f"infra/k8s/overlays/{env}/generated/deployments.yaml").read_text(encoding="utf-8")))
    deployed = {d["metadata"]["name"]: d for d in docs if d and d.get("kind") == "Deployment"}
    assert set(deployed) >= set(product_registry.platform_apps())
    for name, doc in deployed.items():
        for container in doc["spec"]["template"]["spec"]["containers"]:
            tag = container["image"].rsplit(":", 1)[-1]
            assert tag not in ("latest", "dev"), f"{env}: {name} runs {container['image']}"
