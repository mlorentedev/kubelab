"""Every third-party image the overlays render carries a version, never `latest`.

`imagePullPolicy` defaults to `Always` for `:latest`, so an unpinned image
upgrades itself on any pod restart, with no PR and no review. Measured
2026-09-27: Grafana rendered `grafana/grafana-oss:latest` in both overlays
while the identity model depended on 13.0.2's behaviour (lessons 457, 461,
463). Nothing flagged it: `sync_k8s_images.py` only syncs the paths it lists,
and Grafana was not one of them.

Images we build (`docker.io/mlorentedev/*`) are out of scope here: ADR-046's
promotion owns their tags.
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
OURS = "docker.io/mlorentedev/"
_IMAGE = re.compile(r"^\s+image:\s*[\"']?(?P<ref>[^\s\"']+)", re.MULTILINE)


def _rendered_images(overlay: str) -> set[str]:
    out = subprocess.run(
        ["kubectl", "kustomize", str(REPO / "infra/k8s/overlays" / overlay)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {m.group("ref") for m in _IMAGE.finditer(out)}


def _tag(ref: str) -> str:
    if "@sha256:" in ref:
        return ref.split("@", 1)[1]
    last = ref.rsplit("/", 1)[-1]
    return last.split(":", 1)[1] if ":" in last else ""


@pytest.mark.parametrize("overlay", ["staging", "prod"])
def test_third_party_images_are_pinned(overlay: str) -> None:
    if shutil.which("kubectl") is None:
        # In CI a missing kubectl is a failure: a runner-image change would
        # otherwise turn this guard into a quiet skip that still reports green.
        if os.environ.get("CI"):
            pytest.fail("kubectl not on PATH in CI: third-party image pins went unchecked")
        pytest.skip("kubectl not on PATH: cannot render the overlays (a skip is CANNOT CHECK, not OK)")
    images = _rendered_images(overlay)
    third_party = {ref for ref in images if not ref.startswith(OURS)}
    assert len(third_party) > 5, f"the scan found only {sorted(third_party)}; the render or the regex drifted"
    unpinned = sorted(ref for ref in third_party if _tag(ref) in ("", "latest"))
    assert not unpinned, (
        f"{overlay} renders unpinned third-party images: {unpinned}. Pin them in "
        f"common.yaml and list the path in toolkit/scripts/sync_k8s_images.py."
    )
