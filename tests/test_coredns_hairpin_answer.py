"""The hairpin's regex rewrites also rewrite the answer back to the queried name.

`rewrite name regex (.*)\\.kubelab\\.live traefik.kube-system.svc.cluster.local`
without an `answer` clause returns an A record OWNED by the rewritten name. musl
(Alpine: Grafana, n8n, Authelia) accepts that; glibc drops an answer whose owner is
not the name it asked for, so every Debian/Ubuntu pod calling `*.kubelab.live`
in-cluster got "Name or service not known". Found on 2026-09-27 when the PR-Agent
server (Debian) could not reach `gitea.kubelab.live` (TOOL-080). `answer auto`
(CoreDNS >= 1.10; the cluster runs 1.14.1) reverses the name in the response.
"""

from __future__ import annotations

from pathlib import Path

import yaml

MANIFEST = Path(__file__).resolve().parent.parent / "infra/k8s/base/edge/coredns-custom.yaml"


def _rewrites() -> list[str]:
    doc = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    server = doc["data"]["kubelab-hairpin.server"]
    return [line.strip() for line in server.splitlines() if line.strip().startswith("rewrite name regex")]


def test_the_hairpin_declares_its_regex_rewrites() -> None:
    # Guards the test below from passing vacuously if the block is reshaped.
    assert len(_rewrites()) >= 2


def test_every_regex_rewrite_also_rewrites_the_answer() -> None:
    missing = [line for line in _rewrites() if not line.endswith("answer auto")]
    assert not missing, f"regex rewrite without `answer auto` (glibc clients drop the answer): {missing}"
