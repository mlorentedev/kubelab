"""Every IngressRoute rule must outrank the catch-all, never tie with it.

The catch-all sends any `*.kubelab.live` host no other rule claims to the errors
service, at an explicit low priority. Traefik picks the highest priority, and a
rule with no priority gets the length of its match. A rule declared at the
catch-all's own priority is a tie, which Traefik breaks by router name: the
service works until a restart re-orders the routers, then answers the errors
404 for every path. Measured in prod on 2026-11-06: Argo CD's passthrough rule
carried `priority: 1`, Traefik restarted at 04:39 UTC, and the whole UI and API
went to the errors service while the hub was healthy (lesson-717).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

OVERLAYS = ("staging", "prod")
REPO = Path(__file__).resolve().parent.parent


def _render(overlay: str) -> list[dict]:
    if not shutil.which("kubectl"):
        if os.environ.get("CI"):
            pytest.fail("kubectl is required in CI to render the overlays")
        pytest.skip("kubectl not installed")
    out = subprocess.run(
        ["kubectl", "kustomize", str(REPO / "infra/k8s/overlays" / overlay)],
        capture_output=True,
        check=True,
        encoding="utf-8",
    ).stdout
    return [doc for doc in yaml.safe_load_all(out) if doc]


def _routes(docs: list[dict]) -> list[tuple[str, dict]]:
    return [
        (doc["metadata"]["name"], route)
        for doc in docs
        if doc.get("kind") == "IngressRoute"
        for route in doc["spec"].get("routes", [])
    ]


def _priority(route: dict) -> int:
    """Traefik's effective priority: the declared one, else the length of the rule."""
    return route.get("priority") or len(route["match"])


def _catch_all(routes: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    return [
        (name, route)
        for name, route in routes
        if route["match"].startswith("HostRegexp(") and [s["name"] for s in route.get("services", [])] == ["errors"]
    ]


def _claimable(route: dict, catch_all: list[tuple[str, dict]]) -> bool:
    """Whether the catch-all could take this rule's traffic: one of its hosts matches a catch-all regexp.

    A rule naming no literal host is judged too, since it may match anything.
    """
    hosts = [h for args in re.findall(r"\bHost\(([^)]*)\)", route["match"]) for h in re.findall(r"`([^`]+)`", args)]
    patterns = [p for _, r in catch_all for p in re.findall(r"HostRegexp\(`([^`]+)`\)", r["match"])]
    return not hosts or any(re.fullmatch(p, h) for p in patterns for h in hosts)


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_the_render_has_a_catch_all(overlay: str) -> None:
    """Without one, the check below compares against nothing and passes."""
    assert _catch_all(_routes(_render(overlay))), f"{overlay}: no catch-all route to the errors service rendered"


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_every_route_outranks_the_catch_all(overlay: str) -> None:
    routes = _routes(_render(overlay))
    catch_all = _catch_all(routes)
    ceiling = max(_priority(route) for _, route in catch_all)
    tied = sorted(
        f"{name}: {route['match']} (priority {_priority(route)})"
        for name, route in routes
        if (name, route) not in catch_all and _claimable(route, catch_all) and _priority(route) <= ceiling
    )
    assert not tied, (
        f"{overlay}: these rules do not outrank the catch-all (priority {ceiling}), so a Traefik "
        f"restart can hand their traffic to the errors service: {tied}"
    )
