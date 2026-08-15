"""SEC-004: every K3s IngressRoute route must reference the rate-limit Middleware.

Blanket application (kubelab#970) -- no per-route opt-out, VPN-only routes
included. Reads manifest FILES directly (no kubectl on CI runners), mirroring
`tests/test_spoke_rbac_covers_manifests.py`'s pattern. Generator-produced
routes (`overlays/*/generated/ingress.yaml`) are covered separately by
`tests/test_k8s_generator_middlewares.py`, which tests the generator function
itself rather than its output file, so they are excluded here to avoid
asserting the same fact twice via two different mechanisms.
"""

from __future__ import annotations

import pathlib

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Hand-written manifest roots. `generated/` is excluded (covered by the
#: generator-level test) and `.rendered/` is a gitignored audit dir (ADR-035).
MANIFEST_ROOTS = ("infra/k8s/base", "infra/k8s/overlays")
SKIPPED_PATH_PARTS = frozenset({"generated", ".rendered"})


def _hand_written_ingressroute_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for root in MANIFEST_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.yaml")):
            if SKIPPED_PATH_PARTS & set(path.parts):
                continue
            if "kind: IngressRoute" in path.read_text(encoding="utf-8"):
                files.append(path)
    return files


def _routes_missing_rate_limit(path: pathlib.Path) -> list[str]:
    """Return a list of `<routeIndex> match=<match>` strings lacking rate-limit."""
    missing: list[str] = []
    docs = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
    for doc in docs:
        if not isinstance(doc, dict) or doc.get("kind") != "IngressRoute":
            continue
        name = doc.get("metadata", {}).get("name", "<unnamed>")
        for i, route in enumerate(doc.get("spec", {}).get("routes", [])):
            middleware_names = {m.get("name") for m in route.get("middlewares", [])}
            if "rate-limit" not in middleware_names:
                match = route.get("match", "<no match>")
                missing.append(f"{name}[{i}] match={match}")
    return missing


class TestEveryIngressRouteHasRateLimit:
    def test_at_least_one_hand_written_file_found(self) -> None:
        """Guard the guard: if this list goes to zero, the test below is vacuous."""
        files = _hand_written_ingressroute_files()
        assert len(files) >= 10, (
            f"Expected >=10 hand-written IngressRoute files, found {len(files)}: {files}. "
            "If routes were genuinely consolidated, lower this bound deliberately."
        )

    def test_every_route_in_every_file_references_rate_limit(self) -> None:
        failures: dict[str, list[str]] = {}
        for path in _hand_written_ingressroute_files():
            missing = _routes_missing_rate_limit(path)
            if missing:
                failures[str(path.relative_to(REPO_ROOT))] = missing
        assert not failures, (
            "These IngressRoute routes are missing the rate-limit middleware "
            f"(SEC-004 is blanket -- no exceptions): {failures}"
        )
