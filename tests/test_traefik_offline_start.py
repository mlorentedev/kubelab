"""Traefik must start, and renew, without anything the site's network decides (#2565, #2699).

Plugins: Traefik downloads a remote plugin from plugins.traefik.io at every start.
When the download fails it starts anyway with EVERY plugin disabled and drops each
router that uses one, while the pod stays Ready. On 2026-10-27 ace1 booted without
egress, K3s started the moment the edge served a default route, and Traefik tried the
download 17 s later: every CrowdSec-protected staging route answered 404 until a
manual restart. So the role fetches each plugin's source at provision time, pinned by
sha256, and Traefik loads it from the node. A start downloads nothing.

ACME: lego checks the DNS-01 record against the zone's authoritative nameservers over
UDP 53 before asking Let's Encrypt to validate. The lab's current site answers every
outbound UDP 53 query itself (192.0.2.1, which does not exist, answers NOERROR), so
the check only ever sees a cached NXDOMAIN. Let's Encrypt validates from its own
network either way, so the local check is replaced by a fixed delay.

What is asserted is the RENDERED HelmChartConfig, for the reason
`test_traefik_ports_stay_behind_the_firewall.py` gives: the template is Jinja, and
only the rendered output says what Traefik receives.
"""

from __future__ import annotations

import pathlib
import re
from typing import Any

import pytest
import yaml
from jinja2 import StrictUndefined

from tests.ansible_jinja import ansible_env

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLE = REPO_ROOT / "infra/ansible/roles/k3s_server"
TASKS = ROLE / "tasks/main.yml"
K8S = REPO_ROOT / "infra/k8s"

# Where Traefik looks for a local plugin's source, relative to its working directory.
LOCAL_PLUGIN_ROOT = "/plugins-local/src/"


def _defaults() -> dict[str, Any]:
    return yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8")) or {}


def _render(**overrides: Any) -> dict[str, Any]:
    env = ansible_env(str(ROLE / "templates"), undefined=StrictUndefined, keep_trailing_newline=True)
    variables = _defaults() | {"ansible_managed": "Ansible managed", "k3s_traefik_acme_enabled": True}
    rendered = env.get_template("traefik-helmconfig.yaml.j2").render(**(variables | overrides))
    return yaml.safe_load(yaml.safe_load(rendered)["spec"]["valuesContent"])


def _plugins() -> list[dict[str, str]]:
    return _defaults()["k3s_traefik_local_plugins"]


def _tasks() -> list[dict[str, Any]]:
    return yaml.safe_load(TASKS.read_text(encoding="utf-8"))


def _plugins_used_by_middlewares() -> set[str]:
    """Every plugin name a Middleware in the manifests asks Traefik for.

    `.yaml.tpl` too: ADR-035's API-key Middlewares are rendered from those by the
    toolkit, outside Kustomize. None exists today, so `api-key` has no consumer in
    the repo, and the first one is held to this the day it is added.
    """
    used: set[str] = set()
    for path in [*K8S.rglob("*.yaml"), *K8S.rglob("*.yaml.tpl")]:
        for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
            if isinstance(doc, dict) and doc.get("kind") == "Middleware":
                used |= set((doc.get("spec") or {}).get("plugin") or {})
    return used


# --- What Traefik receives ---------------------------------------------------------


def test_no_plugin_is_downloaded_at_start() -> None:
    assert "plugins" not in _render()["experimental"]


def test_every_declared_plugin_loads_from_the_node() -> None:
    local = _render()["experimental"]["localPlugins"]
    plugin_dir = _defaults()["k3s_traefik_local_plugins_dir"]

    assert set(local) == {p["name"] for p in _plugins()}
    for plugin in _plugins():
        entry = local[plugin["name"]]
        assert entry["type"] == "hostPath"
        assert entry["moduleName"] == plugin["module"]
        assert entry["mountPath"] == LOCAL_PLUGIN_ROOT + plugin["module"]
        # One directory per version: a bump changes the hostPath, so the
        # HelmChartConfig changes and Traefik rolls onto the new source.
        assert entry["hostPath"] == f"{plugin_dir}/{plugin['name']}/{plugin['version']}"


def test_a_plugin_that_does_not_load_stops_traefik() -> None:
    assert _render()["experimental"]["abortOnPluginFailure"] is True


def test_every_plugin_a_middleware_uses_is_loaded() -> None:
    used = _plugins_used_by_middlewares()
    assert used, "no Middleware uses a plugin: the scan is reading the wrong tree"
    assert used <= {p["name"] for p in _plugins()}


# --- The pins ----------------------------------------------------------------------


@pytest.mark.parametrize("plugin", _plugins(), ids=lambda p: p["name"])
def test_each_plugin_is_pinned(plugin: dict[str, str]) -> None:
    # The source URL is derived from the module, so it must be a GitHub module.
    assert plugin["module"].startswith("github.com/")
    assert re.fullmatch(r"v\d+\.\d+\.\d+", plugin["version"])
    assert re.fullmatch(r"[0-9a-f]{64}", plugin["sha256"])


# --- The role ----------------------------------------------------------------------


def _task(name_part: str) -> tuple[int, dict[str, Any]]:
    for index, task in enumerate(_tasks()):
        if name_part in task.get("name", ""):
            return index, task
    raise AssertionError(f"no task named like {name_part!r}")


def test_the_source_is_verified_before_it_is_used() -> None:
    _, fetch = _task("Download each Traefik plugin")
    assert fetch["get_url"]["checksum"] == "sha256:{{ item.sha256 }}"


def test_the_source_is_on_the_node_before_traefik_is_configured() -> None:
    unpack, _ = _task("Unpack each Traefik plugin")
    config, _ = _task("Template Traefik HelmChartConfig")
    assert unpack < config


def test_versions_no_longer_declared_are_pruned() -> None:
    _, prune = _task("Remove Traefik plugin versions no longer declared")
    assert prune["file"]["state"] == "absent"


# --- ACME --------------------------------------------------------------------------


def _acme_args(**overrides: Any) -> list[str]:
    return [a for a in _render(**overrides)["additionalArguments"] if "acme" in a]


def test_the_dns01_check_does_not_query_nameservers_from_the_site() -> None:
    args = _acme_args()
    assert "--certificatesresolvers.letsencrypt.acme.dnschallenge.propagation.disableChecks=true" in args
    assert "--certificatesresolvers.letsencrypt.acme.dnschallenge.propagation.delayBeforeChecks=60s" in args


def test_the_dns01_check_can_be_restored() -> None:
    assert not [a for a in _acme_args(k3s_traefik_acme_propagation_checks=True) if "propagation" in a]
