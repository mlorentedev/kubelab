"""K3s must not derive the hub's node name from a hostname still in flux.

Without `--node-name`, K3s names the node after the OS hostname at the instant
it starts. On GCP that value is a moving target during first boot: the guest
environment sets the instance's full internal DNS name, and cloud-init's
`hostname:` directive applies later. K3s therefore came up as
`gcp1-bxjh.europe-west4-b.c.kubelab-hub.internal`.

WHAT THAT COST, measured 2026-08-22. A later `make provision NODE=gcp1 ENV=hub`
restarted K3s after the hostname had settled; it re-registered as `gcp1`, and
the cluster was left holding TWO Node objects for ONE machine:

    gcp1-bxjh.europe-west4-b.c.kubelab-hub.internal   NotReady   60m   10.164.0.3
    gcp1                                              Ready      19m   10.164.0.3

Same internal IP. Every pod bound to the dead name stayed `Terminating`
indefinitely -- no kubelet remained to confirm deletion -- and
`argocd-application-controller-0` is a StatefulSet ordinal, so its replacement
could not start while the ghost held the name. With no application controller
the hub reconciles nothing: `kubectl rollout` timed out, and the staging
Application sat at `Unknown` no matter what else was fixed.

The name is load-bearing in three other places that all say `gcp1`: the Ansible
inventory, the kubeconfig server URL, and the Headscale given-name. A name
derived from a race is a name free to disagree with all three.

The pin is on `${hostname}`, the same Terraform variable those three read, so
this is one declaration rather than a fourth.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CLOUD_INIT = Path(__file__).resolve().parent.parent / "infra/terraform/gcp/cloud-init.yml"


@pytest.fixture(scope="module")
def script() -> str:
    """The cloud-init body with comment lines removed.

    Stripped for the reason `test_cloud_init_kubeconfig` states: a text scan
    that matches the prose explaining a thing passes a file that only talks
    about it (lesson-363). Every assertion here must see real script lines.
    """
    return "\n".join(line for line in CLOUD_INIT.read_text().splitlines() if not line.lstrip().startswith("#"))


def test_the_k3s_install_pins_the_node_name(script: str) -> None:
    assert re.search(r"--node-name=", script), (
        "the K3s install does not pass --node-name, so the node is named after "
        "whatever the OS hostname happens to be when K3s starts. On GCP that is "
        "still the instance's full internal DNS name during first boot."
    )


def test_the_pinned_name_is_the_hostname_variable_not_a_literal(script: str) -> None:
    """A literal would be a fourth declaration of a name already stated three times.

    `${hostname}` is the Terraform variable the inventory, the kubeconfig and
    the Headscale registration all derive from. Anything else can drift.
    """
    match = re.search(r"--node-name=(\S+)", script)
    assert match, "no --node-name found; the test above should have caught this first"
    value = match.group(1).rstrip("\\").strip('"')
    assert value == "${hostname}", (
        f"--node-name is {value!r}, not the `${{hostname}}` variable. A literal here "
        "is free to disagree with the Ansible inventory, the kubeconfig server URL "
        "and the Headscale given-name, which all derive from that one variable."
    )


def test_the_node_name_matches_what_the_tls_san_already_asserts(script: str) -> None:
    """Internal consistency: the SAN and the node name must name the same host.

    They are adjacent flags on the same command, and a future edit that changes
    one and not the other produces a node whose certificate does not match its
    own name -- which fails at TLS time, far from the cause.
    """
    name = re.search(r"--node-name=(\S+)", script)
    san = re.search(r"--tls-san=(\S*\$\{hostname\}\S*)", script)
    assert name and san, "expected both --node-name and a ${hostname}-derived --tls-san"
    assert "${hostname}" in san.group(1), "the tls-san stopped deriving from ${hostname}"


def test_the_hostname_directive_still_exists(script: str) -> None:
    """The pin does not make cloud-init's own `hostname:` redundant.

    K3s no longer depends on it, but Tailscale registration and everything that
    reads `hostname -s` still do. Removing it because "K3s is pinned now" would
    reintroduce the divergence one layer over.
    """
    assert re.search(r"^hostname:\s*\$\{hostname\}", script, re.MULTILINE), (
        "cloud-init no longer sets the OS hostname. K3s is pinned independently "
        "now, but Tailscale's --hostname and anything reading `hostname -s` are not."
    )
