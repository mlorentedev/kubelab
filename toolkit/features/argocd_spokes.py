"""One definition of a spoke's apiserver URL.

`make register-spoke` needs it, the GCP hub's Terraform needs it, and the drift
guard that compares the two needs it. Before this module the derivation existed
three times -- `Makefile:639` as an inline `python -c "import yaml"`, the
`spoke_servers` default in `infra/terraform/gcp/variables.tf`, and the guard --
of which only the guard goes red when they disagree (#1215).

The rule is `argocd.spokes.<env>.node` -> that node's `tailscale_ip` ->
`k3s.api_port`, and the awkward part is the node lookup: `vps` sits at the top
level of `networking` while homelab nodes sit under `nodes`. That asymmetry is
#1182. It is NOT smoothed here -- GCP-001 exists to measure what a provider
change costs and reshaping `networking` mid-measurement destroys the reading --
but it is now encoded ONCE, so #1182 has one edit to make instead of three.

Every failure raises rather than returning a default. The inline form yielded an
empty string or a `KeyError` from an unrelated frame, and the caller interpolated
it either way: `https://:6443` is a URL, it just is not a spoke.
"""

from __future__ import annotations

from typing import Any


def spoke_envs(config: dict[str, Any]) -> list[str]:
    """Every environment `argocd.spokes` declares, sorted."""
    return sorted(config.get("argocd", {}).get("spokes", {}))


def node_tailscale_ip(config: dict[str, Any], node: str) -> str:
    """A node's Tailscale address, wherever `networking` happens to keep it.

    THE ONLY place the cloud/homelab asymmetry is encoded (#1182).
    """
    networking = config.get("networking", {})
    entry = networking.get(node)
    if not isinstance(entry, dict):
        entry = networking.get("nodes", {}).get(node)
    if not isinstance(entry, dict):
        known = sorted({*networking.get("nodes", {}), *(k for k, v in networking.items() if isinstance(v, dict))})
        raise KeyError(f"networking has no node {node!r}; it knows {known}")
    ip = entry.get("tailscale_ip")
    if not ip:
        raise KeyError(f"networking entry for {node!r} has no tailscale_ip")
    return str(ip)


def apiserver_url(config: dict[str, Any], env: str) -> str:
    """The K3s apiserver URL for one spoke."""
    spokes = config.get("argocd", {}).get("spokes", {})
    if env not in spokes:
        raise KeyError(f"argocd.spokes has no {env!r}; it declares {spoke_envs(config)}")
    node = spokes[env].get("node")
    if not node:
        raise KeyError(f"argocd.spokes.{env} has no node")
    port = config.get("k3s", {}).get("api_port")
    if not port:
        raise KeyError("k3s.api_port is missing; the spoke URL cannot be derived from a literal")
    return f"https://{node_tailscale_ip(config, str(node))}:{port}"


def apiserver_urls(config: dict[str, Any]) -> dict[str, str]:
    """Every declared spoke's apiserver URL, keyed by environment."""
    return {env: apiserver_url(config, env) for env in spoke_envs(config)}
