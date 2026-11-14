"""The hairpin's staging server blocks are rendered from ``networking.staging_zones`` (IDP-053 D8, AC13).

A product's staging zone is one line in ``common.yaml``; the pod-side forward block that makes it
resolvable in-cluster follows from the list instead of a second hand edit. The prod rewrite blocks
stay hand-written until a product declares prod.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from toolkit.features import edge_dns
from toolkit.features.k8s_render import (
    BootstrapEntry,
    RenderError,
    render_and_apply,
    render_staging_zones,
)

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "infra/k8s/base/edge/coredns-custom.yaml"
COMMON = ROOT / "infra/config/values/common.yaml"
ZONES = ["staging.kubelab.live", "staging.mlorente.dev"]
#: Addresses come from their single source, never a literal (CLAUDE.md: no hardcoded IPs in tests).
#: The stub resolver answers with rpi4's own address, as the real resolver would.
RPI4_IP = yaml.safe_load(COMMON.read_text(encoding="utf-8"))["networking"]["nodes"]["rpi4"]["tailscale_ip"]
#: K3s's cluster DNS has no key in ``common.yaml``; the manifest is its one home, so it is read from
#: the prod blocks' own ``forward`` line, which these tests assert the staging render leaves alone.
CLUSTER_DNS = re.search(
    r"traefik\.kube-system\.svc\.cluster\.local answer auto\n\s+forward \. (\S+)",
    MANIFEST.read_text(encoding="utf-8"),
).group(1)  # type: ignore[union-attr]

STAGING_BLOCKS = """\
staging.kubelab.live:53 {
  forward . RESOLVE_RPI4_TAILSCALE_IP
}
staging.mlorente.dev:53 {
  forward . RESOLVE_RPI4_TAILSCALE_IP
}
"""
PROD_BLOCKS = """\
kubelab.live:53 {
  rewrite name regex (.*)\\.kubelab\\.live traefik.kube-system.svc.cluster.local answer auto
  forward . CLUSTER_DNS
}
mlorente.dev:53 {
  rewrite name regex (.*)\\.mlorente\\.dev traefik.kube-system.svc.cluster.local answer auto
  forward . CLUSTER_DNS
}
"""
PROD_BLOCKS = PROD_BLOCKS.replace("CLUSTER_DNS", CLUSTER_DNS)
#: The committed hairpin before the staging blocks were templated, byte for byte.
TODAYS_SERVER = STAGING_BLOCKS + PROD_BLOCKS
THIRD_BLOCK = "staging.example-product.test:53 {\n  forward . RESOLVE_RPI4_TAILSCALE_IP\n}\n"


def _server(text: str) -> str:
    return str(yaml.safe_load(text)["data"]["kubelab-hairpin.server"])


def _committed() -> str:
    return MANIFEST.read_text(encoding="utf-8")


def test_todays_two_zones_render_todays_two_blocks_byte_for_byte() -> None:
    assert _server(render_staging_zones(_committed(), ZONES)) == TODAYS_SERVER


def test_the_committed_zone_list_renders_a_forward_block_per_zone() -> None:
    """Follows the derived `edge.json` as zones are added: it names no zone of its own (EDGE-001)."""
    zones = edge_dns.staging_zones()

    assert set(ZONES) <= set(zones)
    server = _server(render_staging_zones(_committed(), zones))
    assert [line for line in server.splitlines() if line.endswith(":53 {")][: len(zones)] == [
        f"{zone}:53 {{" for zone in zones
    ]


def test_a_third_zone_yields_a_third_forward_block() -> None:
    server = _server(render_staging_zones(_committed(), [*ZONES, "staging.example-product.test"]))

    assert server == STAGING_BLOCKS + THIRD_BLOCK + PROD_BLOCKS


@pytest.mark.parametrize(
    "zone",
    [
        "Staging.example.test",
        "staging.Example.test",
        "staging.example.Test",
        "staging.examplE.test",
        "staging",
        "staging.example.test.",
        "staging.exa mple.test",
        "-a.example.test",
        "staging-.example.test",
        "",
    ],
)
def test_a_zone_that_is_not_a_lowercase_fqdn_is_refused(zone: str) -> None:
    with pytest.raises(RenderError, match="lowercase FQDN"):
        render_staging_zones(_committed(), [*ZONES, zone])


def test_a_manifest_without_the_marker_is_refused() -> None:
    """A reshaped manifest must not silently apply with no staging forwards."""
    with pytest.raises(RenderError, match="STAGING_ZONE_BLOCKS"):
        render_staging_zones("data:\n  a: b\n", ZONES)


def test_no_zones_is_refused() -> None:
    with pytest.raises(RenderError):
        render_staging_zones(_committed(), [])


def _entry(optional: bool) -> BootstrapEntry:
    return BootstrapEntry(
        name="coredns-custom",
        namespace="kube-system",
        manifest="infra/k8s/base/edge/coredns-custom.yaml",
        optional=optional,
        render={"RESOLVE_RPI4_TAILSCALE_IP": "rpi4.kubelab.internal"},
    )


class _Kubectl:
    def __init__(self) -> None:
        self.manifests: list[str] = []

    def __call__(self, cmd: list[str], *, input: str, **_: object) -> object:  # noqa: A002
        self.manifests.append(input)
        return type("Done", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()


def test_the_applied_manifest_carries_every_zone_and_the_resolved_ip() -> None:
    kubectl = _Kubectl()

    assert render_and_apply(
        _entry(optional=True),
        kubeconfig="k",
        project_root=ROOT,
        staging_zones=[*ZONES, "staging.example-product.test"],
        resolver=lambda host: RPI4_IP,
        runner=kubectl,
    )
    server = _server(kubectl.manifests[-1])
    assert f"staging.example-product.test:53 {{\n  forward . {RPI4_IP}\n}}\n" in server
    assert "RESOLVE_" not in server and "STAGING_ZONE_BLOCKS" not in server


@pytest.mark.parametrize("zones", [["Bad.Zone"], None])
def test_a_bad_or_missing_zone_list_is_a_hard_failure_even_for_an_optional_entry(zones: list[str] | None) -> None:
    """`optional` skips a node that is off; it must not also skip a config error."""
    kubectl = _Kubectl()

    assert not render_and_apply(
        _entry(optional=True),
        kubeconfig="k",
        project_root=ROOT,
        staging_zones=zones,
        resolver=lambda host: RPI4_IP,
        runner=kubectl,
    )
    assert kubectl.manifests == []


def test_the_cluster_bootstrap_hands_the_committed_zone_list_to_the_hairpin(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real boundary: `k8s deploy`'s bootstrap step reads `common.yaml` and the applied hairpin carries it."""
    from toolkit.cli import infra

    kubectl = _Kubectl()
    real = infra.render_and_apply
    monkeypatch.setattr(
        infra,
        "render_and_apply",
        lambda entry, **kw: real(entry, **{**kw, "resolver": lambda host: RPI4_IP, "runner": kubectl}),
    )

    assert infra._apply_cluster_bootstrap("kubeconfig", dry_run=True)

    hairpin = next(m for m in kubectl.manifests if "kubelab-hairpin.server" in m)
    zones = edge_dns.staging_zones()
    assert zones, "no zone listed: nothing was checked"
    for zone in zones:
        assert f"{zone}:53 {{\n  forward . {RPI4_IP}\n}}\n" in _server(hairpin)
