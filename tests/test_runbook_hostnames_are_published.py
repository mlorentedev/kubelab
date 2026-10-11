"""Every hostname a runbook tells you to try is one something serves.

The blog was killed on 2026-03-15 and its name stayed in seven runbooks, with
`curl -f https://blog.kubelab.live` as a verification step, until 2026-10-11.
Staging web moved to `staging.mlorente.dev` and six steps kept probing
`web.staging.kubelab.live`. A step against a name nothing serves fails for a
reason unrelated to what it checks, which is the worst moment to learn the doc
is stale.

Prod names are published in `infra/terraform/dns/services.json` (the apex and
`www` are resources of their own). Staging names cannot be checked against DNS:
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

REPO = Path(__file__).resolve().parent.parent
DOCS = [REPO / "docs/runbooks", REPO / "docs/troubleshooting", REPO / "docs/architecture"]

# Architecture files that do not describe the running system, each with why.
NOT_CURRENT = {
    "docs/architecture/dash-001-homepage-cockpit.md": "dated snapshot of the cockpit's first inventory",
    "docs/architecture/components/kubelab-console.md": "design doc for a product with no code yet",
    "docs/architecture/diagram.md": "#825, still draws OpenClaw, PicoClaw and Prometheus",
}

# Names used as placeholders in examples, never meant to resolve.
PLACEHOLDERS = {"name", "newservice", "svc", "service"}

# Stale today, each with the ticket that removes it. This list may only shrink:
# an entry whose name no longer appears fails a test below, so it is deleted
# with the fix rather than left to excuse a future regression.
KNOWN_STALE = {
    "jetson": "#964, Headscale extra_records, retirement tracked there",
}

# A backslash is an edge too: Mermaid labels write `\ntasks.kubelab.live`.
_EDGE = r"(?<![A-Za-z0-9.\\-])"
PROD = re.compile(_EDGE + r"([a-z0-9-]+)\.kubelab\.live\b")
STAGING = re.compile(_EDGE + r"([a-z0-9-]+)\.staging\.kubelab\.live\b")


def _docs() -> dict[str, str]:
    texts = {}
    for root in DOCS:
        for path in root.rglob("*.md"):
            rel = str(path.relative_to(REPO))
            if rel not in NOT_CURRENT:
                texts[rel] = path.read_text()
    return texts


def _mentioned(pattern: re.Pattern[str]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for rel, text in _docs().items():
        for match in pattern.finditer(text):
            found.setdefault(match.group(1), set()).add(rel)
    return found


def _published() -> set[str]:
    records = json.loads((REPO / "infra/terraform/dns/services.json").read_text())
    return {r["name"] for r in records if r.get("zone") == "kubelab"} | {"www"}


def _routed_in_staging() -> set[str]:
    names: set[str] = set()
    for root in (REPO / "infra/k8s/base", REPO / "infra/k8s/overlays/staging"):
        for path in root.rglob("*.yaml"):
            names |= set(STAGING.findall(path.read_text()))
    return names


def test_every_prod_name_in_the_docs_is_published() -> None:
    allowed = _published() | PLACEHOLDERS | set(KNOWN_STALE) | {"staging"}
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


def test_known_stale_entries_are_still_stale() -> None:
    mentioned = _mentioned(PROD)
    gone = [n for n in KNOWN_STALE if n not in mentioned]
    published = [n for n in KNOWN_STALE if n in _published()]
    assert not gone, f"no longer mentioned, delete from KNOWN_STALE: {gone}"
    assert not published, f"now published, delete from KNOWN_STALE: {published}"
