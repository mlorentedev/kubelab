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
        "networking": {
            "nodes": {"ace1": {"lan_ip": "10.0.0.2"}},
            "vps": {"public_ip": "1.2.3.4", "tailscale_ip": "5.6.7.8"},
        },
    }


STAGING = _values("api.staging.kubelab.live", "staging.mlorente.dev")
PROD = _values("api.kubelab.live", "mlorente.dev")


def _step(rate: int = 100, **over: float) -> dict:
    return {
        "rate": rate,
        "status_429": 0,
        "error_rate": 0.0,
        "p95_ms": 10.0,
        "achieved_rps": float(rate),
        "generator_cpu": 10.0,
        "vus_peak": 7,
        **over,
    }


class TestStaysInStaging:
    @pytest.mark.parametrize("env", ["prod", "dev", "", "PROD", "staging "])
    def test_any_env_but_staging_is_refused(self, env: str) -> None:
        with pytest.raises(lt.LoadTestRefused):
            lt.refuse_unless_staging(env)

    def test_the_declared_staging_hosts_pass(self) -> None:
        assert [t.host for t in lt.build_targets(STAGING, PROD)] == ["api.staging.kubelab.live", "staging.mlorente.dev"]

    @pytest.mark.parametrize(
        "api", ["api.kubelab.live", "kubelab.live", "stagingkubelab.live", "api.notstaging.kubelab.live"]
    )
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
        script = (REPO / lt.SCRIPT).read_text(encoding="utf-8")
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
        return yaml.safe_load(ROUTE.read_text(encoding="utf-8"))

    def test_it_stays_outside_everything_a_cluster_is_synced_from(self) -> None:
        assert not ROUTE.is_relative_to(REPO / "infra/k8s")

    def test_every_rule_is_scoped_and_keeps_the_real_chain_minus_the_limiter(self) -> None:
        for rule in self._route()["spec"]["routes"]:
            assert f"Header(`{lt.BYPASS_HEADER}`, `{lt.BYPASS_PLACEHOLDER}`)" in rule["match"]
            assert [m["name"] for m in rule["middlewares"]] == ["secure-headers", "error-pages"]

    def test_its_hosts_and_paths_are_the_targets(self) -> None:
        rules = " ".join(r["match"] for r in self._route()["spec"]["routes"])
        for target in lt.build_targets(STAGING, PROD):
            assert f"Host(`{target.host}`) && Path(`{target.path}`)" in rules

    def test_only_the_ramp_sends_the_header(self) -> None:
        target = lt.build_targets(STAGING, PROD)[0]
        assert lt.BYPASS_HEADER not in lt.k6_env(target, "10.0.0.2", 25, 60, bypass=None).values()
        env = lt.k6_env(target, "10.0.0.2", 100, 60, bypass="f" * 32)
        assert (env["LT_BYPASS_HEADER"], env["LT_BYPASS_VALUE"]) == (lt.BYPASS_HEADER, "f" * 32)


