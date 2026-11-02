#!/usr/bin/env python3
"""Estimate the bytes a node must fetch to pull a set of images (#2742).

Run on the node by `_includes/image-pull.yml`, before the pull. An image the
node already holds counts 0. For any other, the compressed size of its layers
for the node's architecture, read from the registry without pulling. That is an
upper bound: a layer the node holds through another image is counted too.

Usage: image-pull-estimate.py <uname -m> <image> [<image> ...]
Prints one JSON object: {"bytes": N, "images": [{"image": ..., "bytes": N}, ...]}
"""

from __future__ import annotations

import json
import subprocess
import sys

# `uname -m` (ansible_architecture) to the platform name a manifest list uses.
ARCH = {"x86_64": "amd64", "aarch64": "arm64", "armv7l": "arm"}


def layer_bytes(manifest: dict | list, arch: str) -> int:
    """Compressed layer bytes of a `docker manifest inspect -v` document for one architecture.

    A multi-platform image gives a list with one entry per platform, attestation
    entries included; a single-platform image gives one entry, taken as it is.
    """
    entries = manifest if isinstance(manifest, list) else [manifest]
    for entry in entries:
        platform = entry.get("Descriptor", {}).get("platform", {})
        if len(entries) > 1 and platform.get("architecture") != arch:
            continue
        body = entry.get("SchemaV2Manifest") or entry.get("OCIManifest") or {}
        return sum(layer["size"] for layer in body.get("layers", []))
    raise ValueError(f"no {arch} manifest among {len(entries)} entries")


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def estimate(arch: str, images: list[str], run=_run) -> dict:
    found = []
    for image in images:
        if run(["docker", "image", "inspect", image]).returncode == 0:
            found.append({"image": image, "bytes": 0})
            continue
        manifest = run(["docker", "manifest", "inspect", "-v", image])
        if manifest.returncode != 0:
            raise SystemExit(f"cannot read the manifest of {image}: {manifest.stderr.strip()}")
        found.append({"image": image, "bytes": layer_bytes(json.loads(manifest.stdout), arch)})
    return {"bytes": sum(item["bytes"] for item in found), "images": found}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 64
    print(json.dumps(estimate(ARCH.get(argv[0], argv[0]), argv[1:])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
