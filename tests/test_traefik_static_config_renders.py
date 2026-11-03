"""The VPS Traefik static config renders for every env from public values (#3045).

#2926 moved the ACME resolvers to `networking.public_resolvers` and left
`traefik.yml.j2` reading the removed `DNS_RESOLVER_1`, so `config generate` failed
for staging and prod with nothing in CI rendering that template. The renderer is
strict, so an undefined name fails here too.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from toolkit.core.templating import create_renderer
from toolkit.features.generator_traefik import TraefikGenerator

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_the_static_config_renders_with_the_pinned_resolvers(env: str, tmp_path: Path) -> None:
    context = TraefikGenerator()._build_context(env)
    out = tmp_path / "traefik.yml"
    assert create_renderer(REPO / "edge/traefik/templates").render_template("traefik.yml.j2", out, context)
    resolvers = yaml.safe_load(out.read_text(encoding="utf-8"))
    acme = next(iter(resolvers["certificatesResolvers"].values()))["acme"]
    common = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text(encoding="utf-8"))
    assert acme["dnsChallenge"]["resolvers"] == [f"{ip}:53" for ip in common["networking"]["public_resolvers"]]
