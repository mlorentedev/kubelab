"""The spoke apiserver URL, derived once instead of three times (#1215).

`argocd.spokes.<env>.node` -> that node's `tailscale_ip` -> `k3s.api_port` was
being computed in three places when this module was written: `Makefile:639` as an
inline `python -c "import yaml"`, the `spoke_servers` default in
`infra/terraform/gcp/variables.tf`, and the drift guard that compares them. Two
of those are declarations of the RESULT and only one goes red when they diverge.

The asymmetry these tests pin down is the one thing about `networking` that
callers keep re-encoding: `vps` sits at the top level and homelab nodes sit under
`nodes`. Every inline copy is another edit #1182 will have to find.
"""

from __future__ import annotations

import pytest

from toolkit.features import argocd_spokes


@pytest.fixture
def config() -> dict:
    """Shaped like common.yaml, both node placements represented."""
    return {
        "k3s": {"api_port": 6443},
        "argocd": {"spokes": {"staging": {"node": "ace1"}, "prod": {"node": "vps"}}},
        "networking": {
            "vps": {"tailscale_ip": "100.64.0.2"},
            "nodes": {"ace1": {"tailscale_ip": "100.64.0.11"}},
        },
    }


class TestApiserverUrl:
    def test_a_homelab_node_resolves_through_the_nodes_map(self, config: dict) -> None:
        assert argocd_spokes.apiserver_url(config, "staging") == "https://100.64.0.11:6443"

    def test_a_cloud_node_resolves_at_the_top_level(self, config: dict) -> None:
        """`vps` is not under `nodes`. A resolver that only looked there would
        work for staging and fail for prod -- the half-working shape that reads
        as "prod is down" rather than "the lookup is wrong"."""
        assert argocd_spokes.apiserver_url(config, "prod") == "https://100.64.0.2:6443"

    def test_all_spokes_resolve_in_one_call(self, config: dict) -> None:
        assert argocd_spokes.apiserver_urls(config) == {
            "staging": "https://100.64.0.11:6443",
            "prod": "https://100.64.0.2:6443",
        }

    def test_the_port_comes_from_the_ssot_not_a_literal(self, config: dict) -> None:
        config["k3s"]["api_port"] = 7443
        assert argocd_spokes.apiserver_url(config, "staging").endswith(":7443")


class TestItFailsLoudlyRatherThanSilently:
    """Each of these returned an empty string or a KeyError from somewhere else
    in the inline form, and the caller interpolated the result regardless."""

    def test_an_unknown_env_names_the_envs_that_do_exist(self, config: dict) -> None:
        with pytest.raises(KeyError) as exc:
            argocd_spokes.apiserver_url(config, "dev")
        assert "staging" in str(exc.value) and "prod" in str(exc.value)

    def test_a_spoke_pointing_at_an_unknown_node_names_the_node(self, config: dict) -> None:
        config["argocd"]["spokes"]["staging"]["node"] = "ghost"
        with pytest.raises(KeyError, match="ghost"):
            argocd_spokes.apiserver_url(config, "staging")

    def test_a_node_without_a_tailscale_ip_is_not_rendered_as_none(self, config: dict) -> None:
        del config["networking"]["nodes"]["ace1"]["tailscale_ip"]
        with pytest.raises(KeyError, match="tailscale_ip"):
            argocd_spokes.apiserver_url(config, "staging")

    def test_a_missing_api_port_is_not_rendered_as_none(self, config: dict) -> None:
        del config["k3s"]["api_port"]
        with pytest.raises(KeyError, match="api_port"):
            argocd_spokes.apiserver_url(config, "staging")


class TestSpokeUrlCLI:
    """`Makefile:639` now calls this instead of its own inline `python -c`.

    Reads the real `common.yaml`, same as the Makefile target does -- the
    thing worth pinning here is the CLI's argument wiring and exit codes, not
    the resolution logic already covered above.
    """

    def test_a_declared_env_prints_the_same_url_the_module_derives(self) -> None:
        import yaml
        from typer.testing import CliRunner

        from toolkit.cli.infra import app
        from toolkit.config.settings import settings

        common = settings.project_root / "infra" / "config" / "values" / "common.yaml"
        expected = argocd_spokes.apiserver_url(yaml.safe_load(common.read_text()), "staging")

        result = CliRunner().invoke(app, ["argo", "spoke-url", "--env", "staging"])

        assert result.exit_code == 0, result.stdout
        assert result.stdout.strip() == expected

    def test_an_unknown_env_exits_nonzero_and_names_it(self) -> None:
        from typer.testing import CliRunner

        from toolkit.cli.infra import app

        result = CliRunner().invoke(app, ["argo", "spoke-url", "--env", "ghost"])

        assert result.exit_code != 0
        assert "ghost" in result.stdout

    def test_missing_env_option_exits_nonzero(self) -> None:
        from typer.testing import CliRunner

        from toolkit.cli.infra import app

        result = CliRunner().invoke(app, ["argo", "spoke-url"])
        assert result.exit_code != 0
