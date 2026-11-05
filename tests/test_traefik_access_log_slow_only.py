"""K3s Traefik logs every slow request, by route, and nothing that can carry a credential (OPS-065, #3076).

Bounding how long Traefik waits for a backend needs to know which routes take
long legitimately, and the K3s edge logged no requests at all (read 2026-11-04:
zero access-log lines in prod's Loki over 24 h). So it logs a request only past a
declared duration, which keeps the volume near zero, and keeps an explicit list
of fields. The path is not among them: it carries the query string, and no OAuth
or API credential may reach Loki (SEC-021). Router and service name the route
without a URL.
"""

from __future__ import annotations

import pathlib
import re

import jinja2
import yaml

from tests.ansible_jinja import ansible_env

ROLE = pathlib.Path(__file__).resolve().parents[1] / "infra/ansible/roles/k3s_server"

KEPT_FIELDS = {
    "RouterName",
    "ServiceName",
    "RequestMethod",
    "DownstreamStatus",
    "OriginStatus",
    "Duration",
    "OriginDuration",
}


def _defaults() -> dict:
    return yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))


def _access() -> dict:
    env = ansible_env(str(ROLE / "templates"), undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
    for acme in (False, True):
        values = {**_defaults(), "k3s_traefik_acme_enabled": acme}
        rendered = env.get_template("traefik-helmconfig.yaml.j2").render(**values, ansible_managed="Ansible managed")
        access = yaml.safe_load(yaml.safe_load(rendered)["spec"]["valuesContent"])["logs"]["access"]
        if acme:
            return access
        assert access["enabled"] is True, "the access log must not depend on ACME being enabled"
    raise AssertionError("unreachable")


def test_slow_requests_are_logged_as_json_and_only_slow_ones() -> None:
    access = _access()
    assert access["enabled"] is True
    assert access["format"] == "json"
    assert access["filters"]["minduration"] == _defaults()["k3s_traefik_access_log_min_duration"]
    assert set(access["filters"]) == {"minduration"}, "another filter would widen what is logged"


def test_the_threshold_is_a_positive_duration() -> None:
    # Wiring alone is not enough: `0` or `0s` would log every request, which is the
    # volume and the exposure this log exists to avoid.
    threshold = str(_access()["filters"]["minduration"])
    found = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|m)", threshold)
    assert found, f"{threshold!r} is not a Go duration in ms, s or m"
    assert float(found.group(1)) > 0, "a zero threshold logs every request"


def test_only_the_declared_fields_are_kept() -> None:
    general = _access()["fields"]["general"]
    assert general["defaultmode"] == "drop"
    assert general["names"] == {name: "keep" for name in KEPT_FIELDS}


def test_no_field_that_carries_a_url_or_a_client_is_kept() -> None:
    kept = {name for name, mode in _access()["fields"]["general"]["names"].items() if mode != "drop"}
    for name in ("RequestPath", "RequestAddr", "RequestHost", "ClientHost", "ClientAddr", "ClientUsername"):
        assert name not in kept, name


def test_no_header_is_logged() -> None:
    headers = _access()["fields"]["headers"]
    assert headers["defaultmode"] == "drop"
    assert not headers.get("names")
