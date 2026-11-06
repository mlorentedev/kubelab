"""OBS-033 (#2195): prove the ACME failure rule stays quiet on Traefik's own lines.

`make alert-smoke` proves the rule fires and clears. It cannot prove the rule
stays quiet, and that is the half that pages: Traefik logs `Testing certificate
renew...` about once a day and `Starting provider *acme.Provider` on every boot,
so a rule edit that starts matching either would page prod.

For each of those two lines the check takes the newest one in Loki, evaluates
the rule's own expression one minute after it (so the line sits inside the
rule's window), and requires an empty answer. The expression is read from the
rendered overlay, never copied, so the check runs against whatever the rule says
today. The lines are searched with the rule's own stream selector, so a selector
that no longer sees Traefik finds no line and fails rather than reading quiet.

Three outcomes, each with its own exit code:

- 0, quiet: every anchor line found, and the rule answered empty after each.
- 1, regression: the rule matched Traefik's own line. Only this blames the rule.
- 3, not measured: an anchor line is not within Loki's retention (a Traefik up
  for over a week leaves no boot line), or a real ACME failure shares its
  window (staging's alert-smoke induces those). Neither says anything about the
  rule, and rerunning re-reads the same window, so the report names what moves
  it: the next heartbeat, or the next Traefik restart.

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
#: The lines the rule must never match, each evaluated on its own.
ANCHORS = (HEARTBEAT, BOOT_LINE)
#: Seconds after an anchor line to evaluate at: inside any window over a minute.
EVAL_OFFSET_S = 60
#: How far back to look for an anchor: Loki's `retention_period` (loki.yaml), so
#: a boot line is found whenever Loki still holds one.
LOOKBACK = "168h"
#: Matched lines read back to explain a non-empty answer.
SAMPLE_LIMIT = 500


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
class AnchorResult:
    anchor: str
    measured: bool
    quiet: bool
    reason: str
    at_ns: int | None = None
    matched_lines: list[str] = field(default_factory=list)
    #: The rule matched Traefik's own line. The only answer that blames the rule.
    regression: bool = False

    @property
    def ok(self) -> bool:
        return self.measured and self.quiet


@dataclass(frozen=True)
class QuietResult:
    anchors: list[AnchorResult]

    @property
    def ok(self) -> bool:
        return bool(self.anchors) and all(a.ok for a in self.anchors)

    @property
    def exit_code(self) -> int:
        """0 quiet at every anchor, 1 the rule matched Traefik's own line, 3 not measured."""
        if any(a.regression for a in self.anchors):
            return 1
        return 0 if self.ok else 3


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
    if query["relativeTimeRange"].get("to", 0):
        raise QuietCheckError(f"{RULE_UID}: relativeTimeRange.to offsets Grafana's window; this check cannot follow it")
    if window_s != query["relativeTimeRange"]["from"]:
        raise QuietCheckError(
            f"{RULE_UID}: LogQL window {window_s}s disagrees with relativeTimeRange.from "
            f"{query['relativeTimeRange']['from']}s"
        )
    return RuleQuery(expr=expr, window_s=window_s, selector=selector.group(0), log_query=inner.group(1).strip())


#: What moves an anchor's window forward, so a rerun reads a new one.
NEXT = {HEARTBEAT: "the next heartbeat (about daily)", BOOT_LINE: "the next Traefik restart"}


def verdict(
    anchor: str, anchor_ns: int | None, alert_series: list[dict[str, Any]], matched_lines: list[str]
) -> AnchorResult:
    at_ns = None if anchor_ns is None else anchor_ns + EVAL_OFFSET_S * 10**9
    regression = False
    if anchor_ns is None:
        measured, quiet = False, False
        reason = f"no `{anchor}` line in Loki in the last {LOOKBACK}; rerun after {NEXT[anchor]}"
    elif not alert_series:
        measured, quiet, reason = True, True, "quiet: the line is in the window, the rule answered empty"
    elif any(a in line for a in ANCHORS for line in matched_lines):
        measured, quiet, regression = True, False, True
        reason = "the rule matches Traefik's own line: a regression of the rule, it would page"
    else:
        # Rerunning re-reads the same window, so the advice names what moves it.
        measured, quiet = False, False
        reason = f"a real ACME failure shares this window, so it proves nothing; rerun after {NEXT[anchor]}"
    return AnchorResult(
        anchor, measured, quiet, reason, at_ns=at_ns, matched_lines=matched_lines, regression=regression
    )


def _evaluate(loki: LokiLike, rule: RuleQuery, anchor: str) -> AnchorResult:
    newest = loki.query_range(f'{rule.selector} |= "{anchor}"', since=LOOKBACK, limit=1)
    if not newest:
        return verdict(anchor, None, [], [])
    anchor_ns = int(newest[0]["ts_ns"])
    at_ns = anchor_ns + EVAL_OFFSET_S * 10**9
    series = loki.query_instant(rule.expr, at_ns)
    lines: list[str] = []
    if series:
        start_ns = at_ns - rule.window_s * 10**9
        found = loki.query_range(rule.log_query, start_ns=start_ns, end_ns=at_ns, limit=SAMPLE_LIMIT)
        lines = [e["line"] for e in found]
    return verdict(anchor, anchor_ns, series, lines)


def run_acme_quiet_check(loki: LokiLike, docs: list[dict[str, Any]]) -> QuietResult:
    rule = rule_query(docs)
    return QuietResult([_evaluate(loki, rule, anchor) for anchor in ANCHORS])