class TestBypassValueLivesOneRun:
    """A route a dead run leaves behind must bypass nothing anyone can use (#3012).

    The header value used to be `ops-054`, in git, so a leftover route let anyone on the
    VPN past the limiter on two staging hosts until someone ran the infra suite.
    """

    def test_each_run_draws_a_new_unguessable_value(self) -> None:
        values = {lt.new_bypass_value() for _ in range(20)}
        assert len(values) == 20
        assert all(re.fullmatch(r"[0-9a-f]{32}", v) for v in values)

    def test_the_rendered_route_carries_the_value_in_every_rule(self) -> None:
        rendered = yaml.safe_load(lt.render_route(ROUTE.read_text(encoding="utf-8"), "a" * 32))
        for rule in rendered["spec"]["routes"]:
            assert f"Header(`{lt.BYPASS_HEADER}`, `{'a' * 32}`)" in rule["match"]
        assert lt.BYPASS_PLACEHOLDER not in json.dumps(rendered)

    @pytest.mark.parametrize("value", ["ops-054", "", "A" * 32, "a" * 31, "a`) || Host(`x"])
    def test_a_value_that_is_not_a_drawn_one_is_refused(self, value: str) -> None:
        with pytest.raises(lt.LoadTestRefused):
            lt.render_route(ROUTE.read_text(encoding="utf-8"), value)

    def test_a_manifest_without_the_placeholder_is_refused(self) -> None:
        with pytest.raises(lt.LoadTestRefused):
            lt.render_route("kind: IngressRoute\n", "a" * 32)

    def test_arm_applies_the_rendered_route_not_the_file(self) -> None:
        lab = lt.Lab(REPO, "kc", "op", "node", "gen")
        calls: list[tuple] = []
        lab.kubectl = lambda *a, **k: calls.append((a, k)) or ""  # type: ignore[method-assign]
        lab.arm("b" * 32)
        ((args, kwargs),) = calls
        assert args == ("apply", "-f", "-")
        assert kwargs["impersonate"] is True
        assert f"`{'b' * 32}`" in kwargs["stdin"] and lt.BYPASS_PLACEHOLDER not in kwargs["stdin"]

    def test_the_run_sends_what_it_armed_and_records_none_of_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sent: list[str | None] = []

        def step(*_a: object, bypass: str | None, **_k: object) -> dict:
            sent.append(bypass)
            return {**_step(), "reasons": ["errors"]}

        monkeypatch.setattr(lt, "run_step", step)
        monkeypatch.setattr(lt, "_runtime_facts", lambda *_: {})
        monkeypatch.setattr(lt, "wait_for_stable_edge", lambda *_: None)
        monkeypatch.setattr("time.sleep", lambda _: None)
        lab = _DyingLab()
        target = lt.Target("api", "api.example", "/health", "api")
        result = lt.run(lab, "img", (target,), "1.2.3.4", 1, 1, 50)
        assert sent[0] is None  # the baseline runs under the limiter
        assert set(sent[1:]) == {lab.armed}
        assert lab.armed not in json.dumps(result)


class TestAcceptEncoding:
    """An A/B on what the client accepts: k6 sends `Accept-Encoding: gzip` by default,
    which makes a server that compresses per request pay for it on every request."""

    def test_k6s_own_default_sends_nothing_extra(self) -> None:
        target = lt.build_targets(STAGING, PROD)[1]
        assert "LT_ACCEPT_ENCODING" not in lt.k6_env(target, "10.0.0.2", 800, 60, bypass="f" * 32)

    def test_a_declared_encoding_reaches_k6(self) -> None:
        target = lt.build_targets(STAGING, PROD)[1]
        env = lt.k6_env(target, "10.0.0.2", 800, 60, bypass="f" * 32, accept_encoding="identity")
        assert env["LT_ACCEPT_ENCODING"] == "identity"

    @pytest.mark.parametrize("value", ["br", "identity;q=1", "gzip identity", "x -e LT_HOST=evil", ""])
    def test_anything_but_identity_or_gzip_is_refused(self, value: str) -> None:
        # The value lands unquoted in the `docker run -e` line.
        with pytest.raises(lt.LoadTestRefused):
            lt.refuse_unknown_encoding(value)

    def test_the_script_sends_it_as_the_header(self) -> None:
        # A live statement on the headers object the request sends, set before the
        # request runs: not a comment, not a different object, not after the call.
        script = (REPO / lt.SCRIPT).read_text(encoding="utf-8")
        live = [line for line in script.splitlines() if not line.lstrip().startswith("//")]
        code = "\n".join(live)
        assign = code.find("if (LT_ACCEPT_ENCODING) headers['Accept-Encoding'] = LT_ACCEPT_ENCODING;")
        assert assign != -1, "the header is not set on `headers`"
        assert assign < code.find("export default function")
        assert "http.get(`https://${LT_HOST}${LT_PATH}`, { headers," in code, "the request does not send `headers`"


