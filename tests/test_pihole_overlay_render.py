"""OPS-022 / AC3: Pi-hole must render in staging and be absent from prod.

`pihole.kubelab.live` resolves to ace1's Tailscale IP regardless of what prod
ships (services.json's `target` field), so no runtime HTTP probe can ever see
a regression where `pihole.yaml` drifts back into `base/` — every request
lands on staging's Traefik either way. That is the exact shape of the
original defect (#969): prod carried an IngressRoute it could never serve and
ordered ACME certs for a name it never answered, and nothing failed to say so.

The property only exists in the render, so the check has to live there too.
Model: `test_grafana_alerting_render.py` (subprocess `kubectl kustomize`,
skip loudly if kubectl is missing — CANNOT CHECK, not OK). Deliberately not
`test_spoke_rbac_covers_manifests.py`: that test reads manifest *files*, and
a file grep would have passed on the pre-#969 layout just as easily as the
kustomize `tls: {}` bug passed every file-reading check that looked at it.

Includes a positive control (staging renders all three pihole objects) so a
matcher typo cannot pass vacuously forever by finding zero of everything.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Object kinds the pihole manifest ships. Matched by name so a rename of the
#: EndpointSlice (currently "pihole-external") is still caught by name prefix.
PIHOLE_KINDS = {"Service", "EndpointSlice", "IngressRoute"}


def _kustomize(env: str) -> list[dict]:
    """Render an overlay, or skip loudly if kubectl is unavailable.

    A skip here means CANNOT CHECK, which is not the same as OK and must
    never be reported as one.
    """
    if shutil.which("kubectl") is None:
        pytest.skip(
            "CANNOT CHECK: kubectl is not installed, so the rendered output cannot be "
            "produced. This is not a pass — AC3 is unverified in this environment. "
            "Run `make test` on a workstation."
        )

    result = subprocess.run(
        ["kubectl", "kustomize", str(REPO_ROOT / f"infra/k8s/overlays/{env}")],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(f"kubectl kustomize infra/k8s/overlays/{env} failed:\n{result.stderr}")

    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _pihole_objects(env: str) -> list[dict]:
    docs = _kustomize(env)
    return [
        d
        for d in docs
        if d.get("kind") in PIHOLE_KINDS
        and d.get("metadata", {}).get("name", "").startswith("pihole")
    ]


class TestPiholeOverlayRender:
    """Read the emitted manifest, never the file layout."""

    def test_staging_renders_all_three_pihole_objects(self) -> None:
        """Positive control: proves the matcher actually finds pihole when it exists.

        Without this, `test_prod_renders_nothing_pihole` passing means nothing —
        a broken matcher that finds zero of everything would pass it forever.
        """
        found = {d["kind"] for d in _pihole_objects("staging")}
        assert found == PIHOLE_KINDS, (
            f"Staging render is missing {PIHOLE_KINDS - found}. Expected Service, "
            f"EndpointSlice and IngressRoute all present — check "
            f"infra/k8s/overlays/staging/kustomization.yaml lists pihole.yaml."
        )

    def test_prod_renders_nothing_pihole(self) -> None:
        """The actual AC3 assertion: prod must never ship a route it can't serve.

        If `pihole.yaml` drifts back into `base/` (or is added to prod's own
        overlay), this is the only check that will ever fail — no live HTTP
        probe can see it, because pihole.kubelab.live resolves to ace1
        regardless of what prod's Kustomize render contains.
        """
        found = _pihole_objects("prod")
        assert not found, (
            f"Prod render contains pihole objects it can never serve: "
            f"{[(d['kind'], d['metadata']['name']) for d in found]}. "
            f"RPi4 (Pi-hole's backend) is on-demand homelab, never reachable from the "
            f"VPS (ADR-028). Move pihole.yaml back to the staging overlay only."
        )
