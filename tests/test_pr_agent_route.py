"""TOOL-082 (#1843): scripts/pr-agent-route.sh draws which pool member reviews a PR first.

The CI review pool is the members of `harness/reviewer-pool.json` that carry a
`pr_agent` block. The route draws among those that answered their probe by their
declared `weight`, sends a risky PR to the `route: risk` member, and names the
provider of the second attempt. Ported from mlorentedev/dotfiles (dotfiles
AI-045 AC9); the shares are the budget, so the shipped-pool tests read the file
CI reads and pin it to ADR-070.

Two halves, because a stub proves what the script ASKS curl to do and nothing
about what curl does with it:

- the stubbed tests put a fake `curl` first on PATH that answers each Anthropic
  probe with STUB_CODE (STUB_SONNET_CODE for Sonnet's; `timeout` behaves like
  curl's exit 28) and logs its argv and stdin, so they can prove where the key
  travels. Their pool is a fixture with weights 3, 2 and 5, so a point in
  [0, 10) names exactly one member: 0-2 mimo, 3-4 deepseek, 5-9 haiku;
- the real tests run the real `curl` against a server on 127.0.0.1 and prove it
  reads the x-api-key header from the config on stdin (`-K -`), reaches
  `/v1/messages` with the version header, and that `-m` turns a server that never
  answers into the "no answer" path.
"""

from __future__ import annotations

import http.server
import json
import os
import re
import shutil
import socketserver
import subprocess
import threading
from collections import Counter
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ROUTE = REPO_ROOT / "scripts" / "pr-agent-route.sh"
SHIPPED_POOL = REPO_ROOT / "harness" / "reviewer-pool.json"
ADR = REPO_ROOT / "docs" / "adr" / "adr-070-review-pool-adopts-dotfiles-adr-046.md"
KEY = "sk-ant-test-not-a-real-key"

HAIKU = "anthropic/claude-haiku-5-5"
SONNET = "anthropic/claude-sonnet-5-5"
MIMO = "openai/mimo-v2.6-flash"
DEEPSEEK = "openai/deepseek-v4-flash"

pytestmark = pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("bash", "jq", "curl")),
    reason="the route needs bash, jq and curl",
)

