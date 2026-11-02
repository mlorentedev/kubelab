"""The load test stays in staging by construction and judges itself by declared rules (OPS-054).

The refusals are what make it safe to run unattended, and classify/knee are what make
its figure quotable: a step the limiter or the generator stopped must never read as
the service's capacity. The k6 metrics are the shape k6 2.3.0 printed on staging.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest
import yaml

from toolkit.features import load_test as lt

REPO = pathlib.Path(__file__).resolve().parents[1]
ROUTE = REPO / lt.ROUTE_MANIFEST


def _values(api: str, web: str) -> dict:
    return {
        "apps": {"platform": {"api": {"domain": api}, "web": {"domain": web}}},
        "load_test": {"target_node": "ace1", "generator_node": "ace2"},
        "networking": {"nodes": {"ace1": {"lan_ip": "10.0.0.2"}}, "vps": {"public_ip": "1.2.3.4", "tailscale_ip": "5.6.7.8"}},
    }


STAGING = _values("api.staging.kubelab.live", "staging.mlorente.dev")
PROD = _values("api.kubelab.live", "mlorente.dev")


def _step(rate: int = 100, **over: float) -> dict:
    return {"rate": rate, "status_429": 0, "error_rate": 0.0, "p95_ms": 10.0, "achieved_rps": float(rate), "generator_cpu": 10.0, "vus_peak": 7, **over}


class TestStaysInStaging:
    @pytest.mark.parametrize("env", ["prod", "dev", "", "PROD", "staging "])
    def test_any_env_but_staging_is_refused(self, env: str) -> None:
        with pytest.raises(lt.LoadTestRefused):
            lt.refuse_unless_staging(env)

    def test_the_declared_staging_hosts_pass(self) -> None:
        assert [t.host for t in lt.build_targets(STAGING, PROD)] == ["api.staging.kubelab.live", "staging.mlorente.dev"]

    @pytest.mark.parametrize("api", ["api.kubelab.live", "kubelab.live", "stagingkubelab.live", "api.notstaging.kubelab.live"])
    def test_a_host_that_is_not_a_staging_name_is_refused(self, api: str) -> None:
        with pytest.raises(lt.LoadTestRefused):
            lt.build_targets(_values(api, "staging.mlorente.dev"), PROD)

    def test_a_staging_shaped_host_prod_also_declares_is_refused(self) -> None:
        with pytest.raises(lt.LoadTestRefused):
            lt.build_targets(STAGING, _values("api.staging.kubelab.live", "mlorente.dev"))

    @pytest.mark.parametrize("address", ["1.2.3.4", "5.6.7.8"])
    def test_an_address_prod_owns_is_refused(self, address: str) -> None:
        values = _values("a.staging.x", "b.staging.x")
        values["networking"]["nodes"]["ace1"]["lan_ip"] = address
        with pytest.raises(lt.LoadTestRefused):
            lt.resolve_nodes(values, PROD)

    def test_the_generator_cannot_share_the_measured_node(self) -> None:
        values = _values("a.staging.x", "b.staging.x")
        values["load_test"]["generator_node"] = "ace1"
        with pytest.raises(lt.LoadTestRefused):
            lt.resolve_nodes(values, PROD)

    def test_a_cluster_with_any_other_node_is_refused(self, tmp_path: pathlib.Path) -> None:
        lab = lt.Lab(tmp_path, "k", "sa", "ace1", "ace2")
        lab.kubectl = lambda *a, **k: "node/kubelab-vps\n"  # type: ignore[method-assign]
        with pytest.raises(lt.LoadTestRefused):
            lab.assert_cluster()

    def test_the_script_pins_the_name_refuses_redirects_and_rechecks_the_host(self) -> None:
        script = (REPO / lt.SCRIPT).read_text()
        assert "hosts: { [LT_HOST]: LT_ADDRESS }" in script
        assert "maxRedirects: 0" in script
        assert lt.STAGING_NAME.pattern.replace("\\.", ".") in script.replace("\\.", ".")
        assert re.search(r"http\.get\(", script) and "http.post" not in script

    def test_the_real_config_builds_a_real_plan(self) -> None:
        from toolkit.features.configuration import ConfigurationManager

        staging = ConfigurationManager("staging", REPO).get_plaintext_values()
        prod = ConfigurationManager("prod", REPO).get_plaintext_values()
        assert len(lt.build_targets(staging, prod)) == 2
        assert lt.resolve_nodes(staging, prod)[0] == "ace1"


class TestBypassRoute:
    def _route(self) -> dict:
        return yaml.safe_load(ROUTE.read_text())

    def test_it_never_reaches_a_kustomization(self) -> None:
        for name in ("staging", "prod"):
            text = (REPO / f"infra/k8s/overlays/{name}/kustomization.yaml").read_text()
            assert "load-test-route" not in text

    def test_every_rule_is_scoped_and_keeps_the_real_chain_minus_the_limiter(self) -> None:
        for rule in self._route()["spec"]["routes"]:
            assert f"Header(`{lt.BYPASS_HEADER}`, `{lt.BYPASS_VALUE}`)" in rule["match"]
            assert [m["name"] for m in rule["middlewares"]] == ["secure-headers", "error-pages"]

    def test_its_hosts_and_paths_are_the_targets(self) -> None:
        rules = " ".join(r["match"] for r in self._route()["spec"]["routes"])
        for target in lt.build_targets(STAGING, PROD):
            assert f"Host(`{target.host}`) && Path(`{target.path}`)" in rules

    def test_only_the_ramp_sends_the_header(self) -> None:
        target = lt.build_targets(STAGING, PROD)[0]
        assert lt.BYPASS_HEADER not in lt.k6_env(target, "10.0.0.2", 25, 60, bypass=False).values()
        assert lt.k6_env(target, "10.0.0.2", 100, 60, bypass=True)["LT_BYPASS_HEADER"] == lt.BYPASS_HEADER


class TestVerdict:
    def test_a_healthy_step_has_no_reasons(self) -> None:
        assert lt.classify(_step(), 100) == []

    @pytest.mark.parametrize(
        ("over", "reason"),
        [
            ({"status_429": 1}, "limiter"),
            ({"pod_replaced": True}, "rollout"),
            ({"generator_cpu": 86.0}, "generator"),
            ({"error_rate": 0.01}, "errors"),
            ({"p95_ms": 251.0}, "latency"),
            ({"achieved_rps": 94.0}, "throughput"),
        ],
    )
    def test_each_limit_is_a_reason(self, over: dict, reason: str) -> None:
        assert reason in lt.classify(_step(**over), 100)

    def test_a_429_under_the_limiter_is_not_an_invalid_step(self) -> None:
        assert "limiter" not in lt.classify(_step(status_429=5), 25, bypass=False)

    def _steps(self, *reasons: list[str]) -> list[dict]:
        return [{"rate": 100 * (i + 1), "reasons": r, "vus_peak": i} for i, r in enumerate(reasons)]

    def test_knee_is_the_last_healthy_rate(self) -> None:
        got = lt.knee(self._steps([], [], ["latency"]))
        assert (got["last_healthy_rps"], got["first_degraded_rps"], got["lower_bound_only"]) == (200, 300, False)
        assert got["vus_at_last_healthy"] == 1

    def test_a_generator_stop_is_only_a_lower_bound(self) -> None:
        assert lt.knee(self._steps([], ["generator"]))["lower_bound_only"] is True

    def test_a_ramp_that_never_degraded_is_only_a_lower_bound(self) -> None:
        assert lt.knee(self._steps([], []))["lower_bound_only"] is True

    def test_a_limiter_stop_measured_nothing(self) -> None:
        assert lt.knee(self._steps([], ["limiter"]))["last_healthy_rps"] is None

    def test_a_rollout_stop_measured_nothing(self) -> None:
        assert lt.knee(self._steps([], ["rollout", "errors"]))["last_healthy_rps"] is None

    def test_the_ramp_stops_at_the_first_unhealthy_step(self) -> None:
        seen: list[int] = []

        def step(rate: int) -> dict:
            seen.append(rate)
            return {"reasons": ["errors"] if rate == 200 else []}

        lt.ramp(step, (100, 200, 400), lambda: None)
        assert seen == [100, 200]


class TestParsing:
    def test_summary(self) -> None:
        metrics = {
            "http_req_duration": {"values": {"avg": 2, "med": 1, "p(90)": 3, "p(95)": 4, "p(99)": 5, "max": 6}},
            "http_reqs": {"values": {"count": 600, "rate": 10.0}},
            "http_req_failed": {"values": {"rate": 0.5}},
            "vus": {"values": {"max": 9}},
        }
        got = lt.parse_summary("noise\n" + json.dumps(metrics) + "\n")
        assert (got["p95_ms"], got["achieved_rps"], got["vus_peak"], got["dropped"], got["status_429"]) == (4, 10.0, 9, 0, 0)

    def test_cpu_counts_iowait_as_idle(self) -> None:
        assert lt.cpu_percent("cpu 0 0 0 100 0 0 0 0 0 0", "cpu 25 0 0 150 25 0 0 0 0 0") == 25.0

    def test_throttling_is_a_delta(self) -> None:
        assert lt.throttled_ms("nr_throttled 1\nthrottled_usec 1000", "nr_throttled 2\nthrottled_usec 5000") == 4.0
