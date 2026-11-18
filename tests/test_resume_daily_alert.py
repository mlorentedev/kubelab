"""resume's no-success alert (RES-HOST-001 G, #2366).

The rule lives in the staging overlay, not in `base/services/grafana-alerting/`: it
alerts on no data, and prod runs no resume yet. The generic alerting guards scan the
base directory only (`ALERTING_DIR`), so they never see it; this module holds the
same properties for this one rule (#3621 tracks making those guards read overlays).

- It reaches Grafana in staging and not in prod (the rendered ConfigMap).
- Silence is the failure: `noDataState` and `execErrState` are `Alerting`.
- Its stream is the one the generated CronJob writes: container and pod prefix are
  read from the staging render, never retyped.
- Its window is the schedule's period plus 2 hours, read from resume's contract
  snapshot. One success per window, by the owner's ruling (RES-HOST-001 F6), where
  the base rules keep a two-sample floor (`tests/test_alerting_emitter_window.py`).
- Run against a real Loki, it counts resume's `daily: ok` lines and nothing else.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest
import yaml

from tests.loki_harness import REPO, Loki, run_loki, slot, stream_labels
from tests.test_alert_runbook_urls import PREFIX, _github_anchor
from tests.test_alerting_emitter_window import _period_minutes

UID = "reshost001-resume-daily-no-success"
RULE_FILE = REPO / "infra/k8s/overlays/staging/grafana-alerting/resume-rules.yaml"
SNAPSHOT = REPO / "infra/config/products/contracts/resume.yaml"
KEY = RULE_FILE.name
#: What `resume daily` prints last on stderr, only on exit 0 (resume #777, #814). A
#: copy by necessity: resume's source is in another repository.
MARKER = "daily: ok"
_UNIT_MINUTES = {"s": 1 / 60, "m": 1, "h": 60, "d": 1440}


def _render(overlay: str) -> list[dict[str, Any]]:
    if shutil.which("kubectl") is None:
        pytest.skip(f"kubectl not on PATH: the {overlay} render was NOT checked")
    out = subprocess.run(
        ["kubectl", "kustomize", str(REPO / "infra/k8s/overlays" / overlay)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def _alerting_keys(overlay: str) -> set[str]:
    [config] = [
        d for d in _render(overlay) if d["kind"] == "ConfigMap" and d["metadata"]["name"].startswith("grafana-alerting")
    ]
    return set(config["data"])


def _rule() -> dict[str, Any]:
    doc = yaml.safe_load(RULE_FILE.read_text(encoding="utf-8"))
    [rule] = [r for g in doc["groups"] for r in g["rules"] if r["uid"] == UID]
    return rule


def _expr(rule: dict[str, Any]) -> str:
    return next(str(d["model"]["expr"]) for d in rule["data"] if d["refId"] == "A")


def _daily_cronjob() -> dict[str, Any]:
    [cronjob] = [
        d
        for d in _render("staging")
        if d["kind"] == "CronJob" and d["metadata"].get("labels", {}).get("app.kubernetes.io/name") == "resume"
    ]
    return cronjob


@pytest.mark.parametrize(("overlay", "present"), [("staging", True), ("prod", False)])
def test_the_rule_reaches_grafana_only_where_resume_runs(overlay: str, present: bool) -> None:
    keys = _alerting_keys(overlay)
    assert "rules.yaml" in keys, f"{overlay}: the merge dropped the base rule files: {sorted(keys)}"
    assert (KEY in keys) is present


def test_silence_and_a_broken_query_both_alert() -> None:
    """A Job that never starts logs nothing: no data is the failure, never health."""
    rule = _rule()
    assert (rule["noDataState"], rule["execErrState"]) == ("Alerting", "Alerting")


def test_the_query_reads_the_stream_the_generated_cronjob_writes() -> None:
    cronjob = _daily_cronjob()
    [container] = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"]
    expr = _expr(_rule())

    assert f'container="{container["name"]}"' in expr
    # A Job's pods are named <cronjob>-<schedule hash>-<suffix>; the container name alone is generic.
    assert f'pod=~"{cronjob["metadata"]["name"]}-.+"' in expr
    assert f'|= "{MARKER}"' in expr


def test_the_window_is_the_schedule_period_plus_two_hours() -> None:
    schedule = yaml.safe_load(SNAPSHOT.read_text(encoding="utf-8"))["resources"]["daily"]["params"]["schedule"]
    assert _daily_cronjob()["spec"]["schedule"] == schedule
    expected = _period_minutes(schedule) + 120
    rule = _rule()

    windows = [int(v) * _UNIT_MINUTES[u] for v, u in re.findall(r"\[(\d+)([smhd])\]", _expr(rule))]
    assert windows == [expected]
    assert {d["relativeTimeRange"]["from"] for d in rule["data"]} == {expected * 60}


# --------------------------------------------------------------------------- against Loki


@pytest.fixture(scope="module")
def loki() -> Iterator[Loki]:
    yield from run_loki()


def _push(loki: Loki, pod: str, lines: list[tuple[int, str]], container: str = "daily") -> None:
    """Plain text lines, as `resume daily` prints them (the harness's own push JSON-encodes)."""
    labels = stream_labels(namespace="kubelab", pod=pod, container=container, node="ace1")
    body = {"streams": [{"stream": labels, "values": [[str(ts * 1_000_000_000), text] for ts, text in lines]}]}
    request = urllib.request.Request(
        f"{loki.url}/loki/api/v1/push", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 204, response.status


HOUR = 3600


def test_a_success_within_the_window_reads_as_one(loki: Loki) -> None:
    t = slot(0) + 2 * 86400
    _push(
        loki, "resume-daily-29000000-abcde", [(t - 25 * HOUR, "daily: started x"), (t - 25 * HOUR + 60, "daily: ok x")]
    )

    assert list(loki.query(_expr(_rule()), t).values()) == [1.0]


def test_a_success_older_than_the_window_is_no_data(loki: Loki) -> None:
    t = slot(1) + 2 * 86400
    _push(loki, "resume-daily-29000001-abcde", [(t - 27 * HOUR, "daily: ok x")])

    assert loki.query(_expr(_rule()), t) == {}


def test_a_failed_run_is_no_data(loki: Loki) -> None:
    """`daily: started` is printed by every run, so only the `ok` line counts."""
    t = slot(2) + 2 * 86400
    _push(
        loki,
        "resume-daily-29000002-abcde",
        [(t - HOUR, "daily: started x"), (t - HOUR + 60, "error: daily: evaluate failed (3 evaluations failed)")],
    )

    assert loki.query(_expr(_rule()), t) == {}


def test_another_products_daily_container_is_not_resumes(loki: Loki) -> None:
    t = slot(3) + 2 * 86400
    _push(loki, "other-daily-29000003-abcde", [(t - HOUR, "daily: ok x")])

    assert loki.query(_expr(_rule()), t) == {}


def test_the_runbook_url_opens_a_committed_section() -> None:
    """`tests/test_alert_runbook_urls.py` checks base rules only; this one is in an overlay."""
    url = _rule()["annotations"]["runbook_url"]
    assert url.startswith(PREFIX), url
    relative, _, anchor = url.removeprefix(PREFIX).partition("#")
    page = REPO / relative
    assert page.is_file(), f"{relative} does not exist"
    headings = re.findall(r"^#+\s+(.+)$", page.read_text(encoding="utf-8"), flags=re.MULTILINE)
    assert anchor in {_github_anchor(h) for h in headings}, f"{relative} has no heading for #{anchor}"
