"""OBS-033 (#2195): prove the ACME failure rule stays quiet on Traefik's heartbeat.

`make alert-smoke` proves the rule fires and clears. It cannot prove the rule
stays quiet, and that is the half that pages: Traefik logs `Testing certificate
renew...` about once a day and `Starting provider *acme.Provider` on every boot,
so a rule edit that starts matching either would page prod daily.

The check takes the newest heartbeat in Loki, evaluates the rule's own
expression one minute after it (so the heartbeat sits inside the rule's window),
and requires an empty answer. The expression is read from the rendered overlay,
never copied, so the check runs against whatever the rule says today.

Two answers are not "quiet", and both fail:

- No heartbeat found, or the rule's stream selector does not see it in the
  window: an empty result from a selector that sees nothing proves nothing.
- A non-empty result. The matching lines are read back so the report can say
  whether the rule matched the heartbeat (a regression of the rule) or a real
  ACME failure happened in the window (staging's alert-smoke induces those):
  the two call for opposite actions.

Read-only, so it runs in prod as well as staging.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import yaml

RULE_UID = "obs007-acme-failure"
CONFIGMAP_PREFIX = "grafana-alerting"
HEARTBEAT = "Testing certificate renew"
BOOT_LINE = "Starting provider *acme.Provider"
#: Seconds after the heartbeat to evaluate at: inside any window over a minute.
EVAL_OFFSET_S = 60
#: How far back to look for a heartbeat. Traefik logs one about every 24h.
HEARTBEAT_LOOKBACK = "48h"


class QuietCheckError(RuntimeError):
    """The rule could not be read, so nothing was measured."""


class LokiLike(Protocol):
    def query_range(
        self,
        query: str,
        since: str = ...,
        limit: int = ...,
        direction: str = ...,
        start_ns: int | None = ...,
        end_ns: int | None = ...,
    ) -> list[dict[str, Any]]: ...

    def query_instant(self, query: str, at_ns: int) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class RuleQuery:
    expr: str
    window_s: int
    selector: str
    #: The expression's log pipeline, to read back the lines it matched.
    log_query: str


@dataclass(frozen=True)
class QuietResult:
    measured: bool
    quiet: bool
    reason: str
    heartbeat_ns: int | None = None
    heartbeats_in_window: int = 0
    boot_lines_in_window: int = 0
    matched_lines: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.measured and self.quiet


def _find_rule(docs: list[dict[str, Any]]) -> dict[str, Any]:
    for doc in docs:
        if doc.get("kind") != "ConfigMap" or not doc["metadata"]["name"].startswith(CONFIGMAP_PREFIX):
            continue
        for text in (doc.get("data") or {}).values():
            for group in (yaml.safe_load(text) or {}).get("groups", []):
                for rule in group.get("rules", []):
                    if rule.get("uid") == RULE_UID:
                        return rule
    raise QuietCheckError(f"rule {RULE_UID} not found in the rendered {CONFIGMAP_PREFIX} ConfigMap")


def rule_query(docs: list[dict[str, Any]]) -> RuleQuery:
    """The rule's expression and window, from rendered overlay documents."""
    query = next(d for d in _find_rule(docs)["data"] if d.get("refId") == "A")
    expr = query["model"]["expr"].strip()
    inner = re.search(r"count_over_time\((.*)\[(\d+)m\]\s*\)", expr, re.DOTALL)
    selector = re.search(r"\{[^{}]*\}", expr)
    if not inner or not selector:
        raise QuietCheckError(f"cannot read the window and selector of {RULE_UID}: {expr}")
    window_s = int(inner.group(2)) * 60
    if window_s != query["relativeTimeRange"]["from"]:
        raise QuietCheckError(
            f"{RULE_UID}: LogQL window {window_s}s disagrees with relativeTimeRange.from "
            f"{query['relativeTimeRange']['from']}s"
        )
    return RuleQuery(expr=expr, window_s=window_s, selector=selector.group(0), log_query=inner.group(1).strip())


def verdict(
    heartbeat_ns: int | None,
    heartbeats_in_window: int,
    alert_series: list[dict[str, Any]],
    matched_lines: list[str],
    boot_lines_in_window: int = 0,
) -> QuietResult:
    if heartbeat_ns is None:
        measured, quiet, reason = False, False, f"no heartbeat in Loki in the last {HEARTBEAT_LOOKBACK}"
    elif heartbeats_in_window < 1:
        measured, quiet, reason = False, False, "the rule's selector does not see the heartbeat in its window"
    elif not alert_series:
        measured, quiet, reason = True, True, "quiet: heartbeat in the window, rule answered empty"
    elif any(HEARTBEAT in line or BOOT_LINE in line for line in matched_lines):
        measured, quiet = True, False
        reason = "the rule matches the heartbeat: a regression of the rule, it would page daily"
    else:
        measured, quiet, reason = True, False, "a real ACME failure is in the window; rerun once it ages out"
    return QuietResult(
        measured,
        quiet,
        reason,
        heartbeat_ns=heartbeat_ns,
        heartbeats_in_window=heartbeats_in_window,
        boot_lines_in_window=boot_lines_in_window,
        matched_lines=matched_lines,
    )


def _count(loki: LokiLike, query: str, at_ns: int) -> int:
    return sum(int(float(s["value"][1])) for s in loki.query_instant(query, at_ns))


def run_acme_quiet_check(loki: LokiLike, docs: list[dict[str, Any]]) -> QuietResult:
    rule = rule_query(docs)
    newest = loki.query_range(f'{rule.selector} |= "{HEARTBEAT}"', since=HEARTBEAT_LOOKBACK, limit=1)
    if not newest:
        return verdict(None, 0, [], [])
    heartbeat_ns = int(newest[0]["ts_ns"])
    at_ns = heartbeat_ns + EVAL_OFFSET_S * 10**9
    window = f"[{rule.window_s}s]"
    heartbeats = _count(loki, f'sum(count_over_time({rule.selector} |= "{HEARTBEAT}" {window}))', at_ns)
    boots = _count(loki, f'sum(count_over_time({rule.selector} |= "{BOOT_LINE}" {window}))', at_ns)
    series = loki.query_instant(rule.expr, at_ns)
    lines: list[str] = []
    if series:
        start_ns = at_ns - rule.window_s * 10**9
        lines = [e["line"] for e in loki.query_range(rule.log_query, start_ns=start_ns, end_ns=at_ns, limit=20)]
    return verdict(heartbeat_ns, heartbeats, series, lines, boot_lines_in_window=boots)