FAKE_CURL = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$STUB_ARGV_LOG"
cat >> "$STUB_STDIN_LOG"
code="${STUB_CODE:-200}"
case "$*" in *claude-sonnet*) code="${STUB_SONNET_CODE:-$code}" ;; esac
if [ "$code" = "timeout" ]; then printf '000'; exit 28; fi
printf '%s' "$code"
"""

FIXTURE_POOL = {
    "pool": [
        {"id": "nan/mimo-v2.6-flash", "pr_agent": {"model": MIMO, "weight": 3}},
        {"id": "nan/deepseek-v4-flash", "pr_agent": {"model": DEEPSEEK, "weight": 2}},
        {"id": "nan/qwen3.8-flash"},
        {
            "id": "anthropic-review/claude-haiku-5-5",
            "pr_agent": {"model": HAIKU, "weight": 5, "reasoning_effort": "high"},
        },
        {
            "id": "anthropic-review/claude-sonnet-5-5",
            "pr_agent": {"model": SONNET, "route": "risk", "reasoning_effort": "medium"},
        },
    ],
    "pr_agent_risk": {"min_changed_lines": 900, "label": "deep-review"},
}

# What the route reads from the environment; a developer's shell must not leak in.
ROUTE_VARS = (
    "POOL_FILE",
    "NAN_OUTCOME",
    "NAN_MODEL",
    "NAN_FALLBACKS",
    "NAN_PREFLIGHT_EXIT",
    "PR_AGENT_ANTHROPIC_API_KEY",
    "PR_AGENT_PROVIDER",
    "PR_CHANGED_LINES",
    "PR_LABELS",
    "PR_AGENT_DRAW",
    "ANTHROPIC_API_BASE",
    "ROUTE_PROBE_TIMEOUT",
    "GITHUB_REPOSITORY",
    "GITHUB_STEP_SUMMARY",
    "STUB_CODE",
    "STUB_SONNET_CODE",
)


def _output(proc: subprocess.CompletedProcess[str]) -> str:
    return proc.stdout + proc.stderr


def _in_order(text: str, *parts: str) -> bool:
    """True when every part occurs in `text`, each after the one before it."""
    at = 0
    for part in parts:
        at = text.find(part, at)
        if at < 0:
            return False
        at += len(part)
    return True


def _declared_nan_chain(pool_file: Path) -> tuple[str, str]:
    """NAN_MODEL and NAN_FALLBACKS as the preflight would hand them over: every
    NaN model the pool declares, answering, in pool order."""
    pool = json.loads(pool_file.read_text())
    nan = [m["pr_agent"]["model"] for m in pool["pool"] if m.get("pr_agent", {}).get("model", "").startswith("openai/")]
    return nan[0], json.dumps(nan[1:])


class Route:
    """The route run against a fake curl, with its output file and logs."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.out = tmp_path / "output"
        self.argv_log = tmp_path / "argv.log"
        self.stdin_log = tmp_path / "stdin.log"
        self.summary = tmp_path / "summary"
        self.pool = tmp_path / "pool.json"
        self.pool.write_text(json.dumps(FIXTURE_POOL))
        bindir = tmp_path / "bin"
        bindir.mkdir()
        curl = bindir / "curl"
        curl.write_text(FAKE_CURL)
        curl.chmod(0o755)
        self.argv_log.write_text("")
        self.env = {k: v for k, v in os.environ.items() if k not in ROUTE_VARS}
        self.env.update(
            PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}",
            STUB_ARGV_LOG=str(self.argv_log),
            STUB_STDIN_LOG=str(self.stdin_log),
            POOL_FILE=str(self.pool),
            NAN_OUTCOME="success",
            NAN_MODEL=MIMO,
            NAN_FALLBACKS=json.dumps([DEEPSEEK]),
            PR_AGENT_ANTHROPIC_API_KEY=KEY,
            GITHUB_REPOSITORY="o/r",
        )

    def run(self, **overrides: str | None) -> subprocess.CompletedProcess[str]:
        """One run into this fixture's output file. A None override unsets the variable."""
        return self.execute(self.out, overrides)

    def execute(self, out: Path, overrides: dict[str, str | None]) -> subprocess.CompletedProcess[str]:
        out.write_text("")
        merged: dict[str, str] = dict(self.env)
        for name, value in overrides.items():
            if value is None:
                merged.pop(name, None)
            else:
                merged[name] = value
        return subprocess.run(  # noqa: S603
            [str(ROUTE), "--output", str(out)],
            env=merged,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def get(self, key: str) -> str:
        """One `key=value` line of the last run's output file."""
        match = re.search(rf"^{re.escape(key)}=(.*)$", self.out.read_text(), re.MULTILINE)
        return match.group(1) if match else ""

    def reset_argv(self) -> None:
        self.argv_log.write_text("")

    def every_point(self, total: int, **overrides: str | None) -> dict[str, int]:
        """How many points of [0, total) draw each reviewer."""

        def one(point: int) -> str:
            out = self.tmp_path / f"point-{point}"
            self.execute(out, {"PR_AGENT_DRAW": str(point), **overrides})
            match = re.search(r"^reviewer=(.*)$", out.read_text(), re.MULTILINE)
            return match.group(1) if match else ""

        with ThreadPoolExecutor(max_workers=8) as pool:
            return dict(Counter(pool.map(one, range(total))))


@pytest.fixture
def route(tmp_path: Path) -> Route:
    return Route(tmp_path)


# --- the draw --------------------------------------------------------------------


def test_each_member_is_drawn_at_its_own_points_with_the_other_provider_second(route: Route) -> None:
    proc = route.run(PR_AGENT_DRAW="0")
    assert proc.returncode == 0, _output(proc)
    assert route.get("reviewer") == MIMO
    assert route.get("route") == "draw"
    assert route.get("first") == "nan"
    assert route.get("second") == "anthropic"
    assert route.get("nan_model") == MIMO
    assert route.get("nan_fallbacks") == f'["{DEEPSEEK}"]'
    # The second attempt is the drawn Anthropic member, at its effort.
    assert route.get("anthropic_model") == HAIKU
    assert route.get("anthropic_effort") == "high"

    route.run(PR_AGENT_DRAW="3")
    assert route.get("reviewer") == DEEPSEEK
    # The drawn NaN model goes first; the other stays behind it.
    assert route.get("nan_model") == DEEPSEEK
    assert route.get("nan_fallbacks") == f'["{MIMO}"]'

    route.run(PR_AGENT_DRAW="5")
    assert route.get("reviewer") == HAIKU
    assert route.get("first") == "anthropic"
    assert route.get("second") == "nan"
    assert route.get("anthropic_model") == HAIKU
    # NaN is the second attempt, in declared order.
    assert route.get("nan_model") == MIMO
    assert route.get("nan_fallbacks") == f'["{DEEPSEEK}"]'


def test_across_every_point_each_member_is_drawn_exactly_its_weight(route: Route) -> None:
    assert route.every_point(10) == {HAIKU: 5, DEEPSEEK: 2, MIMO: 3}


def test_a_member_that_did_not_answer_gives_up_its_points_and_the_rest_keep_theirs(route: Route) -> None:
    env = {"NAN_FALLBACKS": "[]"}
    assert route.every_point(8, **env) == {HAIKU: 5, MIMO: 3}
    assert route.run(**env, PR_AGENT_DRAW="8").returncode == 2


def test_a_nan_model_with_no_weight_is_never_drawn_first_but_stays_in_the_chain(route: Route) -> None:
    fallbacks = json.dumps([DEEPSEEK, "openai/glm5.3-flash"])
    assert route.every_point(10, NAN_FALLBACKS=fallbacks) == {HAIKU: 5, DEEPSEEK: 2, MIMO: 3}
    route.run(NAN_FALLBACKS=fallbacks, PR_AGENT_DRAW="0")
    assert route.get("nan_fallbacks") == '["openai/deepseek-v4-flash","openai/glm5.3-flash"]'


def test_a_point_outside_the_total_weight_is_a_usage_error_never_a_silent_pick(route: Route) -> None:
    assert route.run(PR_AGENT_DRAW="10").returncode == 2
    assert route.run(PR_AGENT_DRAW="x").returncode == 2


def test_the_random_draw_reaches_every_member_the_heaviest_most(route: Route) -> None:
    def one(i: int) -> str:
        out = route.tmp_path / f"random-{i}"
        route.execute(out, {})
        match = re.search(r"^reviewer=(.*)$", out.read_text(), re.MULTILINE)
        return match.group(1) if match else ""

    with ThreadPoolExecutor(max_workers=8) as pool:
        counts = Counter(pool.map(one, range(300)))
    assert set(counts) == {MIMO, DEEPSEEK, HAIKU}, counts
    # Expected 90, 60 and 150; 30 is more than four standard deviations below
    # the smallest, and haiku leads deepseek by about seven.
    assert all(n >= 30 for n in counts.values()), counts
    assert counts[HAIKU] > counts[DEEPSEEK], counts


def test_the_shipped_pool_draws_each_member_exactly_its_declared_weight(route: Route) -> None:
    """The shipped pool, not the fixture: every point of its total weight draws
    the member that owns it, so the shares in harness/reviewer-pool.json are the
    shares CI runs."""
    pool = json.loads(SHIPPED_POOL.read_text())
    nan_model, nan_fallbacks = _declared_nan_chain(SHIPPED_POOL)
    weights = {
        m["pr_agent"]["model"]: m["pr_agent"]["weight"] for m in pool["pool"] if "weight" in m.get("pr_agent", {})
    }
    drawn = route.every_point(
        sum(weights.values()), POOL_FILE=str(SHIPPED_POOL), NAN_MODEL=nan_model, NAN_FALLBACKS=nan_fallbacks
    )
    assert drawn == weights


def _shared_by_short_name(shares: dict[str, int]) -> dict[str, int]:
    return {short: n for model, n in shares.items() for short in ("mimo", "glm", "deepseek", "haiku") if short in model}


def test_the_shipped_weights_are_the_ones_adr_070_adopted() -> None:
    """The shares are the budget (ADR-070 decision 3 names them), so the shipped
    weights must be the ADR's: a share changed in the pool without an amendment
    to the ADR fails here, and the test above only proves the draw honours
    whatever the pool says. dotfiles read ADR-046's 'Weights at adoption:' line;
    kubelab's ADR-070 states them as 'starting weights:'."""
    line = next((ln for ln in ADR.read_text().splitlines() if "starting weights:" in ln), None)
    assert line, "ADR-070 states no 'starting weights:' line"
    adopted = {
        pair.split()[0].lower(): int(pair.split()[1])
        for pair in line.split("starting weights:", 1)[1].strip().rstrip(".").split(",")
    }
    assert len(adopted) == 4, adopted
    pool = json.loads(SHIPPED_POOL.read_text())
    shipped = _shared_by_short_name(
        {m["pr_agent"]["model"]: m["pr_agent"]["weight"] for m in pool["pool"] if "weight" in m.get("pr_agent", {})}
    )
    assert shipped == adopted
    assert adopted == {"mimo": 27, "glm": 19, "deepseek": 19, "haiku": 35}


def test_the_shipped_pool_routes_to_sonnet_at_1500_changed_lines_and_not_below(route: Route) -> None:
    """1,500 changed lines put about 3% of PRs on Sonnet and moving it moves the
    month's spend, so the number is pinned here and the route is driven against
    the shipped pool on both sides."""
    nan_model, nan_fallbacks = _declared_nan_chain(SHIPPED_POOL)
    env = {"POOL_FILE": str(SHIPPED_POOL), "NAN_MODEL": nan_model, "NAN_FALLBACKS": nan_fallbacks}
    assert json.loads(SHIPPED_POOL.read_text())["pr_agent_risk"]["min_changed_lines"] == 1500

    proc = route.run(**env, PR_CHANGED_LINES="1500", PR_AGENT_DRAW="0")
    assert proc.returncode == 0, _output(proc)
    assert route.get("route") == "risk"
    assert route.get("reviewer") == SONNET

    proc = route.run(**env, PR_CHANGED_LINES="1499", PR_AGENT_DRAW="0")
    assert proc.returncode == 0, _output(proc)
    assert route.get("route") == "draw"


# --- the risk route --------------------------------------------------------------


def test_a_pr_at_the_line_threshold_reviews_first_on_the_risk_member_nan_second(route: Route) -> None:
    proc = route.run(PR_CHANGED_LINES="900", PR_AGENT_DRAW="0")
    assert proc.returncode == 0, _output(proc)
    assert route.get("route") == "risk"
    assert route.get("reviewer") == SONNET
    assert route.get("first") == "anthropic"
    assert route.get("second") == "nan"
    assert route.get("anthropic_model") == SONNET
    assert route.get("anthropic_effort") == "medium"
    assert '"model":"claude-sonnet-5-5"' in route.argv_log.read_text()

    route.run(PR_CHANGED_LINES="899", PR_AGENT_DRAW="0")
    assert route.get("route") == "draw"
    assert route.get("reviewer") == MIMO


def test_the_label_routes_a_small_pr_to_the_risk_member_and_only_the_exact_label(route: Route) -> None:
    route.run(PR_CHANGED_LINES="3", PR_LABELS='["docs", "deep-review"]', PR_AGENT_DRAW="0")
    assert route.get("route") == "risk"
    assert route.get("reviewer") == SONNET
    route.run(PR_CHANGED_LINES="3", PR_LABELS='["deep-review-later"]', PR_AGENT_DRAW="0")
    assert route.get("route") == "draw"


def test_the_risk_member_is_probed_only_for_a_risky_pr(route: Route) -> None:
    route.run(PR_CHANGED_LINES="10", PR_AGENT_DRAW="0")
    assert "claude-sonnet" not in route.argv_log.read_text()


def test_a_risk_member_that_does_not_answer_sends_the_pr_to_the_draw_with_a_note(route: Route) -> None:
    proc = route.run(STUB_SONNET_CODE="529", PR_CHANGED_LINES="5000", PR_AGENT_DRAW="5")
    assert proc.returncode == 0, _output(proc)
    assert route.get("route") == "draw"
    assert route.get("reviewer") == HAIKU
    assert route.get("anthropic_model") == HAIKU
    assert _in_order(route.get("note"), "crossed the risk line (5000 changed lines", "drawn by weight instead")


def test_an_unread_size_is_named_and_the_label_still_routes(route: Route) -> None:
    route.run(PR_CHANGED_LINES="", PR_AGENT_DRAW="0")
    assert route.get("route") == "draw"
    assert "size could not be read" in route.get("note")
    route.run(PR_CHANGED_LINES="", PR_LABELS='["deep-review"]', PR_AGENT_DRAW="0")
    assert route.get("route") == "risk"


def test_provider_nan_and_nan_only_never_take_the_risk_route(route: Route) -> None:
    route.run(PR_AGENT_PROVIDER="nan", PR_CHANGED_LINES="5000", PR_AGENT_DRAW="0")
    assert route.get("first") == "nan"
    assert route.get("route") == "draw"
    route.reset_argv()
    route.run(PR_AGENT_PROVIDER="nan-only", PR_CHANGED_LINES="5000", PR_AGENT_DRAW="0")
    assert route.get("first") == "nan"
    assert route.argv_log.read_text() == ""


# --- the allowlist ---------------------------------------------------------------


def test_a_pool_naming_an_anthropic_model_outside_the_allowlist_fails_before_any_probe(route: Route) -> None:
    pool = json.loads(route.pool.read_text())
    pool["pool"][3]["pr_agent"]["model"] = "anthropic/claude-opus-5-5"
    route.pool.write_text(json.dumps(pool))
    proc = route.run(PR_AGENT_DRAW="0")
    assert proc.returncode == 1, _output(proc)
    assert _in_order(_output(proc), "::error::", "anthropic/claude-opus-5-5", "allowlist"), _output(proc)
    assert route.argv_log.read_text() == ""
    assert route.out.read_text() == ""


def test_the_allowlist_is_exactly_haiku_and_sonnet() -> None:
    declared = [ln for ln in ROUTE.read_text().splitlines() if ln.startswith("ALLOWED_ANTHROPIC=")]
    assert declared == ['ALLOWED_ANTHROPIC="anthropic/claude-haiku-5-5 anthropic/claude-sonnet-5-5"']


def test_an_unreadable_pool_is_a_usage_error(route: Route) -> None:
    assert route.run(POOL_FILE=str(route.tmp_path / "missing.json")).returncode == 2


# --- members out of the draw -----------------------------------------------------


@pytest.mark.parametrize("code", ["401", "404", "429", "529", "timeout"])
def test_an_anthropic_member_that_does_not_answer_is_never_drawn(route: Route, code: str) -> None:
    proc = route.run(STUB_CODE=code, PR_AGENT_DRAW="3")
    assert proc.returncode == 0, _output(proc)
    assert route.get("first") == "nan"
    assert route.get("second") == "none"
    assert route.get("anthropic_model") == ""
    assert _in_order(_output(proc), "::warning::", "claude-haiku-5-5"), _output(proc)
    assert route.get("note")
    # Only NaN's five points remain.
    assert route.run(STUB_CODE=code, PR_AGENT_DRAW="5").returncode == 2


def test_the_warning_names_the_fix_by_status_class(route: Route) -> None:
    route.run(STUB_CODE="401", PR_AGENT_DRAW="0")
    assert _in_order(route.get("note"), "key is refused", "dotf secrets rotate PR_AGENT_ANTHROPIC_API_KEY")
    route.run(STUB_CODE="404", PR_AGENT_DRAW="0")
    assert _in_order(route.get("note"), "model id is wrong", "reviewer-pool.json")
    route.run(STUB_CODE="429", PR_AGENT_DRAW="0")
    assert "rate limit, overload or spend limit" in route.get("note")


def test_no_key_means_no_probe_and_no_anthropic_member_with_the_remedy(route: Route) -> None:
    proc = route.run(PR_AGENT_ANTHROPIC_API_KEY="", PR_CHANGED_LINES="5000", PR_AGENT_DRAW="0")
    assert proc.returncode == 0, _output(proc)
    assert route.get("second") == "none"
    assert route.get("route") == "draw"
    assert route.argv_log.read_text() == ""
    assert "dotf secrets sync ci --repo o/r PR_AGENT_ANTHROPIC_API_KEY" in route.get("note")


def test_nan_down_as_a_whole_leaves_anthropic_alone_with_no_second_attempt(route: Route) -> None:
    proc = route.run(NAN_OUTCOME="failure", NAN_MODEL="", NAN_FALLBACKS="", PR_AGENT_DRAW="0")
    assert proc.returncode == 0, _output(proc)
    assert route.get("first") == "anthropic"
    assert route.get("second") == "none"
    assert route.get("nan_model") == ""


def test_a_preflight_that_failed_on_its_setup_stops_the_draw_instead_of_paying_for_every_review(
    route: Route,
) -> None:
    proc = route.run(NAN_OUTCOME="failure", NAN_MODEL="", NAN_FALLBACKS="", NAN_PREFLIGHT_EXIT="2")
    assert proc.returncode == 1, _output(proc)
    assert "::error::The NaN preflight failed on its setup (exit 2)" in _output(proc)
    assert route.argv_log.read_text() == ""
    assert route.out.read_text() == ""


def test_a_preflight_in_which_no_model_answered_exit_1_still_hands_over_to_anthropic(route: Route) -> None:
    proc = route.run(NAN_OUTCOME="failure", NAN_MODEL="", NAN_FALLBACKS="", NAN_PREFLIGHT_EXIT="1", PR_AGENT_DRAW="0")
    assert proc.returncode == 0, _output(proc)
    assert route.get("first") == "anthropic"


def test_no_member_at_all_answers_first_none_and_the_job_summary_says_so(route: Route) -> None:
    proc = route.run(NAN_OUTCOME="failure", NAN_MODEL="", STUB_CODE="529", GITHUB_STEP_SUMMARY=str(route.summary))
    assert proc.returncode == 0, _output(proc)
    assert route.get("first") == "none"
    assert route.get("second") == "none"
    assert "No member answered" in route.summary.read_text()


# --- the override ----------------------------------------------------------------


def test_provider_nan_draws_among_nan_only_with_anthropic_second(route: Route) -> None:
    route.run(PR_AGENT_PROVIDER="nan", PR_AGENT_DRAW="3")
    assert route.get("reviewer") == DEEPSEEK
    assert route.get("second") == "anthropic"
    assert route.run(PR_AGENT_PROVIDER="nan", PR_AGENT_DRAW="5").returncode == 2


def test_provider_anthropic_puts_anthropic_first_nan_second(route: Route) -> None:
    route.run(PR_AGENT_PROVIDER="anthropic", PR_AGENT_DRAW="0")
    assert route.get("first") == "anthropic"
    assert route.get("second") == "nan"


def test_provider_nan_only_never_probes_or_schedules_anthropic(route: Route) -> None:
    proc = route.run(PR_AGENT_PROVIDER="nan-only", PR_AGENT_DRAW="0")
    assert proc.returncode == 0, _output(proc)
    assert route.get("first") == "nan"
    assert route.get("second") == "none"
    assert route.argv_log.read_text() == ""
    # Even with NaN down, the switch holds: no review rather than spending.
    route.run(NAN_OUTCOME="failure", NAN_MODEL="", PR_AGENT_PROVIDER="nan-only")
    assert route.get("first") == "none"
    assert route.argv_log.read_text() == ""


def test_a_forced_provider_with_no_member_that_answered_draws_from_the_rest_loudly(route: Route) -> None:
    proc = route.run(STUB_CODE="529", PR_AGENT_PROVIDER="anthropic", PR_AGENT_DRAW="0")
    assert proc.returncode == 0, _output(proc)
    assert route.get("first") == "nan"
    assert "::warning::PR_AGENT_PROVIDER=anthropic" in _output(proc)


def test_an_unknown_override_fails_before_any_probe(route: Route) -> None:
    proc = route.run(PR_AGENT_PROVIDER="nan_only")
    assert proc.returncode == 1, _output(proc)
    assert "::error::PR_AGENT_PROVIDER is nan_only" in _output(proc)
    assert route.argv_log.read_text() == ""
    assert route.out.read_text() == ""


# --- the key, the request, the outputs -------------------------------------------


def test_the_key_travels_on_curls_stdin_never_on_its_argv(route: Route) -> None:
    proc = route.run(PR_CHANGED_LINES="5000", PR_AGENT_DRAW="0")
    assert proc.returncode == 0, _output(proc)
    assert KEY not in route.argv_log.read_text()
    assert f'header = "x-api-key: {KEY}"' in route.stdin_log.read_text()
    assert "sk-ant-test" not in _output(proc)
    assert "sk-ant-test" not in route.out.read_text()


def test_the_probe_asks_for_the_pools_model_briefly_on_the_messages_api(route: Route) -> None:
    route.run(PR_AGENT_DRAW="0")
    argv = route.argv_log.read_text()
    for expected in (
        '"model":"claude-haiku-5-5"',
        '"max_tokens":64',
        "anthropic-version: 2023-06-01",
        "https://api.anthropic.com/v1/messages",
    ):
        assert expected in argv


def test_the_job_summary_names_the_member_drawn_the_risk_route_and_the_second_attempt(route: Route) -> None:
    route.run(GITHUB_STEP_SUMMARY=str(route.summary), PR_AGENT_DRAW="5")
    summary = route.summary.read_text()
    assert f"Drawn to review first: `{HAIKU}`" in summary
    assert "nothing is published: nan." in summary
    route.summary.write_text("")
    route.run(GITHUB_STEP_SUMMARY=str(route.summary), PR_LABELS='["deep-review"]')
    assert f"Routed by risk (the deep-review label) to `{SONNET}`" in route.summary.read_text()


def test_it_runs_under_bash_e_as_a_workflow_step_does(route: Route) -> None:
    route.out.write_text("")
    proc = subprocess.run(  # noqa: S603
        ["bash", "-e", str(ROUTE), "--output", str(route.out)],
        env=route.env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, _output(proc)
    assert route.get("first")


# --- the real curl ---------------------------------------------------------------


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

    # HTTPServer.server_bind resolves socket.getfqdn(host) only to fill
    # server_name. On a macOS runner that reverse lookup outlived the start-up
    # wait, so every test failed in setup. Nothing here reads server_name.
    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = str(self.server_address[0]), self.server_address[1]


class LocalAnthropic:
    """An Anthropic stand-in on 127.0.0.1. It answers by `mode`, not by the
    model: the probe asks for the real allowlisted id, so no test-only id ever
    needs to pass the allowlist. `alive` answers 200, `dead` answers 401, `hang`
    holds the connection open, `stall` sends a 200 status line and never the body."""

    def __init__(self) -> None:
        self.mode = "alive"
        self.requests: list[str] = []
        self.release = threading.Event()
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append(
                    f"{self.path} {body['model']} {self.headers.get('x-api-key', '<none>')} "
                    f"{self.headers.get('anthropic-version', '<none>')}"
                )
                if owner.mode == "hang":
                    owner.release.wait(30)
                    return
                if owner.mode == "stall":
                    self.send_response(200)
                    self.send_header("Content-Length", "100")
                    self.end_headers()
                    self.wfile.flush()
                    owner.release.wait(30)
                    return
                self.send_response(200 if owner.mode == "alive" else 401)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args: object) -> None:
                pass

        self.server = _Server(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> LocalAnthropic:
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release.set()
        self.server.shutdown()
        self.server.server_close()


class RealRoute:
    """The route against the real curl and a LocalAnthropic, on a two-member pool."""

    def __init__(self, server: LocalAnthropic, tmp_path: Path) -> None:
        self.server = server
        self.out = tmp_path / "output"
        pool = tmp_path / "pool.json"
        pool.write_text(
            json.dumps(
                {
                    "pool": [
                        {"id": "nan/mimo-v2.6-flash", "pr_agent": {"model": MIMO, "weight": 1}},
                        {"id": "anthropic-review/claude-haiku-5-5", "pr_agent": {"model": HAIKU, "weight": 1}},
                    ]
                }
            )
        )
        self.env = {k: v for k, v in os.environ.items() if k not in ROUTE_VARS}
        self.env.update(
            ANTHROPIC_API_BASE=server.url,
            PR_AGENT_ANTHROPIC_API_KEY=KEY,
            ROUTE_PROBE_TIMEOUT="2",
            NAN_OUTCOME="success",
            NAN_MODEL=MIMO,
            NAN_FALLBACKS="[]",
            POOL_FILE=str(pool),
            PR_AGENT_DRAW="0",
        )

    def run(self, **overrides: str) -> subprocess.CompletedProcess[str]:
        self.out.write_text("")
        return subprocess.run(  # noqa: S603
            [str(ROUTE), "--output", str(self.out)],
            env={**self.env, **overrides},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def get(self, key: str) -> str:
        match = re.search(rf"^{re.escape(key)}=(.*)$", self.out.read_text(), re.MULTILINE)
        return match.group(1) if match else ""


@pytest.fixture
def real(tmp_path: Path) -> Iterator[RealRoute]:
    with LocalAnthropic() as server:
        yield RealRoute(server, tmp_path)


def test_real_curl_sends_the_key_from_stdin_and_the_version_header_to_v1_messages(real: RealRoute) -> None:
    proc = real.run(PR_AGENT_DRAW="1")
    assert proc.returncode == 0, _output(proc)
    assert real.get("reviewer") == HAIKU
    assert real.server.requests == [f"/v1/messages claude-haiku-5-5 {KEY} 2023-06-01"]


def test_real_curl_a_refusal_comes_back_as_its_status(real: RealRoute) -> None:
    real.server.mode = "dead"
    proc = real.run()
    assert proc.returncode == 0, _output(proc)
    assert real.get("second") == "none"
    assert "answered HTTP 401" in real.get("note")


def test_real_curl_a_server_that_never_answers_ends_at_the_timeout_as_no_answer(real: RealRoute) -> None:
    real.server.mode = "hang"
    proc = real.run()
    assert proc.returncode == 0, _output(proc)
    assert real.get("second") == "none"
    assert "no answer within 2s" in real.get("note")


def test_real_curl_a_200_status_line_whose_body_never_arrives_is_no_answer(real: RealRoute) -> None:
    real.server.mode = "stall"
    proc = real.run()
    assert proc.returncode == 0, _output(proc)
    assert real.get("second") == "none"
    assert "no answer within 2s" in real.get("note")
