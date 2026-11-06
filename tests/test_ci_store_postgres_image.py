"""The Postgres the API store tests run against in CI is the cluster's (#3117).

The tests exist to prove `ON CONFLICT` and keyset semantics, which can change across
majors, so CI must not keep validating one version while the cluster runs another.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _cluster_images() -> set[str]:
    docs = yaml.safe_load_all((ROOT / "infra/k8s/base/services/postgres.yaml").read_text(encoding="utf-8"))
    found: set[str] = set()
    for doc in docs:
        spec = ((doc or {}).get("spec") or {}).get("template", {}).get("spec", {})
        for c in spec.get("containers", []) + spec.get("initContainers", []):
            if c.get("image", "").startswith("postgres:"):
                found.add(c["image"])
    return found


def _ci_image() -> str:
    text = (ROOT / ".github/workflows/ci-pipeline.yml").read_text(encoding="utf-8")
    images = set(re.findall(r"docker run[^\n]*(?:\\\n[^\n]*)*?\s(postgres:\S+)", text))
    assert len(images) == 1, f"expected one Postgres image in the API store step, found {sorted(images)}"
    return images.pop()


def test_ci_runs_the_store_tests_on_the_clusters_postgres() -> None:
    cluster = _cluster_images()
    assert len(cluster) == 1, f"expected one Postgres image in the cluster manifest, found {sorted(cluster)}"
    assert _ci_image() == cluster.pop()
