"""The edge stops waiting for a backend after a declared bound, or says why not (OPS-065, ADR-076).

Traefik 3.6 waits forever for a backend's response headers unless told otherwise, so a
backend that accepts a connection and never answers holds every request sent to it.
The default bound is a static `serversTransport` argument in the K3s HelmChartConfig,
from the `k3s_server` role defaults. A route that needs a longer one references a
`ServersTransport` of its own, declared once with a reason in
`edge.backend_timeouts.exceptions` (common.yaml). The unit is a route rule, as for
`error-pages` (ADR-072).

A `ServersTransport` object does not inherit the static defaults: one that omits
`dialTimeout` gets Traefik's 30 s, so every exception restates the default dial bound.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
from typing import Any

import jinja2
import pytest
import yaml

from tests.ansible_jinja import ansible_env

REPO = pathlib.Path(__file__).resolve().parents[1]
ROLE = REPO / "infra/ansible/roles/k3s_server"
COMMON = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text(encoding="utf-8"))
EXCEPTIONS: list[dict[str, str]] = COMMON["edge"]["backend_timeouts"]["exceptions"]
OVERLAYS = ["staging", "prod"]


def _defaults() -> dict[str, Any]:
    return yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))


def _arguments(acme: bool) -> list[str]:
    env = ansible_env(str(ROLE / "templates"), undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
    values = {**_defaults(), "k3s_traefik_acme_enabled": acme}
    rendered = env.get_template("traefik-helmconfig.yaml.j2").render(**values, ansible_managed="Ansible managed")
    return yaml.safe_load(yaml.safe_load(rendered)["spec"]["valuesContent"]).get("additionalArguments") or []


def _render(overlay: str) -> list[dict[str, Any]]:
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not on PATH: cannot render the overlay (a skip is CANNOT CHECK, not OK)")
    out = subprocess.run(
        ["kubectl", "kustomize", str(REPO / "infra/k8s/overlays" / overlay)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert out.returncode == 0, out.stderr
    return [d for d in yaml.safe_load_all(out.stdout) if d]


def _rules(docs: list[dict[str, Any]]) -> list[tuple[str, str, set[str]]]:
    """(IngressRoute name, match, the serversTransport names its services reference)."""
    return [
        (
            d["metadata"]["name"],
            rule["match"],
            {s["serversTransport"] for s in rule.get("services", []) if s.get("serversTransport")},
        )
        for d in docs
        if d["kind"] == "IngressRoute"
        for rule in d["spec"].get("routes", [])
    ]


def _transports(docs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {d["metadata"]["name"]: d["spec"] for d in docs if d["kind"] == "ServersTransport"}


def _declared(route: str, match: str) -> dict[str, str] | None:
    return next((e for e in EXCEPTIONS if e["route"] == route and e.get("match", "") in match), None)


@pytest.mark.parametrize("acme", [False, True])
def test_the_edge_bounds_how_long_it_waits_for_any_backend(acme: bool) -> None:
    defaults = _defaults()
    arguments = _arguments(acme)
    timeouts = "--serversTransport.forwardingTimeouts"
    assert f"{timeouts}.responseHeaderTimeout={defaults['k3s_traefik_response_header_timeout']}" in arguments
    assert f"{timeouts}.dialTimeout={defaults['k3s_traefik_dial_timeout']}" in arguments
    assert not any(a.startswith(f"{timeouts}.idleConnTimeout") for a in arguments), "ADR-076 D4 keeps the default"


def test_the_default_bounds_are_bounds() -> None:
    defaults = _defaults()
    for key in ("k3s_traefik_response_header_timeout", "k3s_traefik_dial_timeout"):
        assert str(defaults[key]).rstrip("s").isdigit() and int(str(defaults[key]).rstrip("s")) > 0, key


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_a_route_with_its_own_transport_is_a_declared_exception(overlay: str) -> None:
    docs = _render(overlay)
    transports = _transports(docs)
    dial = _defaults()["k3s_traefik_dial_timeout"]
    gaps = []
    for route, match, names in _rules(docs):
        if not names:
            continue
        entry = _declared(route, match)
        if entry is None or names != {entry["transport"]}:
            gaps.append(f"{route}: {match} references {sorted(names)} without a matching declaration")
            continue
        spec = transports.get(entry["transport"])
        if spec is None:
            gaps.append(f"{route}: ServersTransport {entry['transport']} is not in the overlay")
            continue
        forwarding = spec.get("forwardingTimeouts") or {}
        if str(forwarding.get("responseHeaderTimeout")) != str(entry["response_header_timeout"]):
            gaps.append(f"{entry['transport']}: responseHeaderTimeout differs from the declaration")
        if str(forwarding.get("dialTimeout")) != str(dial):
            gaps.append(f"{entry['transport']}: dialTimeout must restate the default {dial}")
    assert not gaps, f"{overlay}: {gaps}"


def test_every_exception_is_used_and_says_why() -> None:
    rendered = [rule for overlay in OVERLAYS for rule in _rules(_render(overlay))]
    stale = [
        e
        for e in EXCEPTIONS
        if not any(e["route"] == r and e.get("match", "") in m and e["transport"] in names for r, m, names in rendered)
    ]
    assert not stale, f"exceptions that no route uses: {stale}"
    assert all(e.get("reason", "").strip() for e in EXCEPTIONS), "an exception without a reason is a hole"


def test_headscale_runs_under_the_default_since_a_node_re_registered_through_it() -> None:
    """ADR-076 D2: the exception was lifted by OPS-065 AC4. Bringing it back is a new decision, recorded there."""
    assert not any(e["route"] == "headscale" for e in EXCEPTIONS)
    names = {n for r, _, ns in _rules(_render("prod")) if r == "headscale" for n in ns}
    assert not names, f"the headscale route still references a transport of its own: {sorted(names)}"
