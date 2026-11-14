"""CONSOLE-004 AC6: Grafana reads forge statistics through a read-only role, and its password
never rests in a ConfigMap.

Judged on the rendered overlays (`kubectl kustomize`), because what the cluster gets is the
render: the datasource definition is a generated, hashed ConfigMap (a ConfigMap nothing
re-reads must change its name, lesson-404), and the credential reaches the process as an
environment variable from a Secret that `apply-secrets` restarts Grafana for (#1804).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.features.k8s_secrets import SECRET_DEFINITIONS
from toolkit.features.postgres_provisioner import READER_ROLES
from toolkit.features.secret_consumers import secret_refs
from toolkit.features.secrets_manager import SECRET_CATALOG

REPO = Path(__file__).resolve().parent.parent
ROLE = "forge_stats"
KEY_PATH = "apps.platform.api.forge_stats_db_password"
ENV_VAR = "FORGE_STATS_DB_PASSWORD"
DASHBOARD = REPO / "infra/k8s/base/services/grafana-dashboards/forge-stats.json"
GRAFANA_ADMIN = next(m for m in SECRET_DEFINITIONS if m.name == "grafana-admin")

_RENDERS: dict[str, list[dict[str, Any]]] = {}


def _render(overlay: str) -> list[dict[str, Any]]:
    if overlay not in _RENDERS:
        if shutil.which("kubectl") is None:
            pytest.skip("kubectl not on PATH: cannot render the overlay (a skip is CANNOT CHECK, not OK)")
        out = subprocess.run(
            ["kubectl", "kustomize", str(REPO / "infra/k8s/overlays" / overlay)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        _RENDERS[overlay] = [d for d in yaml.safe_load_all(out.stdout) if d]
    return _RENDERS[overlay]


def _named(overlay: str, kind: str, prefix: str) -> list[dict[str, Any]]:
    return [
        d
        for d in _render(overlay)
        if d["kind"] == kind and re.fullmatch(rf"{re.escape(prefix)}(-[a-z0-9]{{8,10}})?", d["metadata"]["name"])
    ]


def _datasource(overlay: str) -> dict[str, Any]:
    (cm,) = _named(overlay, "ConfigMap", "grafana-datasources")
    provisioned = yaml.safe_load(cm["data"]["datasources.yaml"])
    return next(d for d in provisioned["datasources"] if d["uid"] == "forge-stats")


def _grafana(overlay: str) -> dict[str, Any]:
    return next(d for d in _render(overlay) if d["kind"] == "Deployment" and d["metadata"]["name"] == "grafana")


def test_the_role_password_is_catalogued_for_each_env_that_runs_grafana() -> None:
    spec = next((s for s in SECRET_CATALOG if s.key_path == KEY_PATH), None)
    assert spec is not None, f"{KEY_PATH} must be in SECRET_CATALOG"
    # `envs` is the audit dimension: a pseudo-env such as `common` matches no real env.
    assert set(spec.envs) == {"staging", "prod"}
    assert READER_ROLES[ROLE].password_path == KEY_PATH


def test_the_generator_would_keep_the_password_out_of_a_configmap_if_the_vault_merged_it_in() -> None:
    # The K8s generator merges SOPS into the values it renders ConfigMaps from, and drops a key
    # by an exact word of its name. The key is not in the vault until the operator writes it,
    # so this is the guard that holds the day it is.
    from toolkit.config.constants import VALIDATION_RULES

    assert set(KEY_PATH.upper().replace(".", "_").split("_")) & set(VALIDATION_RULES.SECRET_PATTERNS)


def test_the_password_reaches_grafana_through_its_secret_and_not_a_configmap() -> None:
    assert GRAFANA_ADMIN.optional_keys["forge-stats-db-password"] == KEY_PATH.upper().replace(".", "_")
    assert "forge-stats-db-password" not in GRAFANA_ADMIN.keys


@pytest.mark.parametrize("overlay", ["staging", "prod"])
def test_the_datasource_is_the_read_only_role_with_the_password_taken_from_the_environment(overlay: str) -> None:
    ds = _datasource(overlay)
    assert ds["user"] == ROLE
    assert ds["jsonData"]["database"] == READER_ROLES[ROLE].database
    assert ds["url"] == "postgres:5432"
    # An expansion Grafana performs from its own environment: the file holds a name.
    assert ds["secureJsonData"] == {"password": f"${ENV_VAR}"}
    assert ds["editable"] is False


@pytest.mark.parametrize("overlay", ["staging", "prod"])
def test_grafana_takes_the_password_from_a_secret_key_that_apply_secrets_writes(overlay: str) -> None:
    container = _grafana(overlay)["spec"]["template"]["spec"]["containers"][0]
    env = next(e for e in container["env"] if e["name"] == ENV_VAR)
    ref = env["valueFrom"]["secretKeyRef"]
    assert ref["key"] == "forge-stats-db-password"
    assert ref["key"] in {*GRAFANA_ADMIN.keys, *GRAFANA_ADMIN.optional_keys}
    # `optional`: the key arrives with the vault entry, and a pod waiting for it is Grafana down.
    assert ref["optional"] is True
    # The restart `apply-secrets` runs after a changed Secret finds Grafana by this reference.
    assert ref["name"] in secret_refs(_grafana(overlay)["spec"]["template"]["spec"])


@pytest.mark.parametrize("overlay", ["staging", "prod"])
def test_no_configmap_of_the_render_holds_the_password_or_its_value_name(overlay: str) -> None:
    for doc in _render(overlay):
        if doc["kind"] != "ConfigMap":
            continue
        blob = json.dumps(doc.get("data", {}))
        # The datasource names the variable it expands, which is all it may hold of the
        # secret. No ConfigMap carries the secret's own key, which is how a value would
        # arrive through the generator's SOPS merge.
        assert "APPS_PLATFORM_API_FORGE_STATS_DB_PASSWORD" not in blob, doc["metadata"]["name"]
        assert "forge-stats-db-password" not in blob, doc["metadata"]["name"]
        if not doc["metadata"]["name"].startswith("grafana-datasources"):
            assert ENV_VAR not in blob, doc["metadata"]["name"]


@pytest.mark.parametrize("overlay", ["staging", "prod"])
def test_the_datasource_configmap_is_hashed_and_the_pod_mounts_that_name(overlay: str) -> None:
    (cm,) = _named(overlay, "ConfigMap", "grafana-datasources")
    name = cm["metadata"]["name"]
    # Grafana reads datasource provisioning once, at start: an unhashed name would change the
    # ConfigMap, leave the pod as it was and let Argo CD report Synced.
    assert re.fullmatch(r"grafana-datasources-[a-z0-9]{8,10}", name), name
    volumes = _grafana(overlay)["spec"]["template"]["spec"]["volumes"]
    assert next(v for v in volumes if v["name"] == "datasources")["configMap"]["name"] == name


def test_the_loki_datasource_survives_the_move_to_a_generated_configmap() -> None:
    provisioned = yaml.safe_load(_named("staging", "ConfigMap", "grafana-datasources")[0]["data"]["datasources.yaml"])
    loki = next(d for d in provisioned["datasources"] if d["uid"] == "loki")
    assert loki["url"] == "http://loki:3100"
    assert loki["isDefault"] is True


def test_the_dashboard_queries_the_stats_view_through_the_datasource_and_nothing_else() -> None:
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    assert dashboard["uid"] == "forge-stats"
    panels = [p for p in dashboard["panels"] if p["type"] != "row"]
    assert panels, "the dashboard has no panels"
    for panel in panels:
        assert panel["datasource"]["uid"] == "forge-stats", panel["title"]
        for target in panel["targets"]:
            sql = target["rawSql"]
            assert re.search(r"\bFROM\s+forge_stats\b", sql), (panel["title"], sql)
            # Nothing the role cannot read, and nothing that names an identifying column.
            assert not re.search(r"\b(forge_item|forge_source|forge_event|title|url|author|assignees|labels)\b", sql), (
                sql
            )


@pytest.mark.parametrize("overlay", ["staging", "prod"])
def test_the_rendered_dashboards_carry_the_stats_dashboard(overlay: str) -> None:
    (cm,) = _named(overlay, "ConfigMap", "grafana-dashboards")
    assert json.loads(cm["data"]["forge-stats.json"]) == json.loads(DASHBOARD.read_text(encoding="utf-8"))


def test_grafana_is_admitted_to_postgres() -> None:
    policy = next(
        d for d in _render("staging") if d["kind"] == "NetworkPolicy" and d["metadata"]["name"] == "postgres-ingress"
    )
    sources = [p["podSelector"]["matchLabels"]["app.kubernetes.io/name"] for p in policy["spec"]["ingress"][0]["from"]]
    assert "grafana" in sources
