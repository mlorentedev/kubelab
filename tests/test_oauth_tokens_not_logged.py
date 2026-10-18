"""SEC-021 (#1840): no OAuth credential reaches Loki.

Grafana 13.0.2 tries to parse every access token as a JWT, whatever its config
(`collectUserInfoData`, generic_oauth.go:263), and when that fails it logs the
token inside the error (`token is not in JWT format: %s`, social_base.go:242).
Authelia's tokens are opaque by default, so every SSO login wrote a live bearer
token to Loki at `warn`: measured on 2026-09-26, 3 in prod (two of them Admin) and
19 in staging. Vikunja and Authelia also log authorization codes, which are
single-use but are still credentials in transit.

Two layers, each tested here:

- The `grafana` client issues RFC 9068 JWT access tokens, so Grafana parses the
  token instead of logging it. Grafana keeps the first value it finds per field
  (ID token, then UserInfo, then access token), so the role still comes from
  UserInfo's `groups`.
- Vector redacts every `authelia_(at|rt|ac)_` value before Loki, whichever app
  logs it next.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from jinja2 import meta

from toolkit.core.templating import TemplateRenderer
from toolkit.features import oidc_clients
from toolkit.features.configuration import ConfigurationManager

REPO = Path(__file__).resolve().parent.parent
COMMON = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())
VECTOR_DIR = REPO / "infra/k8s/base/services/vector-config"
VECTOR_TESTS = Path(__file__).resolve().parent / "fixtures" / "vector-redaction-tests.yaml"
_ALG = "access_token_signed_response_alg"


def _declared(client_id: str) -> dict[str, Any]:
    clients = COMMON["apps"]["services"]["security"]["authelia"]["oidc_clients"]
    return next(c for c in clients if c["client_id"] == client_id)


# --------------------------------------------------------------------------- Authelia


def test_grafana_is_issued_jwt_access_tokens() -> None:
    """An opaque token is what Grafana logs; a signed one it parses."""
    assert _declared("grafana").get(_ALG, "none") != "none"


def test_the_resolver_passes_a_declared_access_token_alg_through() -> None:
    values = {"apps": {"services": {"security": {"authelia": {"oidc_clients": [dict(_declared("grafana"))]}}}}}
    values["apps"]["services"]["observability"] = {"grafana": {"domain": "grafana.example.test"}}
    (resolved,) = oidc_clients.resolve_clients(values, "staging")
    assert resolved[_ALG] == _declared("grafana")[_ALG]


def test_a_client_that_declares_no_alg_renders_none() -> None:
    """Absent means Authelia's default (opaque), so the key is not emitted at all."""
    client = {k: v for k, v in _declared("grafana").items() if k != _ALG}
    values = {"apps": {"services": {"security": {"authelia": {"oidc_clients": [client]}}}}}
    values["apps"]["services"]["observability"] = {"grafana": {"domain": "grafana.example.test"}}
    (resolved,) = oidc_clients.resolve_clients(values, "staging")
    assert _ALG not in resolved


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_each_rendered_clients_file_carries_it(env: str) -> None:
    rendered = yaml.safe_load(oidc_clients.clients_file(env).read_text())
    clients = rendered["identity_providers"]["oidc"]["clients"]
    grafana = next(c for c in clients if c["client_id"] == "grafana")
    assert grafana.get(_ALG) == _declared("grafana")[_ALG]


@pytest.mark.parametrize("env_name", ["staging", "prod"])
def test_the_authelia_template_renders_clients_without_an_alg(monkeypatch: pytest.MonkeyPatch, env_name: str) -> None:
    """The Authelia Jinja template (the Compose path, rendered by `toolkit config generate`
    for every env) renders the clients from the same resolver.

    Rendered with the generator's own renderer (StrictUndefined) over the clients the
    resolver returns, because the resolver omits the key for a client that declares
    none. A truth test on that missing key raised, and `toolkit config generate`
    failed for staging and prod while a text search of the template stayed green
    (#2469). Dev declares only grafana, so it never took that path.
    """
    manager = ConfigurationManager(env_name, REPO)
    monkeypatch.setattr(manager, "_decrypt_sops", lambda _path: {})
    clients = [
        {**client, "client_secret_hash": "unset-digest"}
        for client in oidc_clients.resolve_clients(manager.get_merged_config(), env_name)
    ]
    without = [c["client_id"] for c in clients if _ALG not in c]
    assert without, "every client declares the alg; the missing-key path would go untested"

    env = TemplateRenderer(REPO / "infra/config/authelia/templates").env
    template_name = "configuration.yml.j2"
    source = env.loader.get_source(env, template_name)[0]  # type: ignore[union-attr]
    lists = {"apps": [], "authelia_users": [], "trusted_cidrs": [], "oidc_clients": clients}
    context = {name: "unset" for name in meta.find_undeclared_variables(env.parse(source))} | lists
    text = env.get_template(template_name).render(context)
    # The JWKS key is left as Authelia's own template expression, which Authelia
    # expands at load time; until then the line is not YAML.
    rendered = yaml.safe_load(re.sub(r"\{\{ secret [^}]*\}\}", "authelia-secret", text))

    emitted = {c["client_id"]: c for c in rendered["identity_providers"]["oidc"]["clients"]}
    assert emitted["grafana"][_ALG] == _declared("grafana")[_ALG]
    assert all(_ALG not in emitted[client_id] for client_id in without)


