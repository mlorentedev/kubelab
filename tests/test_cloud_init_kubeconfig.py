"""cloud-init must tell helm where the cluster is.

Finding F1 says the hub's cloud-init installs Argo CD on every boot, because a
MIG recreates rather than restarts and a hub that stops at "K3s ready" never
comes back. #1217 recorded F1 as closed in code.

It was not. On the first real boot:

    Error: Kubernetes cluster unreachable: Get "http://localhost:8080/version":
    dial tcp [::1]:8080: connect: connection refused

`localhost:8080` is helm's fallback when it finds no kubeconfig. `kubectl` works
in the same script without one because K3s ships a wrapper that defaults to
`/etc/rancher/k3s/k3s.yaml`; helm has no such convention, and nothing in the
script exported it.

So the namespace was created, K3s came up, and Argo CD was never installed --
cloud-init exiting with `status: error` on a node that looked healthy from the
MIG's point of view.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CLOUD_INIT = Path(__file__).resolve().parent.parent / "infra/terraform/gcp/cloud-init.yml"
K3S_KUBECONFIG = "/etc/rancher/k3s/k3s.yaml"


@pytest.fixture(scope="module")
def script() -> str:
    """The runcmd body with comment lines removed.

    Stripped because the first version of this file did not, and its own
    "exported before the first kubectl" assertion failed on the COMMENT
    explaining why the export exists. Same defect as lesson-363: a text scan
    matching the prose that documents the thing, and failing a file that is
    correct for describing itself.
    """
    return "\n".join(line for line in CLOUD_INIT.read_text().splitlines() if not line.lstrip().startswith("#"))


def test_kubeconfig_is_exported(script: str) -> None:
    """Without it, helm silently targets localhost:8080 and fails."""
    assert re.search(rf"export KUBECONFIG={re.escape(K3S_KUBECONFIG)}", script), (
        "cloud-init never exports KUBECONFIG. kubectl survives that because K3s "
        "wraps it; helm does not, and falls back to localhost:8080."
    )


def test_it_is_exported_before_helm_runs(script: str) -> None:
    """Setting it after the install is the same as not setting it."""
    export = script.find("export KUBECONFIG=")
    helm = script.find("helm upgrade")
    assert export != -1 and helm != -1
    assert export < helm, "KUBECONFIG is exported after helm has already run"


def test_it_is_exported_before_the_first_kubectl_too(script: str) -> None:
    """kubectl works without it today only by K3s's convenience wrapper.

    Relying on that leaves the script correct by accident: the same command run
    through a different kubectl, or as a different user, addresses nothing.
    """
    export = script.find("export KUBECONFIG=")
    kubectl = script.find("kubectl ")
    assert export != -1 and kubectl != -1
    assert export < kubectl, "the first kubectl runs before KUBECONFIG is set"


def test_the_path_is_k3s_own_kubeconfig(script: str) -> None:
    """`--write-kubeconfig-mode=644` in the K3s install is what makes this file
    readable; pointing elsewhere would be a second declaration of that choice."""
    assert K3S_KUBECONFIG in script
    assert "--write-kubeconfig-mode=644" in script
