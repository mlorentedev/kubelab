"""#1581: every host an Authelia rule names explicitly is one the environment routes.

A service that leaves the cluster keeps its access rule unless something checks:
prod granted `bypass` to `wiki.kubelab.live` for months after the wiki was
retired, so whatever next answered on that name would have been public without
anyone deciding it. Wildcard rules are exempt: they name a class of hosts, not one.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# The Authelia configuration each environment ships: base is staging's, prod overrides it.
CONFIGS = {
    "staging": PROJECT_ROOT / "infra/k8s/base/services/authelia-config/configuration.yml",
    "prod": PROJECT_ROOT / "infra/k8s/overlays/prod/authelia-config/configuration.yml",
}


def _routed_hosts(env: str) -> set[str]:
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not on PATH: Authelia rules were NOT checked against routes")
    out = subprocess.run(
        ["kubectl", "kustomize", str(PROJECT_ROOT / "infra/k8s/overlays" / env)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return set(re.findall(r"Host\(`([^`]+)`\)", out))


def _explicit_rule_domains(config: Path) -> set[str]:
    rules = yaml.safe_load(config.read_text(encoding="utf-8"))["access_control"]["rules"]
    domains: set[str] = set()
    for rule in rules:
        named = rule["domain"] if isinstance(rule["domain"], list) else [rule["domain"]]
        domains.update(d for d in named if "*" not in d)
    return domains


@pytest.mark.parametrize("env", sorted(CONFIGS))
def test_every_explicit_rule_names_a_routed_host(env: str) -> None:
    unrouted = _explicit_rule_domains(CONFIGS[env]) - _routed_hosts(env)
    assert not unrouted, f"{env}: Authelia rules for hosts no IngressRoute serves: {sorted(unrouted)}"
