"""Did the Sealed Secrets controller decrypt the probe with the operator's key? (RES-HOST-001 A6, AC8).

The probe is a `SealedSecret` sealed offline against the certificate held in SOPS, committed with the
sha256 of its plaintext in an annotation. A controller running a key it minted itself cannot decrypt it,
so the Secret never appears; one running the operator's key produces a value with the committed digest.

This reads a decrypted credential, so it prints a verdict and nothing derived from the value: the caller
gets `True` or `False`, and an error names a cause that carries no value (kubectl's own stderr).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

PROBE_MANIFEST = "infra/k8s/cluster/sealed-secrets/probe.yaml"
DIGEST_ANNOTATION = "kubelab.live/plaintext-sha256"
_SHA256 = re.compile(r"[0-9a-f]{64}")

Runner = Callable[..., Any]


class ProbeError(Exception):
    """The probe cannot be checked: the file is unusable, or the cluster could not be read."""


@dataclass(frozen=True)
class Probe:
    namespace: str
    name: str
    key: str
    expected_sha256: str


def load_probe(path: Path) -> Probe:
    """Read the probe's identity and expected digest from its committed `SealedSecret`."""
    if not path.is_file():
        raise ProbeError(f"the probe SealedSecret is not committed yet: {path}")
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if doc.get("kind") != "SealedSecret":
        raise ProbeError(f"{path} is not a SealedSecret")
    meta = doc.get("metadata") or {}
    digest = (meta.get("annotations") or {}).get(DIGEST_ANNOTATION, "")
    if not _SHA256.fullmatch(str(digest)):
        raise ProbeError(f"{path} carries no lowercase sha256 in the {DIGEST_ANNOTATION} annotation")
    keys = list((doc.get("spec") or {}).get("encryptedData") or {})
    if len(keys) != 1:
        raise ProbeError(f"{path} must seal exactly one value, found {len(keys)}")
    return Probe(meta["namespace"], meta["name"], keys[0], str(digest))


def _decrypted_sha256(probe: Probe, kubeconfig: str, run: Runner) -> str:
    """sha256 of the value the controller wrote; empty when the Secret exists without the probe's key.

    Raises ProbeError when there is no such Secret: on a fresh apply the controller has not had time
    to unseal yet, and that is no evidence about its key.
    """
    result = run(
        [
            "kubectl",
            "--kubeconfig",
            kubeconfig,
            "-n",
            probe.namespace,
            "get",
            "secret",
            probe.name,
            "--ignore-not-found",
            "-o",
            "json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise ProbeError(f"kubectl could not read {probe.namespace}/{probe.name}: {(result.stderr or '').strip()}")
    if not result.stdout.strip():
        raise ProbeError(
            f"the controller has not unsealed the probe yet ({probe.namespace}/{probe.name} does not exist): "
            "retry, or check the controller is running"
        )
    encoded = (json.loads(result.stdout).get("data") or {}).get(probe.key)
    return hashlib.sha256(base64.b64decode(encoded)).hexdigest() if encoded else ""


def verify(probe: Probe, kubeconfig: str, run: Runner | None = None) -> bool:
    """True when the controller decrypted the probe to the committed digest, False when it made another value.

    Raises ProbeError when the Secret does not exist yet or the cluster cannot be read.
    """
    actual = _decrypted_sha256(probe, kubeconfig, run or subprocess.run)
    return hmac.compare_digest(actual, probe.expected_sha256)
