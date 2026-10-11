"""Every hostname a runbook tells you to try is published or routed.

The blog was killed on 2026-03-15 and its name stayed in seven runbooks, with
`curl -f https://blog.kubelab.live` as a verification step, until 2026-10-11.
Staging web moved to `staging.mlorente.dev` and six steps kept probing
`web.staging.kubelab.live`. A step against a name nothing serves fails for a
reason unrelated to what it checks, which is the worst moment to learn the doc
is stale.

Prod names, in `kubelab.live` and `mlorente.dev`, must be records in
`infra/terraform/dns/services.json` (each apex and `www` are resources of their
own; the staging zones in `networking.staging_zones` resolve over the VPN). A
record proves publication, not that a service answers: one that outlives its
service is a stale record, and removing it is part of the retirement. Staging names cannot be checked against DNS:
the staging zone answers every `*.staging.kubelab.live` with a wildcard, so the
truth is what the manifests route. Any mention of a name under `infra/k8s/base`
or the staging overlay counts as routed, a loose match chosen so the guard never
raises a false alarm.

`docs/architecture` is covered except for the files in NOT_CURRENT.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
DOCS = [REPO / "docs/runbooks", REPO / "docs/troubleshooting", REPO / "docs/architecture"]

# Architecture files that do not describe the running system, each with why.
NOT_CURRENT = {
    "docs/architecture/dash-001-homepage-cockpit.md": "dated snapshot of the cockpit's first inventory",
    "docs/architecture/components/kubelab-console.md": "design doc for a product with no code yet",
    "docs/architecture/diagram.md": "#825, still draws OpenClaw, PicoClaw and Prometheus",
    "docs/architecture/infra/dns-cloudflare.md": "historical zone export of 2025-08-30",
}

# Names used as placeholders in examples, never meant to resolve.
PLACEHOLDERS = {"name", "newservice", "svc", "service"}

# Stale today, each with the ticket that removes it. This list may only shrink:
# an entry whose name no longer appears fails a test below, so it is deleted
# with the fix rather than left to excuse a future regression.
KNOWN_STALE = {
    "jetson": "#964, Headscale extra_records, retirement tracked there",
}

# A dot is not an edge-breaker: in `hub.argocd.kubelab.live` the label checked is
# `argocd`, the one the zone would have to publish.
_EDGE = r"(?<![A-Za-z0-9-])"
PROD = re.compile(_EDGE + r"([a-z0-9-]+)\.kubelab\.live\b")
STAGING = re.compile(_EDGE + r"([a-z0-9-]+)\.staging\.kubelab\.live\b")
PERSONAL = re.compile(_EDGE + r"([a-z0-9-]+)\.mlorente\.dev\b")


def _unescape(text: str) -> str:
    """Mermaid labels break lines with a literal `\\n`, which would otherwise glue
    its `n` to the name that follows and hide it from the edge match."""
    return text.replace("\\n", "\n")


def _docs() -> dict[str, str]:
    texts = {}
    for root in DOCS:
        for path in root.rglob("*.md"):
            rel = str(path.relative_to(REPO))
            if rel not in NOT_CURRENT:
                texts[rel] = _unescape(path.read_text())
    return texts


def _mentioned(pattern: re.Pattern[str]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for rel, text in _docs().items():
        for match in pattern.finditer(text):
            found.setdefault(match.group(1), set()).add(rel)
    return found


def _published(zone: str = "kubelab") -> set[str]:
    records = json.loads((REPO / "infra/terraform/dns/services.json").read_text())
    return {r["name"] for r in records if r.get("zone") == zone} | {"www"}


def _staging_labels() -> set[str]:
    common = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())
    return {zone.split(".")[0] for zone in common["networking"]["staging_zones"]}


def _staging_manifests() -> str:
    texts = []
    for root in (REPO / "infra/k8s/base", REPO / "infra/k8s/overlays/staging"):
        for pattern in ("*.yaml", "*.yml"):
            texts += [path.read_text() for path in root.rglob(pattern)]
    return "\n".join(texts)


def _routed_in_staging() -> set[str]:
    return set(STAGING.findall(_staging_manifests()))


def test_every_prod_name_in_the_docs_is_published() -> None:
    allowed = _published() | PLACEHOLDERS | set(KNOWN_STALE) | _staging_labels()
    unpublished = {n: sorted(p) for n, p in _mentioned(PROD).items() if n not in allowed}
    assert not unpublished, (
        f"docs name prod hosts nothing publishes: {unpublished}. Fix the doc, or "
        "publish the name in services.json if the service is real."
    )


def test_every_staging_name_in_the_docs_is_routed() -> None:
    allowed = _routed_in_staging() | PLACEHOLDERS
    unrouted = {n: sorted(p) for n, p in _mentioned(STAGING).items() if n not in allowed}
    assert not unrouted, (
        f"docs name staging hosts no manifest routes: {unrouted}. The wildcard "
        "resolves them anyway, so the step fails at Traefik, not at DNS."
    )


def test_every_personal_site_name_in_the_docs_is_published() -> None:
    # A staging zone apex (`staging.mlorente.dev`) is VPN-only, so it is no record:
    # it counts when a staging manifest routes it, like any other staging name.
    routed = _staging_manifests()
    apexes = {label for label in _staging_labels() if f"{label}.mlorente.dev" in routed}
    allowed = _published("mlorente") | PLACEHOLDERS | apexes
    unpublished = {n: sorted(p) for n, p in _mentioned(PERSONAL).items() if n not in allowed}
    assert not unpublished, f"docs name mlorente.dev hosts nothing publishes: {unpublished}"


def test_a_mermaid_line_break_does_not_hide_the_name_after_it() -> None:
    assert PROD.findall("A[Ingress\\nblog.kubelab.live]") == ["nblog"]
    assert PROD.findall(_unescape("A[Ingress\\nblog.kubelab.live]")) == ["blog"]


def test_a_nested_name_is_checked_by_its_nearest_label() -> None:
    assert PROD.findall("https://hub.argocd.kubelab.live") == ["argocd"]
    assert STAGING.findall("a.b.staging.kubelab.live") == ["b"]


def test_known_stale_entries_are_still_stale() -> None:
    mentioned = _mentioned(PROD)
    gone = [n for n in KNOWN_STALE if n not in mentioned]
    published = [n for n in KNOWN_STALE if n in _published()]
    assert not gone, f"no longer mentioned, delete from KNOWN_STALE: {gone}"
    assert not published, f"now published, delete from KNOWN_STALE: {published}"
