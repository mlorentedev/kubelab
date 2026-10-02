"""Evaluate a Grafana alert rule's LogQL against a real Loki, from fixture lines (BACKUP-032).

An alert rule is code that never runs until it fires, and a rule that cannot
fire looks exactly like one with nothing to report. OBS-018 (#1377) is the
measured case: an `unwrap` over a boolean that Loki could not parse, so every
sample was dropped and `noDataState: Alerting` paged from the first day. Reading
the expression did not catch it; running it would have.

So this runs the pinned `grafana/loki` image, pushes JSON lines with chosen
timestamps, and evaluates a rule's `expr`, **read from the rules YAML, never
retyped**, as an instant query at a chosen time. An instant query at `t` is the
last point of the range query Grafana runs, which is what the rule's `last`
reducer keeps.

Two limits, stated so nobody reads more into a green test than it proves:

- It evaluates the expression, not Grafana's `for:` or `noDataState`. A test
  that needs "held across two probes" evaluates at two times.
- Cases share one Loki, so each takes its own time slot, far enough from the
  others that no rule window reaches across (`slot()`).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
ALERTING_DIR = REPO / "infra/k8s/base/services/grafana-alerting"

# Far enough apart that no rule window (24 h at most today) spans two slots.
SLOT_SECONDS = 3 * 86400
# Slots start in the future, for the reason given at `-validation.create-grace-period`.
_EPOCH = int(time.time()) + 86400


def loki_image() -> str:
    """The image prod runs, from the kustomize `images:` pin, never a second copy."""
    kustomization = yaml.safe_load((REPO / "infra/k8s/base/kustomization.yaml").read_text())
    pin = next(i for i in kustomization["images"] if i["name"] == "grafana/loki")
    return f"grafana/loki:{pin['newTag']}"


def rule_expr(uid: str, ref: str = "A") -> str:
    """A rule's query, verbatim from the rules YAML."""
    for path in sorted(ALERTING_DIR.glob("*.yaml")):
        for group in (yaml.safe_load(path.read_text()) or {}).get("groups") or []:
            for rule in group.get("rules") or []:
                if rule.get("uid") == uid:
                    item = next(d for d in rule["data"] if d["refId"] == ref)
                    return str(item["model"]["expr"])
    raise KeyError(uid)


def slot(index: int) -> int:
    """The start (epoch seconds) of a case's private time slot."""
    return _EPOCH + index * SLOT_SECONDS


class Loki:
    def __init__(self, url: str) -> None:
        self.url = url

    def push(self, labels: dict[str, str], lines: list[tuple[int, dict[str, Any]]]) -> None:
        """Push `(epoch seconds, record)` pairs as one stream, records JSON-encoded as the probe prints them."""
        body = {
            "streams": [
                {
                    "stream": labels,
                    "values": [[str(ts * 1_000_000_000), json.dumps(record, separators=(",", ":"))] for ts, record in lines],
                }
            ]
        }
        request = urllib.request.Request(
            f"{self.url}/loki/api/v1/push",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.status == 204, response.status

    def query(self, expr: str, at: int) -> dict[tuple[tuple[str, str], ...], float]:
        """Instant query at `at`: {sorted label pairs: value}. Raises on a query error,
        which is itself a finding: Grafana treats it as `execErrState`."""
        params = urllib.parse.urlencode({"query": expr, "time": str(at * 1_000_000_000)})
        try:
            with urllib.request.urlopen(f"{self.url}/loki/api/v1/query?{params}", timeout=10) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            raise AssertionError(f"Loki refused the query: {exc.read().decode()[:300]}") from exc
        assert payload["status"] == "success", payload
        return {tuple(sorted(r["metric"].items())): float(r["value"][1]) for r in payload["data"]["result"]}


def _docker_or_skip() -> None:
    if shutil.which("docker") is None:
        # The only proof a rule can fire: in CI a missing docker is a failure, or
        # a runner-image change would turn every rule test into a quiet skip.
        if os.environ.get("CI"):
            pytest.fail("docker not on PATH in CI: the alert rules went unevaluated")
        pytest.skip("docker not on PATH: cannot run Loki (a skip is CANNOT CHECK, not OK)")


def run_loki() -> Iterator[Loki]:
    """Start the pinned Loki on a free local port; yield a client; remove it."""
    _docker_or_skip()
    started = subprocess.run(
        [
            "docker", "run", "-d", "--rm",
            "-p", "127.0.0.1::3100",
            loki_image(),
            "-config.file=/etc/loki/local-config.yaml",
            # Fixture lines carry timestamps from their own slots, which lie in
            # the FUTURE. The querier asks the ingester (where unflushed lines
            # live) only for ranges ending in the last 3 h, and in 3.6.4 neither
            # `-querier.query-ingesters-within` nor `-querier.query-ingester-only`
            # changed that for older ranges (measured: `ingester_requests=0`).
            # Future slots keep every window inside the ingester's range.
            "-validation.create-grace-period=8760h",
        ],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    container = started.stdout.strip()
    try:
        port = subprocess.run(
            ["docker", "port", container, "3100/tcp"], capture_output=True, text=True, check=True
        ).stdout.split(":")[-1].strip()
        url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 90
        while True:
            try:
                with urllib.request.urlopen(f"{url}/ready", timeout=2) as response:
                    if response.status == 200:
                        break
            except (urllib.error.URLError, ConnectionError, OSError):
                pass
            if time.monotonic() > deadline:
                logs = subprocess.run(["docker", "logs", container], capture_output=True, text=True).stderr[-800:]
                pytest.fail(f"Loki did not become ready in 90 s: {logs}")
            time.sleep(1)
        yield Loki(url)
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)
