"""A branded error page must be reachable, and a test must say by what (OPS-030, ADR-072, lesson-584).

Five of ten pages shipped in every `errors` image could never be served: nothing
targeted them. The audit that found it was a one-off; this makes it a CI failure.

A page `errors/<status>.html` is reachable when either
  - a Traefik `errors` Middleware lists its status and queries `/errors/{status}.html`, or
  - nginx maps a status it can itself generate to it with `error_page` (the catch-all 404,
    which is `return 404` inside nginx), or
  - it is a declared source page: a file consumed by something other than a request path.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from functools import cache
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
PAGES_DIR = ROOT / "edge" / "errors" / "html" / "errors"
NGINX_CONF = ROOT / "edge" / "errors" / "nginx.conf"
OVERLAYS = ["staging", "prod"]


def _expand(spec: str | int) -> set[int]:
    """`"502-504"` -> {502, 503, 504}; `404` -> {404}. Traefik's range syntax."""
    low, _, high = str(spec).partition("-")
    return set(range(int(low), int(high or low) + 1))


@cache
def _middleware_statuses() -> set[int]:
    """Statuses that an `errors` Middleware an overlay deploys sends to `/errors/{status}.html`.

    Read from the rendered overlays, as `test_error_pages_coverage.py` reads routes: a file
    no kustomization lists is never applied, so its Middleware targets nothing (#2621).
    """
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not on PATH: cannot render the overlays (a skip is CANNOT CHECK, not OK)")
    found: set[int] = set()
    for overlay in OVERLAYS:
        out = subprocess.run(
            ["kubectl", "kustomize", str(ROOT / "infra/k8s/overlays" / overlay)], capture_output=True, text=True
        )
        assert out.returncode == 0, out.stderr
        for doc in yaml.safe_load_all(out.stdout):
            if not isinstance(doc, dict) or doc.get("kind") != "Middleware":
                continue
            errors = (doc.get("spec") or {}).get("errors") or {}
            # Only a Middleware that sends the exact page path to the `errors` service counts: one that
            # points at another service, or a query that merely contains the text, serves nothing here.
            if (errors.get("service") or {}).get("name") != "errors" or errors.get("query") != "/errors/{status}.html":
                continue
            for entry in errors.get("status") or []:
                found |= _expand(entry)
    return found


def _nginx_error_pages() -> dict[int, str]:
    """`error_page 404 /errors/404.html;` -> {404: "404.html"}."""
    text = NGINX_CONF.read_text(encoding="utf-8")
    return {int(m[0]): m[1] for m in re.findall(r"^\s*error_page\s+(\d{3})\s+/errors/([\w.-]+);", text, re.M)}


# Pages that are not served by a request path but consumed as files. The ban page is rendered by
# the CrowdSec bouncer plugin from a mounted file (ADR-072 phase 2), so nothing targets it by status.
# That consumer does not exist yet: #2368 owns it, and replaces this entry with a check that the
# HelmChartConfig mounts the file. An entry here is a debt with an owner, not a permanent exemption.
SOURCE_PAGES = {"403.html": "CrowdSec ban page source (ADR-072 phase 2, OPS-037 / #2368)"}


def _nginx_emits() -> set[int]:
    """Statuses this nginx generates for itself: `return NNN` and `try_files ... =NNN`.

    Derived from the config, not assumed. An `error_page` for any other status is decoration,
    which is how 401/408/429/500 sat in the config for months. Measured on the built image:
    `/errors/`, `/errors` and an unknown path all answer 404, and nothing here answers 403.
    """
    text = NGINX_CONF.read_text(encoding="utf-8")
    found = {int(n) for n in re.findall(r"\breturn\s+(\d{3})\b", text)}
    found |= {int(n) for n in re.findall(r"try_files\s+[^;]*=(\d{3})\s*;", text)}
    return {status for status in found if status >= 400}  # `return 200` and `return 204` are not errors


PAGES = sorted(PAGES_DIR.glob("*.html"))


def test_the_scan_sees_the_sources() -> None:
    """A parser that finds nothing would pass every page below for the wrong reason."""
    assert {502, 503, 504} <= _middleware_statuses()
    assert 404 in _nginx_error_pages()
    assert _nginx_emits() == {404}, _nginx_emits()
    assert PAGES, "no pages found"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_a_page_is_targeted_by_something(page: Path) -> None:
    status = int(page.stem)
    via_middleware = status in _middleware_statuses()
    via_nginx = status in _nginx_emits() and _nginx_error_pages().get(status) == page.name
    assert via_middleware or via_nginx or page.name in SOURCE_PAGES, (
        f"{page.name} is served by nothing: no errors Middleware lists {status} and nginx has no "
        f"`error_page {status} /errors/{page.name}` for a status nginx emits. Delete it, target it, or declare it "
        f"in SOURCE_PAGES (ADR-072)."
    )


def test_every_nginx_error_page_points_at_a_file_that_exists() -> None:
    missing = [name for name in _nginx_error_pages().values() if not (PAGES_DIR / name).exists()]
    assert not missing, missing


def test_maintenance_page_stays_gone() -> None:
    """Nothing routed to it; ADR-072 deleted it."""
    assert not (PAGES_DIR.parent / "maintenance.html").exists()


def test_a_declared_source_page_exists() -> None:
    """An allowlist entry for a file that is gone would excuse the next page given that name."""
    assert all((PAGES_DIR / name).exists() for name in SOURCE_PAGES)


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_every_served_page_has_a_json_twin_with_its_own_status(page: Path) -> None:
    """`Accept: application/json` is rewritten to `<status>.json` (AC5); a missing twin is a 404 for an API client.

    The source page (403) is never requested by status, so it needs no twin.
    """
    if page.name in SOURCE_PAGES:
        pytest.skip("source page: rendered by the ban plugin, never negotiated")
    twin = page.with_suffix(".json")
    assert twin.exists(), f"{twin.name} is missing: an API client asking for JSON would get a 404"
    assert json.loads(twin.read_text(encoding="utf-8"))["error"]["status"] == int(page.stem)
