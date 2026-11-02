"""Traefik's memory limit is its own, never the kube-system LimitRange default (OBS-043).

The default is one value for every container in the namespace, and at 384Mi it
OOMKilled the ingress under a load test while the node had gigabytes free.
"""

from __future__ import annotations

import pathlib

import jinja2
import yaml

from tests.ansible_jinja import ansible_env

REPO = pathlib.Path(__file__).resolve().parents[1]
ROLE = REPO / "infra/ansible/roles/k3s_server"


def _mebibytes(value: str) -> int:
    assert value.endswith("Mi"), value
    return int(value[:-2])


def test_the_rendered_chart_values_declare_request_and_limit() -> None:
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
    env = ansible_env(str(ROLE / "templates"), undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
    rendered = env.get_template("traefik-helmconfig.yaml.j2").render(**defaults, ansible_managed="Ansible managed")
    values = yaml.safe_load(yaml.safe_load(rendered)["spec"]["valuesContent"])
    assert values["resources"]["requests"]["memory"] == defaults["k3s_traefik_memory_request"]
    assert values["resources"]["limits"]["memory"] == defaults["k3s_traefik_memory_limit"]


def test_the_limit_is_above_the_namespace_default_that_killed_it() -> None:
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
    governance = REPO / "infra/k8s/base/governance/kube-system-limitrange.yaml"
    limitrange = yaml.safe_load(governance.read_text(encoding="utf-8"))
    default = limitrange["spec"]["limits"][0]["default"]["memory"]
    assert _mebibytes(defaults["k3s_traefik_memory_limit"]) > _mebibytes(default)
    assert _mebibytes(defaults["k3s_traefik_memory_request"]) < _mebibytes(defaults["k3s_traefik_memory_limit"])
