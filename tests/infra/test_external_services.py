"""Infrastructure: the external-service pattern, checked against the live cluster.

Services labelled `kubelab.live/location: external` are fronted by K3s Traefik but
served from somewhere else — another node over Tailscale, or bare metal. The
mechanism is a `Service` with **no selector** plus a hand-written `EndpointSlice`
naming the backend's address ("Services without selectors", upstream's own term).

Two invariants hold that shape together, and neither is visible in a Kustomize
render — they are properties of the live object, not of the manifest:

1. The Service must have **no selector**. If it has one, the endpoints controller
   starts managing a slice of its own alongside the hand-written one.
2. There must be exactly **one** EndpointSlice carrying addresses. Two means two
   backends, and Traefik load-balances between them.

Why this file exists: on 2026-08-14 the Gitea cutover (ADR-061) hit exactly this.
The manifest was correct and produced a selector-less Service on a fresh cluster,
but the *live* object was a conversion of one that already had a selector, and
`kubectl apply` does not remove a field the new manifest merely omits — omitting
is not deleting. The result was one domain round-robining between two different
Gitea instances with two different databases: a push landing in one and a read
served from the other. Every render, unit test, sync check and e2e run was green
throughout, because both backends answered 200.

Deliberately an infra test rather than a static one: no manifest inspection could
have caught it, since the manifests were right. Only the cluster knows.
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

pytestmark = pytest.mark.infra

_KUBECONFIG_PATTERN = "~/.kube/kubelab-{env}-config"
_NAMESPACE = "kubelab"
_EXTERNAL_SELECTOR = "kubelab.live/location=external"


def _kubeconfig(env: str) -> str:
    path = os.path.expanduser(_KUBECONFIG_PATTERN.format(env=env))
    if os.path.exists(path):
        return path
    return os.environ.get("KUBECONFIG", path)


def _kubectl_json(args: str, env: str, timeout: int = 20) -> dict:
    result = subprocess.run(
        f"kubectl --kubeconfig {_kubeconfig(env)} -n {_NAMESPACE} {args} -o json",
        shell=True,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        pytest.skip(f"cluster unreachable: {result.stderr.strip()[:120]}")
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def external_services(env: str) -> list[dict]:
    """Live Services carrying the external-location label."""
    if not os.path.exists(_kubeconfig(env)):
        pytest.skip(f"no kubeconfig for {env}")
    items = _kubectl_json(f"get svc -l {_EXTERNAL_SELECTOR}", env).get("items", [])
    if not items:
        # Not a skip. Every environment has at least one of these, so an empty
        # result means the label query stopped matching — which would make every
        # assertion below pass by testing nothing.
        pytest.fail(
            f"no Services matched {_EXTERNAL_SELECTOR} in {env}. The label convention "
            "changed or the manifests lost it; this guard is now blind."
        )
    return items


def test_external_services_have_no_selector(external_services: list[dict]) -> None:
    """A selector on an external Service means the cluster is also picking backends."""
    offenders = {
        svc["metadata"]["name"]: svc["spec"]["selector"]
        for svc in external_services
        if svc.get("spec", {}).get("selector")
    }
    assert not offenders, (
        "External Services must have no selector — with one, the endpoints controller "
        "manages a second EndpointSlice beside the hand-written one and traffic is split "
        f"between backends: {offenders}. Note `kubectl apply` will NOT remove a selector "
        "an object already has; it needs an explicit `selector: null` patch."
    )


def test_external_services_have_exactly_one_populated_endpointslice(
    external_services: list[dict], env: str
) -> None:
    """Two slices with addresses means two backends answering one name."""
    problems: list[str] = []
    for svc in external_services:
        name = svc["metadata"]["name"]
        slices = _kubectl_json(
            f"get endpointslice -l kubernetes.io/service-name={name}", env
        ).get("items", [])

        populated = {
            s["metadata"]["name"]: [
                addr for ep in (s.get("endpoints") or []) for addr in (ep.get("addresses") or [])
            ]
            for s in slices
        }
        populated = {n: a for n, a in populated.items() if a}

        if len(populated) != 1:
            problems.append(f"{name}: expected 1 populated EndpointSlice, found {len(populated)} — {populated}")

    assert not problems, (
        "External Services must resolve to exactly one backend:\n"
        + "\n".join(problems)
        + "\nTwo populated slices means Traefik round-robins between them, which reads "
        "as intermittent, not as an outage."
    )
