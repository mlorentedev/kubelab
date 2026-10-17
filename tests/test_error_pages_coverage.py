"""Every route carries `error-pages` or says why not (OPS-030, ADR-072).

Hand-written IngressRoutes drifted from the generated ones: in prod, `authelia`,
`vikunja` and `n8n` had no branded 502-504 while staging `authelia` did, and
nothing noticed. The exceptions are declared once, with a reason each, in
`edge.errors.coverage.exceptions` (common.yaml). The unit is a route *rule*, because
`n8n` has a webhook rule that must not be intercepted next to a UI rule that must.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
COMMON = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text(encoding="utf-8"))
EXCEPTIONS = COMMON["edge"]["errors"]["coverage"]["exceptions"]
OVERLAYS = ["staging", "prod"]


def _rules(overlay: str) -> list[tuple[str, str, set[str]]]:
    """(IngressRoute name, match, middleware names) for every rule an overlay renders."""
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not on PATH: cannot render the overlay (a skip is CANNOT CHECK, not OK)")
    out = subprocess.run(
        ["kubectl", "kustomize", str(REPO / "infra/k8s/overlays" / overlay)], capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    rules = []
    for doc in yaml.safe_load_all(out.stdout):
        if not doc or doc.get("kind") != "IngressRoute":
            continue
        for rule in doc["spec"].get("routes", []):
            names = {m["name"] for m in rule.get("middlewares") or []}
            rules.append((doc["metadata"]["name"], rule["match"], names))
    return rules


def _excepted(route: str, match: str) -> bool:
    return any(e["route"] == route and e.get("match", "") in match for e in EXCEPTIONS)


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_every_rule_has_error_pages_or_a_declared_exception(overlay: str) -> None:
    gaps = [
        f"{route}: {match}"
        for route, match, names in _rules(overlay)
        if "error-pages" not in names and not _excepted(route, match)
    ]
    assert not gaps, (
        f"{overlay}: rules without `error-pages` and without an entry in edge.errors.coverage.exceptions: {gaps}"
    )


def test_every_exception_still_has_a_reason() -> None:
    assert all(e.get("reason", "").strip() for e in EXCEPTIONS), "an exception without a reason is a hole"


def test_no_exception_is_stale() -> None:
    """An entry that matches no rule missing the middleware in any overlay is a lie in the SSOT."""
    gaps = [(r, m) for o in OVERLAYS for r, m, names in _rules(o) if "error-pages" not in names]
    stale = [
        e
        for e in EXCEPTIONS
        if not any(e["route"] == r and e.get("match", "") in m for r, m in gaps)
    ]
    assert not stale, f"exceptions that no longer match a rule without the middleware: {stale}"