class TestVerdict:
    def test_a_healthy_step_has_no_reasons(self) -> None:
        assert lt.classify(_step(), 100) == []

    @pytest.mark.parametrize(
        ("over", "reason"),
        [
            ({"status_429": 1}, "limiter"),
            ({"pod_replaced": True}, "rollout"),
            ({"edge_restarts": 1}, "edge-restart"),
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

    @pytest.mark.parametrize("reason", ["limiter", "rollout"])
    def test_a_ramp_that_measured_nothing_says_so_and_nothing_else(self, reason: str) -> None:
        # #3012: it read `lower_bound_only: true` beside a `vus_at_last_healthy`, so one key
        # meant "a lower bound" and "no figure", and a VU count stood beside a null rate.
        got = lt.knee(self._steps([], [reason]))
        assert got["measured"] is False
        assert got["lower_bound_only"] is False
        assert got["vus_at_last_healthy"] is None
        # The rate the stop happened at is not a capacity figure either; the
        # reason says why the run stopped.
        assert got["first_degraded_rps"] is None and got["reasons"] == [reason]

    @pytest.mark.parametrize("reasons", [[[], ["generator"]], [[], []], [[], ["latency"]]])
    def test_a_ramp_that_reached_a_step_measured_it(self, reasons: list) -> None:
        assert lt.knee(self._steps(*reasons))["measured"] is True

    def test_a_generator_saturated_on_the_first_step_measured_nothing(self) -> None:
        # No healthy step, and the stop was the generator's: there is no figure
        # to call a lower bound, and nothing was learnt about the service.
        got = lt.knee(self._steps(["generator"]))
        assert got["measured"] is False
        assert got["lower_bound_only"] is False
        assert got["last_healthy_rps"] is None and got["vus_at_last_healthy"] is None

    def test_a_ramp_with_no_steps_measured_nothing(self) -> None:
        got = lt.knee([])
        assert got["measured"] is False and got["lower_bound_only"] is False

    def test_a_healthy_rate_of_zero_keeps_its_vus(self) -> None:
        steps = [{"rate": 0, "reasons": [], "vus_peak": 3}, {"rate": 50, "reasons": ["latency"], "vus_peak": 4}]
        got = lt.knee(steps)
        assert (got["last_healthy_rps"], got["vus_at_last_healthy"]) == (0, 3)

    def test_a_service_degraded_on_the_first_step_is_a_measurement(self) -> None:
        # The knee is below the first step, and `first_degraded_rps` says so.
        got = lt.knee(self._steps(["latency"]))
        assert got["measured"] is True and got["lower_bound_only"] is False
        assert got["last_healthy_rps"] is None and got["first_degraded_rps"] is not None

    def test_the_ramp_stops_at_the_first_unhealthy_step(self) -> None:
        seen: list[int] = []

        def step(rate: int) -> dict:
            seen.append(rate)
            return {"reasons": ["errors"] if rate == 200 else []}

        lt.ramp(step, (100, 200, 400), lambda: None)
        assert seen == [100, 200]


class TestEdgeRecovery:
    """A crash loop must never be measured as a service failing at low rates."""

    def test_it_waits_out_a_restart(self) -> None:
        counts = iter([0, 1, 1, 1, 1])
        slept: list[int] = []
        lt.wait_for_stable_edge(lambda: True, lambda: next(counts), slept.append, 30, 100)
        assert sum(slept) == 40  # the restart reset the clock

    def test_an_edge_that_never_settles_stops_the_run(self) -> None:
        counts = iter(range(100))
        with pytest.raises(lt.LoadTestRefused):
            lt.wait_for_stable_edge(lambda: True, lambda: next(counts), lambda _: None, 30, 100)

    def test_an_edge_with_no_pod_never_counts_as_calm(self) -> None:
        # #3012: `edge_state` answers ("", 0) with no pod, which never changes, so only
        # `ready` keeps the clock at zero. A loop that trusted the state alone would pass.
        with pytest.raises(lt.LoadTestRefused):
            lt.wait_for_stable_edge(lambda: False, lambda: ("", 0), lambda _: None, 30, 100)

    def test_calm_counts_only_from_the_pod_that_came_back(self) -> None:
        polls = iter([("", 0)] * 3 + [("uid", 0)] * 10)
        ready = iter([False, False, True] + [True] * 10)
        slept: list[int] = []
        lt.wait_for_stable_edge(lambda: next(ready), lambda: next(polls), slept.append, 30, 200)
        # poll 3 sees the pod (state changed, clock reset); polls 4-6 are calm.
        assert sum(slept) == 60


class TestParsing:
    def test_summary(self) -> None:
        metrics = {
            "http_req_duration": {"values": {"avg": 2, "med": 1, "p(90)": 3, "p(95)": 4, "p(99)": 5, "max": 6}},
            "http_reqs": {"values": {"count": 600, "rate": 10.0}},
            "http_req_failed": {"values": {"rate": 0.5}},
            "vus": {"values": {"max": 9}},
        }
        got = lt.parse_summary("noise\n" + json.dumps(metrics) + "\n")
        assert (got["p95_ms"], got["achieved_rps"], got["vus_peak"], got["dropped"], got["status_429"]) == (
            4,
            10.0,
            9,
            0,
            0,
        )

    def test_a_step_records_where_each_request_spent_its_time(self) -> None:
        # #3102: a p90 of 5 s over a p50 of 6 ms reads the same whether requests waited
        # for a connection, a TLS handshake or the backend; only the phases tell them apart.
        trend = {"med": 1, "p(95)": 2, "p(99)": 3, "max": 4}
        metrics = {
            "http_req_duration": {"values": {"avg": 2, "med": 1, "p(90)": 3, "p(95)": 4, "p(99)": 5, "max": 6}},
            "http_req_blocked": {"values": trend},
            "http_req_connecting": {"values": {**trend, "p(99)": 30}},
            "http_req_tls_handshaking": {"values": trend},
            "http_req_waiting": {"values": trend},
            "http_req_receiving": {"values": trend},
        }
        phases = lt.parse_summary(json.dumps(metrics))["phases"]
        assert set(phases) == {"blocked", "connecting", "tls_handshaking", "waiting", "receiving"}
        assert phases["connecting"] == {"p50_ms": 1, "p95_ms": 2, "p99_ms": 30, "max_ms": 4}

    def test_a_phase_k6_did_not_report_reads_as_zero(self) -> None:
        metrics = {"http_req_duration": {"values": {"avg": 2, "med": 1, "p(90)": 3, "p(95)": 4, "p(99)": 5, "max": 6}}}
        phases = lt.parse_summary(json.dumps(metrics))["phases"]
        assert phases["tls_handshaking"] == {"p50_ms": 0, "p95_ms": 0, "p99_ms": 0, "max_ms": 0}

    def test_cpu_counts_iowait_as_idle(self) -> None:
        assert lt.cpu_percent("cpu 0 0 0 100 0 0 0 0 0 0", "cpu 25 0 0 150 25 0 0 0 0 0") == 25.0

    def test_throttling_is_a_delta(self) -> None:
        assert lt.throttled_ms("nr_throttled 1\nthrottled_usec 1000", "nr_throttled 2\nthrottled_usec 5000") == 4.0


class TestEdgeReadings:
    def test_a_restart_in_place_is_the_difference(self) -> None:
        assert lt.edge_restarts_between(("a", 2), ("a", 5)) == 3

    def test_a_replaced_pod_counts_even_though_its_count_went_down(self) -> None:
        assert lt.edge_restarts_between(("a", 5), ("b", 0)) == 1
        assert lt.edge_restarts_between(("a", 5), ("b", 2)) == 2

    def test_no_running_pod_is_a_refusal_not_a_traceback(self) -> None:
        lab = lt.Lab.__new__(lt.Lab)
        lab.kubectl = lambda *_args, **_kw: json.dumps({"items": [{"status": {"phase": "Pending"}}]})
        with pytest.raises(lt.LoadTestRefused, match="no running pod"):
            lab.pod("traefik", "kube-system")

    def test_an_edge_down_at_the_end_of_a_step_is_recorded_not_raised(self) -> None:
        lab = lt.Lab.__new__(lt.Lab)
        lab.kubectl = lambda *_args, **_kw: json.dumps({"items": []})
        assert lt.edge_restarts_between(("a", 5), lab.edge_state()) == 1


class TestCleanup:
    def test_the_image_goes_even_when_the_route_could_not(self) -> None:
        calls: list[str] = []

        class Lab:
            generator = "gen"

            def disarm(self) -> None:
                raise RuntimeError("api unreachable")

            def ssh(self, _node: str, command: str) -> str:
                calls.append(command)
                return ""

        with pytest.raises(RuntimeError):
            lt.cleanup(Lab(), "grafana/k6:x")
        assert calls and "docker image rm" in calls[0]


class TestResultsDirectory:
    def test_a_relative_directory_is_the_repos_and_gets_created(self, tmp_path: pathlib.Path) -> None:
        from toolkit.cli.infra import _load_test_results_dir

        assert _load_test_results_dir("docs/new", tmp_path) == tmp_path / "docs/new"
        assert (tmp_path / "docs/new").is_dir()

    def test_a_second_run_on_the_same_day_and_commit_keeps_the_first(self, tmp_path: pathlib.Path) -> None:
        """Measured 2026-11-04: a 3,200/s rerun on the same commit replaced the 2,000/s results."""
        from datetime import datetime, timezone

        from toolkit.cli.infra import _load_test_result_base

        now = datetime(2026, 11, 4, 7, 9, tzinfo=timezone.utc)
        first = _load_test_result_base(tmp_path, now, "0e224c0f")
        assert first == tmp_path / "2026-11-04-0e224c0f"
        first.with_suffix(".json").write_text("{}", encoding="utf-8")
        second = _load_test_result_base(tmp_path, now, "0e224c0f")
        assert second == tmp_path / "2026-11-04-0e224c0f-2"
        second.with_suffix(".md").write_text("", encoding="utf-8")
        assert _load_test_result_base(tmp_path, now, "0e224c0f") == tmp_path / "2026-11-04-0e224c0f-3"


class _DyingLab:
    """Enough of a Lab for `run`: everything answers, and the second ramp dies."""

    root = REPO
    generator = "gen"
    target_node = "node"

    def __init__(self) -> None:
        self.disarmed = False
        self.armed = ""

    def assert_cluster(self) -> None: ...

    def arm(self, value: str) -> None:
        self.armed = value

    def disarm(self) -> None:
        self.disarmed = True

    def ssh(self, *_args: object, **_kw: object) -> str:
        return ""

    def restarts(self, *_args: object) -> int:
        return 0

    def edge_state(self) -> tuple[str, int]:
        return "a", 0

    def edge_ready(self) -> bool:
        return True


class TestKeepsWhatItMeasured:
    @staticmethod
    def _run(monkeypatch: pytest.MonkeyPatch, lab: _DyingLab, seen: list[dict]) -> None:
        calls = iter([_step(), _step(), RuntimeError("edge gone")])

        def step(*_args: object, **_kw: object) -> dict:
            got = next(calls)
            if isinstance(got, Exception):
                raise got
            return {**got, "reasons": ["errors"]}

        monkeypatch.setattr(lt, "run_step", step)
        monkeypatch.setattr(lt, "_runtime_facts", lambda *_: {})
        monkeypatch.setattr(lt, "wait_for_stable_edge", lambda *_: None)
        monkeypatch.setattr("time.sleep", lambda _: None)
        target = lt.Target("api", "api.example", "/health", "api")
        lt.run(lab, "img", (target,), "1.2.3.4", 2, 1, 50, checkpoint=lambda r: seen.append(json.loads(json.dumps(r))))

    def test_a_ramp_that_dies_leaves_the_earlier_ones_on_record(self, monkeypatch: pytest.MonkeyPatch) -> None:
        lab, seen = _DyingLab(), []
        with pytest.raises(RuntimeError):
            self._run(monkeypatch, lab, seen)
        assert [len(r["ramps"]) for r in seen] == [0, 1]
        assert all(r["incomplete"] for r in seen)
        assert lab.disarmed

    @pytest.mark.parametrize(("given", "recorded"), [(None, "gzip (k6 default)"), ("identity", "identity")])
    def test_the_result_says_what_the_client_accepted(
        self, monkeypatch: pytest.MonkeyPatch, given: str | None, recorded: str
    ) -> None:
        monkeypatch.setattr(lt, "run_step", lambda *_a, **_k: {**_step(), "reasons": ["errors"]})
        monkeypatch.setattr(lt, "_runtime_facts", lambda *_: {})
        monkeypatch.setattr(lt, "wait_for_stable_edge", lambda *_: None)
        monkeypatch.setattr("time.sleep", lambda _: None)
        target = lt.Target("api", "api.example", "/health", "api")
        result = lt.run(_DyingLab(), "img", (target,), "1.2.3.4", 1, 1, 50, accept_encoding=given)
        assert result["facts"]["accept_encoding"] == recorded

    def test_a_report_of_a_partial_run_says_so(self) -> None:
        assert lt.render({"baseline": [], "ramps": [], "incomplete": True}).startswith("**Incomplete")
        assert "Incomplete" not in lt.render({"baseline": [], "ramps": []})

    @staticmethod
    def _rendered_step() -> dict:
        figures = dict.fromkeys(("requests", "achieved_rps", "error_rate", "status_429", "dropped", "vus_peak"), 0)
        figures |= dict.fromkeys(("avg_ms", "p50_ms", "p90_ms", "p95_ms", "p99_ms", "max_ms", "throttled_ms"), 0.0)
        return {
            **figures, "rate": 100, "node_cpu": 1.0, "generator_cpu": 1.0, "node_mem_available_mb": 1,
            "pods_top": {}, "reasons": [],
        }  # fmt: skip

    def test_a_report_shows_the_phases_of_each_step(self) -> None:
        step = self._rendered_step()
        step["phases"] = {p: {"p50_ms": 0, "p95_ms": 0, "p99_ms": 0, "max_ms": 0} for p in lt.PHASES}
        step["phases"]["connecting"]["p99_ms"] = 3000
        text = lt.render({"baseline": [], "ramps": [{"target": "api", "repeat": 1, "knee": {}, "steps": [step]}]})
        assert "connecting p99" in text and "3000.0" in text

    def test_a_report_of_an_older_run_without_phases_still_renders(self) -> None:
        ramp = {"target": "api", "repeat": 1, "knee": {}, "steps": [self._rendered_step()]}
        text = lt.render({"baseline": [], "ramps": [ramp]})
        assert "connecting p99" not in text


class TestRefusesARunThatMeasuresNothing:
    @pytest.mark.parametrize(("repeats", "seconds", "max_rate"), [(0, 60, 6400), (3, 0, 6400), (3, 60, 49)])
    def test_refused(self, repeats: int, seconds: int, max_rate: int) -> None:
        with pytest.raises(lt.LoadTestRefused):
            lt.refuse_empty_run(repeats, seconds, max_rate)

    def test_the_smallest_real_run_passes(self) -> None:
        lt.refuse_empty_run(1, 1, lt.STEPS[0])

    def test_a_floor_above_the_ceiling_selects_nothing_and_is_refused(self) -> None:
        with pytest.raises(lt.LoadTestRefused):
            lt.refuse_empty_run(1, 60, 1400, min_rate=1600)


class TestStartsAtAFloor:
    """A rerun at the knee: a ramp stops at its first degraded step, so a floor reaches past it."""

    def test_no_floor_keeps_every_step_up_to_the_ceiling(self) -> None:
        assert lt.select_steps(0, 400) == (50, 100, 200, 400)

    def test_a_floor_drops_the_steps_below_it(self) -> None:
        assert lt.select_steps(1400, 1600) == (1400, 1600)


class TestEdgeDownWhileWaiting:
    def test_no_running_pod_is_not_ready_rather_than_a_refusal(self) -> None:
        lab = lt.Lab.__new__(lt.Lab)
        lab.kubectl = lambda *_args, **_kw: json.dumps({"items": []})
        assert lab.edge_ready() is False

    def test_a_failed_disarm_names_the_remedy(self) -> None:
        class Lab:
            generator = "gen"

            def disarm(self) -> None:
                raise OSError("kubectl missing")

            def ssh(self, *_args: object) -> str:
                return ""

        with pytest.raises(lt.LoadTestRefused, match="load-test-clear"):
            lt.cleanup(Lab(), "img")


class TestRemoteCommandQuoting:
    """#3012: `k6_command` runs through one remote shell, so every value is quoted."""

    def test_each_value_reaches_k6_as_one_word(self) -> None:
        import shlex

        cmd = lt.k6_command("grafana/k6:1.0", {"LT_PATH": "/a b", "LT_HOST": "x;touch /tmp/p"})
        words = shlex.split(cmd)
        assert "LT_PATH=/a b" in words
        assert "LT_HOST=x;touch /tmp/p" in words
        assert words[words.index("LT_HOST=x;touch /tmp/p") - 1] == "-e"

    def test_the_image_is_quoted_too(self) -> None:
        import shlex

        assert "img x" in shlex.split(lt.k6_command("img x", {}))


def test_the_edge_measure_comment_sits_on_its_own_target() -> None:
    # #3012: the load-test block had landed between edge-measure's comment and target.
    lines = (REPO / "Makefile").read_text(encoding="utf-8").splitlines()
    target = lines.index(".PHONY: edge-measure")
    block = []
    for line in reversed(lines[:target]):
        if not line.startswith("#"):
            break
        block.append(line)
    assert any("line rate" in line for line in block), "edge-measure has no comment directly above it"
    load = lines.index(".PHONY: load-test load-test-clear")
    assert "line rate" not in "".join(lines[load - 4 : load])