# --------------------------------------------------------------------------- Vector


def _rendered(overlay: str) -> list[dict[str, Any]]:
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not on PATH: cannot render the overlay (a skip is CANNOT CHECK, not OK)")
    out = subprocess.run(
        ["kubectl", "kustomize", str(REPO / "infra/k8s/overlays" / overlay)], capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    return [d for d in yaml.safe_load_all(out.stdout) if d]


@pytest.mark.parametrize("overlay", ["staging", "prod"])
def test_vector_rolls_when_its_config_changes(overlay: str) -> None:
    """Vector runs without --watch-config, so a plain ConfigMap would change and Argo CD
    would report Synced while Vector kept the old pipeline (lesson-404). The name has
    to change with the content, and the DaemonSet has to follow it."""
    docs = _rendered(overlay)
    config = next(d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"].startswith("vector-config"))
    assert config["metadata"]["name"] != "vector-config", "no hash suffix: a config change would never reach Vector"
    daemonset = next(d for d in docs if d["kind"] == "DaemonSet" and d["metadata"]["name"] == "vector")
    mounted = {v["configMap"]["name"] for v in daemonset["spec"]["template"]["spec"]["volumes"] if "configMap" in v}
    assert config["metadata"]["name"] in mounted


def test_dev_vector_loads_the_mounted_config() -> None:
    """The image's default config is a bundled demo, not the file Compose mounts, so a
    redaction written there is dead unless the service points Vector at it."""
    compose = yaml.safe_load((REPO / "infra/stacks/services/observability/loki/compose.base.yml").read_text())
    vector = compose["services"]["vector"]
    mounted = {v.split(":")[1] for v in vector["volumes"] if v.split(":")[0].endswith("config/loki/vector.toml")}
    assert mounted, "the dev Vector config is not mounted"
    command = vector.get("command") or []
    assert "--config" in command and command[command.index("--config") + 1] in mounted


def _vector_image() -> str:
    kustomization = yaml.safe_load((REPO / "infra/k8s/base/kustomization.yaml").read_text())
    pin = next(i for i in kustomization["images"] if i["name"] == "timberio/vector")
    return f"{pin.get('newName', pin['name'])}:{pin['newTag']}"


#: Each shipped Vector config and the transform that must redact in it. Dev Compose
#: ships Docker's logs to its own Loki through the same rule.
VECTOR_CONFIGS = {
    "k8s": (VECTOR_DIR / "vector.yaml", "parse_logs"),
    "dev": (REPO / "infra/config/loki/vector.toml", "redact_tokens"),
}


@pytest.mark.integration
@pytest.mark.parametrize("target", sorted(VECTOR_CONFIGS))
def test_vector_redacts_every_token_kind_and_nothing_else(target: str, docker_mount_dir: Path) -> None:
    """Runs Vector's own unit-test runner on each shipped config, with the pinned image."""
    if shutil.which("docker") is None:
        # The only proof the redaction works: in CI a missing docker is a failure,
        # or a runner-image change would turn this security test into a quiet skip.
        if os.environ.get("CI"):
            pytest.fail("docker not on PATH in CI: the Vector redaction went untested")
        pytest.skip("docker not on PATH: cannot run Vector (a skip is CANNOT CHECK, not OK)")
    config, transform = VECTOR_CONFIGS[target]
    tests = docker_mount_dir / "tests.yaml"
    tests.write_text(VECTOR_TESTS.read_text().replace("parse_logs", transform))
    out = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            # The DaemonSet sets it from the downward API; Vector refuses a config
            # that references an unset variable, which is also why a stray dollar
            # in the file is a startup failure and not a typo.
            "-e",
            "VECTOR_SELF_NODE_NAME=unit-test",
            "-v",
            f"{config}:/etc/vector/{config.name}:ro",
            "-v",
            f"{tests}:/etc/vector/tests.yaml:ro",
            _vector_image(),
            "test",
            f"/etc/vector/{config.name}",
            "/etc/vector/tests.yaml",
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert out.returncode == 0, out.stdout + out.stderr
