"""A rolling pod keeps serving until Traefik has dropped its endpoint (DELIVERY-012).

SIGTERM and endpoint removal start together, so without a delay the process can
stop while Traefik still routes to it. Measured on staging at 50 requests/s: a
`web` rollout lost 0.34% of its requests, with a 5-second maximum (#2977). The
test reads the committed Deployments, which are what Argo CD applies.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
# Traefik's Kubernetes provider throttles config reloads for 2 seconds, then needs
# to load the new config.
MIN_DRAIN_SECONDS = 5
# Kubernetes' default terminationGracePeriodSeconds, which the sleep spends from.
GRACE_SECONDS = 30


def _deployments(env: str) -> list[dict]:
    path = REPO / f"infra/k8s/overlays/{env}/generated/deployments.yaml"
    docs = yaml.safe_load_all(path.read_text(encoding="utf-8"))
    return [d for d in docs if d and d["kind"] == "Deployment"]


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_every_generated_app_drains_before_it_stops(env: str) -> None:
    deployments = _deployments(env)
    assert deployments, f"no generated Deployments in {env}"
    for deployment in deployments:
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        seconds = container["lifecycle"]["preStop"]["sleep"]["seconds"]
        assert MIN_DRAIN_SECONDS <= seconds < GRACE_SECONDS, deployment["metadata"]["name"]
