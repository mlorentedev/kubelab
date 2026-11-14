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

# Registered apps an env deliberately does not deploy. Argo CD prunes prod and staging, so an app
# that LOSES its pin is deleted from the cluster by the next sync, and the drift gate accepts it
# (the regenerated overlay and the committed one agree). Naming the absence here is what turns
# that deletion into a failing test: a pin removed by mistake is not on this list, and an app
# registered ahead of its first build is added here and removed again in the PR that pins it.
DECLARED_UNPINNED: dict[str, set[str]] = {"staging": set(), "prod": {"imagesensortool"}}

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
    path.write_text(_REGISTRY, encoding="utf-8", newline="\n")
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


def _pin(app: str, env: str) -> str | None:
    """`apps.platform.<app>.version` as the env resolves it: the env's values over common's."""
    for name in (env, "common"):
        values = yaml.safe_load((REPO / f"infra/config/values/{name}.yaml").read_text(encoding="utf-8"))
        version = ((values.get("apps") or {}).get("platform") or {}).get(app, {}).get("version")
        if version:
            return str(version)
    return None


@pytest.mark.parametrize("env", _ENVS)
def test_the_committed_overlay_runs_each_pinned_app_on_its_pin_and_no_other(env: str) -> None:
    """The real config: an app with a pin in this env runs on exactly it, one without is absent.

    Registered is not deployed: an app can be pinned in staging alone (imagesensortool was), and
    its prod overlay must then not carry it. An app that loses its pin, or an overlay that keeps
    a Deployment for one, is named here instead of the overlay silently changing.
    """
    path = REPO / f"infra/k8s/overlays/{env}/generated/deployments.yaml"
    docs = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
    images = {
        d["metadata"]["name"]: [c["image"] for c in d["spec"]["template"]["spec"]["containers"]]
        for d in docs
        if d and d.get("kind") == "Deployment"
    }
    pinned = {app: _pin(app, env) for app in product_registry.platform_apps() if _pin(app, env)}
    assert pinned, "no registered app has a pin: the check below would pass on nothing"
    assert set(pinned) <= set(images), f"{env}: pinned apps with no Deployment: {set(pinned) - set(images)}"
    registered_unpinned = set(product_registry.platform_apps()) - set(pinned)
    assert registered_unpinned == DECLARED_UNPINNED[env], (
        f"{env}: apps with no apps.platform.<app>.version are {sorted(registered_unpinned)}, declared "
        f"{sorted(DECLARED_UNPINNED[env])}. A lost pin deletes the app (Argo CD prunes); a new app "
        "registered before its first build is declared in DECLARED_UNPINNED"
    )
    assert not registered_unpinned & set(images), (
        f"{env}: an unpinned app has a Deployment: {registered_unpinned & set(images)}"
    )
    for app, version in pinned.items():
        assert all(image.endswith(f":{version}") for image in images[app]), (
            f"{env}: {app} runs {images[app]}, not {version}"
        )
        assert version not in ("latest", "dev")
