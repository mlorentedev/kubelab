"""The hub->spoke probes must name the hub that actually reconciles that spoke.

`preserved_flows` hardcoded `aws1` as the source of both hub->spoke flows. That
was true while one hub existed. GCP-001 makes two coexist: `gcp1` takes staging
first, `aws1` keeps prod, and prod moves later (spec design decision 1,
"additive-then-subtractive, never a swap").

A probe that keeps asking `aws1` about staging measures a path nobody uses. It
would stay green while the real staging path -- gcp1 to ace1 -- was broken, and
it would go red the moment aws1 legitimately stops reaching a spoke it no longer
owns. Both directions are wrong, and neither is loud.

Which hub owns which spoke is already declared: `networking.gcp.managed_spokes`.
Deriving the source from it means the cutover moves the probe with no edit here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

COMMON = Path(__file__).resolve().parent.parent / "infra/config/values/common.yaml"


@pytest.fixture
def net() -> dict[str, Any]:
    return yaml.safe_load(COMMON.read_text())["networking"]


def _flow(flows: list, needle: str):
    found = [f for f in flows if needle in f.name]
    assert found, f"no flow named like {needle!r}; the probe's flow set changed shape"
    return found[0]


class TestTheSourceFollowsTheSSOT:
    def test_staging_is_probed_from_the_hub_that_manages_it(self, net: dict[str, Any]) -> None:
        """`managed_spokes` says gcp1 owns staging, so the probe must ask gcp1."""
        from toolkit.scripts.headscale_probe import preserved_flows

        managed = net["gcp"].get("managed_spokes", [])
        assert "staging" in managed, "the SSOT no longer gives staging to the GCP hub"
        assert _flow(preserved_flows(net), "staging").src == net["gcp"]["hostname"]

    def test_prod_is_still_probed_from_the_aws_hub(self, net: dict[str, Any]) -> None:
        """Additive, never a swap: aws1 reconciles prod until AC6 retires it."""
        from toolkit.scripts.headscale_probe import preserved_flows

        assert "prod" not in net["gcp"].get("managed_spokes", [])
        assert _flow(preserved_flows(net), "prod").src == net["aws"]["hostname"]

    def test_moving_prod_moves_the_probe_with_no_code_edit(self, net: dict[str, Any]) -> None:
        """The cutover is adding "prod" to managed_spokes. The probe must follow
        that on its own, or it becomes one more site to remember."""
        from toolkit.scripts.headscale_probe import preserved_flows

        after = {**net, "gcp": {**net["gcp"], "managed_spokes": ["staging", "prod"]}}
        assert _flow(preserved_flows(after), "prod").src == net["gcp"]["hostname"]

    def test_an_empty_managed_spokes_leaves_everything_on_aws(self, net: dict[str, Any]) -> None:
        """The pre-migration world, which must still be expressible."""
        from toolkit.scripts.headscale_probe import preserved_flows

        before = {**net, "gcp": {**net["gcp"], "managed_spokes": []}}
        flows = preserved_flows(before)
        assert _flow(flows, "prod").src == net["aws"]["hostname"]
        assert _flow(flows, "staging").src == net["aws"]["hostname"]


def test_no_hub_hostname_is_written_as_a_literal() -> None:
    """Over the AST, so the docstring explaining the change cannot fail it."""
    import ast

    src = (Path(__file__).resolve().parent.parent / "toolkit/scripts/headscale_probe.py").read_text()
    tree = ast.parse(src)
    docstrings = {
        id(n.body[0].value)
        for n in ast.walk(tree)
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef))
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
    }
    literals = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and n.value in ("aws1", "gcp1")
        and id(n) not in docstrings
    ]
    assert not literals, f"a hub hostname is hardcoded again: {literals}"
