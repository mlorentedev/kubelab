"""Neither overlay runs one of our own images on a mutable tag (DELIVERY-010, #1882).

ADR-046's defect #1 was the `:dev` alias on both overlays: one tag, two different digests in staging
and prod, for 78 days. The generator still accepts `dev` and `latest`, giving them
`imagePullPolicy: Always` (`generator_k8s.py:_resolve_pull_policy`), and `common.yaml` keeps
`version: dev` as the dev env's default, so nothing else stops the alias from coming back.

What runs is what kustomize renders, not what a source file says: `base/edge/errors.yaml` still names
`kubelab-errors:dev`, and the base `images:` list overrides it. So this reads the rendered overlays.
Staging tracks `sha-<short>`, prod tracks released semver, and `errors` is env-agnostic semver; a
digest is immutable too. Anything else, including `dev`, `latest` and an `-rc` tag, is refused.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
OVERLAYS = ["staging", "prod"]
OWN = re.compile(r"(^|/)kubelab-[a-z0-9-]+(:|@|$)")
IMMUTABLE = re.compile(r"(@sha256:[0-9a-f]{64}|:sha-[0-9a-f]{7,40}|:\d+\.\d+\.\d+)$")


def _images(node: Any) -> Iterator[str]:
    """Every `image:` value anywhere in a document: containers, initContainers, Jobs, CronJobs."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "image" and isinstance(value, str):
                yield value
            else:
                yield from _images(value)
    elif isinstance(node, list):
        for item in node:
            yield from _images(item)


def _own_images(overlay: str) -> list[str]:
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not on PATH: cannot render the overlay (a skip is CANNOT CHECK, not OK)")
    out = subprocess.run(
        ["kubectl", "kustomize", str(REPO / "infra/k8s/overlays" / overlay)], capture_output=True, encoding="utf-8"
    )
    assert out.returncode == 0, out.stderr
    return [image for doc in yaml.safe_load_all(out.stdout) for image in _images(doc) if OWN.search(image)]


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_every_own_image_is_pinned_to_an_immutable_tag(overlay: str) -> None:
    images = _own_images(overlay)
    # api, web and errors at least: an empty list would pass while checking nothing.
    assert {re.search(r"kubelab-[a-z0-9-]+", i).group(0) for i in images} >= {
        "kubelab-api",
        "kubelab-web",
        "kubelab-errors",
    }, images
    mutable = sorted({i for i in images if not IMMUTABLE.search(i)})
    assert not mutable, f"{overlay} renders our own images on a mutable tag (ADR-046): {mutable}"


@pytest.mark.parametrize(
    ("image", "immutable"),
    [
        ("docker.io/mlorentedev/kubelab-api:sha-9a4a029", True),
        ("docker.io/mlorentedev/kubelab-web:1.16.3", True),
        ("docker.io/mlorentedev/kubelab-api@sha256:" + "a" * 64, True),
        ("docker.io/mlorentedev/kubelab-api:dev", False),
        ("docker.io/mlorentedev/kubelab-api:latest", False),
        ("docker.io/mlorentedev/kubelab-api", False),
        ("docker.io/mlorentedev/kubelab-api:1.4.0-rc.1", False),
    ],
)
def test_the_tag_rule(image: str, immutable: bool) -> None:
    assert OWN.search(image)
    assert bool(IMMUTABLE.search(image)) is immutable
