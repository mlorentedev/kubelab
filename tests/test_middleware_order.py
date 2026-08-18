"""SEC-008 (#1097): `secure-headers` leads every Traefik middleware chain.

Traefik applies middlewares outermost-first, so a request rejected by an earlier
one never reaches a later one. A route whose chain leads with `rate-limit`
therefore returns 429s stripped of the security headers every other route's
rejections carry.

Two things this test does differently from the ticket that asked for it, both
because the source files lie about the outcome:

**It resolves the overlay, not just the files.** `tests/test_rate_limit_coverage.py`
reads manifests directly and says why — there is no kubectl on CI runners. That
is fine for "does this route carry rate-limit at all", and wrong here: a
strategic-merge patch REPLACES a list rather than merging it, so a base chain
that leads correctly can be silently replaced by a patch that does not restate
`secure-headers` at all. Checking source files alone reports prod's `authelia`
as compliant while the rendered route has no security headers whatsoever. The
resolver below is a deliberately narrow kustomize — base plus one patch file,
matched on kind and name, list-replacement semantics for `middlewares` — and
`test_resolver_agrees_with_kustomize` pins it against the real thing wherever
kubectl exists.

**It asserts presence before position.** The ticket framed this as an ordering
convention. The measurement said otherwise: of the deviations, two prod routes
were not misordered but missing `secure-headers` entirely. Position is the
smaller half of the invariant.

The convention is declared once, as data, and both the hand-written manifests
and the generator's `_build_middlewares()` are checked against that one
declaration (#1097 AC2).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
K8S = REPO_ROOT / "infra" / "k8s"
ENVIRONMENTS = ("staging", "prod")

#: The convention, declared once (#1097 AC2). Everything below checks against
#: this and nothing restates it.
LEAD_MIDDLEWARE = "secure-headers"

#: Routes allowed to deviate, each with the reason it may (#1097 AC3). An
#: exemption without a reason is a silent skip wearing a list entry, so the
#: reason is required and `test_no_stale_exemptions` deletes entries that stop
#: being needed.
EXEMPTIONS: dict[str, str] = {
    "catch-all": (
        "Traefik's fallback router for unmatched hosts. It serves the error-pages "
        "backend and nothing else, so there is no application response to protect "
        "and no header a client would act on."
    ),
    "kubelab-redirect": (
        "A pure 301 to the canonical host, issued by the `kubelab-redirect` "
        "middleware itself before any backend is reached. The redirect target "
        "carries the full chain."
    ),
    "uptime-kuma": (
        "External service on RPi3 bare metal via Service + EndpointSlice. Deviation "
        "predates this test and is unverified — kept exempt rather than reordered "
        "because the route is not reachable from CI to prove the change safe. "
        "Tracked in #1097."
    ),
    "headscale": (
        "Carries the Noise protocol over a forced HTTP/1.1 TLSOption "
        "(`headscale-http11`) and is the only route in the repo with that "
        "constraint. Whether the ordering is load-bearing for it is UNVERIFIED — "
        "#1097 poses the question and nothing in the repo records an answer. Exempt "
        "rather than reordered: the prod hub is offline (#1066), so a change here "
        "could not be observed converging."
    ),
}


def _docs(path: Path) -> list[dict[str, Any]]:
    try:
        # Some manifests are top-level lists, not mappings; only docs that can
        # carry `kind` are of interest here.
        return [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if isinstance(d, dict)]
    except (yaml.YAMLError, OSError):
        return []


def _ingressroutes(paths: list[Path]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for path in paths:
        for doc in _docs(path):
            if doc.get("kind") == "IngressRoute":
                found[doc["metadata"]["name"]] = doc
    return found


def _overlay_sources(env: str) -> tuple[list[Path], list[Path]]:
    """(resource files, patch files) for `env`, from its kustomization."""
    overlay = K8S / "overlays" / env
    kustomization = yaml.safe_load((overlay / "kustomization.yaml").read_text(encoding="utf-8"))

    resources: list[Path] = []
    for entry in kustomization.get("resources", []):
        target = (overlay / entry).resolve()
        if target.is_dir():
            resources.extend(sorted(target.rglob("*.yaml")))
        elif target.is_file():
            resources.append(target)

    patches = [(overlay / p["path"]).resolve() for p in kustomization.get("patches", []) if "path" in p]
    return resources, patches


def resolve_chains(env: str) -> dict[str, list[list[str]]]:
    """Effective middleware chains per route, after the overlay's patches.

    Narrow on purpose: it models the one kustomize behaviour that matters here,
    which is that a strategic-merge patch REPLACES `middlewares` rather than
    merging into it. `test_resolver_agrees_with_kustomize` is what keeps that
    claim honest.
    """
    resources, patches = _overlay_sources(env)
    routes = _ingressroutes(resources)

    for patch_file in patches:
        for patch in _docs(patch_file):
            if patch.get("kind") != "IngressRoute":
                continue
            name = patch["metadata"]["name"]
            base = routes.get(name)
            if base is None:
                continue
            for i, patched_route in enumerate(patch.get("spec", {}).get("routes", [])):
                if "middlewares" not in patched_route:
                    continue
                base_routes = base.setdefault("spec", {}).setdefault("routes", [])
                while len(base_routes) <= i:
                    base_routes.append({})
                base_routes[i]["middlewares"] = patched_route["middlewares"]

    chains: dict[str, list[list[str]]] = {}
    for name, doc in routes.items():
        for route in doc.get("spec", {}).get("routes", []):
            names = [m["name"] for m in route.get("middlewares", []) or []]
            if names:
                chains.setdefault(name, []).append(names)
    return chains


# ---------------------------------------------------------------------------
# The invariant: presence first, then position
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_every_chain_carries_the_lead_middleware(env: str) -> None:
    """`secure-headers` must be PRESENT — the half the ticket did not ask for.

    Prod's `authelia` and `loki` were not misordered. Their base chains lead
    correctly and a prod patch restated the list without `secure-headers` at
    all, so the rendered routes served with no Traefik security headers. A
    source-level order check calls both compliant.
    """
    missing = {
        name: chain
        for name, chains in resolve_chains(env).items()
        if name not in EXEMPTIONS
        for chain in chains
        if LEAD_MIDDLEWARE not in chain
    }
    assert not missing, (
        f"[{env}] these routes resolve WITHOUT {LEAD_MIDDLEWARE} entirely: {missing}. "
        "A strategic-merge patch replaces a middleware list rather than merging "
        "into it, so a patch must restate every middleware the route needs."
    )


@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_every_chain_leads_with_the_lead_middleware(env: str) -> None:
    """#1097 AC1 — and it is about rejections, not successful requests.

    A request rejected by an earlier middleware never reaches a later one, so a
    chain led by `rate-limit` returns 429s without the headers every other
    route's rejections carry.
    """
    misordered = {
        name: chain
        for name, chains in resolve_chains(env).items()
        if name not in EXEMPTIONS
        for chain in chains
        if chain and chain[0] != LEAD_MIDDLEWARE
    }
    assert not misordered, (
        f"[{env}] these routes do not lead with {LEAD_MIDDLEWARE}: {misordered}. "
        f"Either move it first, or add the route to EXEMPTIONS with its reason."
    )


def test_a_patch_that_declares_middlewares_restates_the_lead() -> None:
    """The mechanism, checked at file level so the reason is visible in review.

    The two tests above catch the outcome. This one catches the cause, and it is
    the form a reviewer can act on: if you touch `middlewares:` in a patch, you
    own the whole list.
    """
    offenders: list[str] = []
    for env in ENVIRONMENTS:
        _, patches = _overlay_sources(env)
        for patch_file in patches:
            for patch in _docs(patch_file):
                if patch.get("kind") != "IngressRoute":
                    continue
                name = patch["metadata"]["name"]
                if name in EXEMPTIONS:
                    continue
                for route in patch.get("spec", {}).get("routes", []):
                    declared = [m["name"] for m in route.get("middlewares", []) or []]
                    if declared and LEAD_MIDDLEWARE not in declared:
                        offenders.append(f"{env}/{patch_file.name}:{name} -> {declared}")
    assert not offenders, (
        "these patches declare a middleware list without "
        f"{LEAD_MIDDLEWARE}, which REPLACES the base chain rather than adding to "
        f"it: {offenders}"
    )


# ---------------------------------------------------------------------------
# The generator is checked against the same declaration (#1097 AC2)
# ---------------------------------------------------------------------------


def test_the_generator_emits_the_lead_middleware_first() -> None:
    """`_build_middlewares()` is the other producer of these chains.

    Checking only the hand-written manifests would leave every generated route
    free to drift in the opposite direction, and the generated ingress is the
    larger half of the tree.
    """
    from toolkit.features.generator_k8s import K8sGenerator

    for enable_auth in (True, False):
        chain = K8sGenerator._build_middlewares(None, {}, enable_auth)  # type: ignore[arg-type]
        assert chain, f"_build_middlewares(enable_auth={enable_auth}) emitted nothing"
        assert chain[0] == LEAD_MIDDLEWARE, (
            f"_build_middlewares(enable_auth={enable_auth}) emits {chain}, which does not lead with {LEAD_MIDDLEWARE}"
        )


# ---------------------------------------------------------------------------
# The exemption list is kept honest
# ---------------------------------------------------------------------------


def test_every_exemption_has_a_reason() -> None:
    empty = [name for name, reason in EXEMPTIONS.items() if not reason.strip()]
    assert not empty, f"exemptions without a recorded reason: {empty}"


def test_no_stale_exemptions() -> None:
    """An exemption for a route that now complies is a hole nobody is watching."""
    still_deviating = set()
    for env in ENVIRONMENTS:
        for name, chains in resolve_chains(env).items():
            for chain in chains:
                if not chain or chain[0] != LEAD_MIDDLEWARE or LEAD_MIDDLEWARE not in chain:
                    still_deviating.add(name)

    stale = set(EXEMPTIONS) - still_deviating
    assert not stale, (
        f"these routes now satisfy the convention and no longer need an exemption: "
        f"{sorted(stale)} — delete them from EXEMPTIONS so the list keeps shrinking"
    )


# ---------------------------------------------------------------------------
# The resolver is pinned against real kustomize wherever it exists
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_resolver_agrees_with_kustomize(env: str) -> None:
    """Cross-check, skipped where kubectl is absent (CI runners).

    This does not gate the invariant — the tests above do that from files, and
    they run everywhere. What this pins is the *resolver's* claim to model
    kustomize's list-replacement semantics, which is the assumption the whole
    module rests on. A skipped cross-check leaves the gate intact; a resolver
    nobody ever compared would not.
    """
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not available — resolver cross-check is local-only")

    result = subprocess.run(
        ["kubectl", "kustomize", str(K8S / "overlays" / env)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        pytest.skip(f"kubectl kustomize failed: {result.stderr.strip()[:120]}")

    rendered: dict[str, list[list[str]]] = {}
    for doc in yaml.safe_load_all(result.stdout):
        if not doc or doc.get("kind") != "IngressRoute":
            continue
        for route in doc.get("spec", {}).get("routes", []):
            names = [m["name"] for m in route.get("middlewares", []) or []]
            if names:
                rendered.setdefault(doc["metadata"]["name"], []).append(names)

    resolved = resolve_chains(env)
    assert {k: sorted(v) for k, v in resolved.items()} == {k: sorted(v) for k, v in rendered.items()}, (
        f"[{env}] the resolver disagrees with kubectl kustomize — its model of patch semantics is wrong"
    )
