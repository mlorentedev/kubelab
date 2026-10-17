"""SSOT-027 (#1782): every OIDC consumer presents the client_id the SSOT declares.

`apps.services.security.authelia.oidc_clients` generates what Authelia registers
(SSOT-017). The apps that present those ids still carry them in their own config
formats (an env file, Helm values, a shell script, a playbook), so renaming a client
in the SSOT changed what Authelia accepts and not what the app sends: the failure is
`invalid_client` at login, which reads as the app's bug.

Each consumer is tied to its client by the client's `redirect.domain` key, not by the
id itself, so this test carries no copy of any id: change one side and it goes red.
The Compose Grafana reads its id from the loader, which derives it from the same list.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.features.configuration import ConfigurationManager

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "infra/config/values/common.yaml"

# (client's redirect.domain key, consumer file, pattern capturing the id it presents)
CONSUMERS = [
    (
        "apps.services.observability.grafana.domain",
        "infra/k8s/base/services/grafana-config/grafana.env",
        r"^GF_AUTH_GENERIC_OAUTH_CLIENT_ID=(\S+)$",
    ),
    (
        "apps.services.core.vikunja.domain",
        "infra/k8s/base/services/vikunja-config/vikunja.env",
        r"^VIKUNJA_AUTH_OPENID_PROVIDERS_AUTHELIA_CLIENTID=(\S+)$",
    ),
    ("argocd.domain", "infra/helm/argocd/values.yaml", r"^\s+clientID:\s*(\S+)$"),
    ("apps.services.core.gitea.domain", "infra/ansible/roles/beelink_services/files/gitea-bootstrap.sh", r"--key (\S+)"),
    (
        "apps.services.ai.open_webui.domain",
        "infra/ansible/playbooks/provision-ace2.yml",
        r"agent_stack_webui_oidc_client_id:\s*(\S+)",
    ),
]


def _common() -> dict[str, Any]:
    return yaml.safe_load(COMMON.read_text(encoding="utf-8"))


def _client_for(domain_key: str) -> str:
    clients = _common()["apps"]["services"]["security"]["authelia"]["oidc_clients"]
    ids = [c["client_id"] for c in clients if c.get("redirect", {}).get("domain") == domain_key]
    assert len(ids) == 1, f"expected one OIDC client redirecting to {domain_key}, found {ids}"
    return ids[0]


def test_every_ssot_client_has_a_listed_consumer() -> None:
    """A new client with no consumer row would be guarded by nothing."""
    clients = _common()["apps"]["services"]["security"]["authelia"]["oidc_clients"]
    declared = {c["redirect"]["domain"] for c in clients}
    assert declared == {key for key, _, _ in CONSUMERS}


@pytest.mark.parametrize(("domain_key", "path", "pattern"), CONSUMERS, ids=[c[1] for c in CONSUMERS])
def test_the_consumer_presents_the_declared_client_id(domain_key: str, path: str, pattern: str) -> None:
    presented = set(re.findall(pattern, (ROOT / path).read_text(encoding="utf-8"), flags=re.MULTILINE))
    assert presented, f"{path}: no client id found; the pattern no longer matches the file"
    assert presented == {_client_for(domain_key)}, f"{path} presents {sorted(presented)}"


def test_argocd_url_is_its_declared_host() -> None:
    values = yaml.safe_load((ROOT / "infra/helm/argocd/values.yaml").read_text(encoding="utf-8"))
    assert values["configs"]["cm"]["url"] == f"https://{_common()['argocd']['domain']}"


@pytest.mark.parametrize("env", ("dev", "staging", "prod"))
def test_the_compose_grafana_id_is_derived_not_declared(env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Goes through `get_merged_config`, so dropping the derivation step fails here, not at login."""
    grafana = _common()["apps"]["services"]["observability"]["grafana"]
    assert "oauth_client_id" not in grafana, "a second declaration of the id; the loader derives it"
    manager = ConfigurationManager(env, ROOT)
    monkeypatch.setattr(manager, "_decrypt_sops", lambda _path: {})
    derived = manager.get_merged_config()["apps"]["services"]["observability"]["grafana"]["oauth_client_id"]
    assert derived == _client_for("apps.services.observability.grafana.domain")


def test_a_stale_override_does_not_win_over_the_derivation() -> None:
    config = _common()
    config["apps"]["services"]["observability"]["grafana"]["oauth_client_id"] = "stale-client"
    ConfigurationManager._inject_oidc_client_derivations(config)
    derived = config["apps"]["services"]["observability"]["grafana"]["oauth_client_id"]
    assert derived == _client_for("apps.services.observability.grafana.domain")
