"""
Agentic Observability & Automated SRE Triage Engine (ADR-064).

Provides unified access to Loki logs, Grafana Alertmanager, Kubernetes events,
and Slack incident channels for both human engineers and AI agents.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from toolkit.core.logging import logger


def _parse_time_offset(offset: str) -> datetime.timedelta:
    """Parse time offset strings like '5m', '1h', '24h', '30s'."""
    match = re.match(r"^(\d+)([smhd])$", offset.strip().lower())
    if not match:
        return datetime.timedelta(minutes=15)
    val, unit = int(match.group(1)), match.group(2)
    if unit == "s":
        return datetime.timedelta(seconds=val)
    if unit == "m":
        return datetime.timedelta(minutes=val)
    if unit == "h":
        return datetime.timedelta(hours=val)
    if unit == "d":
        return datetime.timedelta(days=val)
    return datetime.timedelta(minutes=15)


def deduplicate_tracebacks(log_lines: list[str]) -> list[str]:
    """
    Deduplicate multi-line Python/Go tracebacks and repeated identical log lines.
    Preserves exact first occurrence and adds occurrence count badges to conserve tokens.
    """
    seen: dict[str, int] = {}
    ordered_unique: list[str] = []

    for line in log_lines:
        # Normalize timestamps and volatile IDs for fingerprinting
        fingerprint = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z?", "", line)
        fingerprint = re.sub(r"0x[0-9a-fA-F]+", "0xADDR", fingerprint).strip()
        if not fingerprint:
            fingerprint = line.strip()

        if fingerprint not in seen:
            seen[fingerprint] = 1
            ordered_unique.append(line)
        else:
            seen[fingerprint] += 1

    result = []
    for line in ordered_unique:
        fingerprint = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z?", "", line)
        fingerprint = re.sub(r"0x[0-9a-fA-F]+", "0xADDR", fingerprint).strip()
        if not fingerprint:
            fingerprint = line.strip()

        count = seen.get(fingerprint, 1)
        if count > 1:
            result.append(f"{line}  [Repeated {count}x]")
        else:
            result.append(line)
    return result


@dataclass
class LokiClient:
    """Client for querying Grafana Loki LogQL streams."""

    base_url: str = field(default_factory=lambda: os.environ.get("LOKI_URL", "http://127.0.0.1:3100"))
    timeout: int = 10

    def query_range(
        self,
        query: str,
        since: str = "15m",
        limit: int = 50,
        direction: str = "BACKWARD",
    ) -> list[dict[str, Any]]:
        """Query Loki log stream using LogQL."""
        now = datetime.datetime.now(datetime.timezone.utc)
        start_time = now - _parse_time_offset(since)

        params = {
            "query": query,
            "start": str(int(start_time.timestamp() * 1e9)),
            "end": str(int(now.timestamp() * 1e9)),
            "limit": str(limit),
            "direction": direction,
        }

        url = f"{self.base_url.rstrip('/')}/loki/api/v1/query_range?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "KubeLab-Toolkit-Observability"})

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning(f"Loki query failed: {e}")
            return []

        entries = []
        if data.get("status") == "success" and "data" in data:
            results = data["data"].get("result", [])
            for stream in results:
                labels = stream.get("stream", {})
                values = stream.get("values", [])
                for ts_ns, line in values:
                    ts_sec = int(ts_ns) / 1e9
                    dt_str = datetime.datetime.fromtimestamp(ts_sec, tz=datetime.timezone.utc).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    entries.append(
                        {
                            "timestamp": dt_str,
                            "container": labels.get("container", labels.get("app", "unknown")),
                            "node": labels.get("node", labels.get("host", "unknown")),
                            "line": line,
                        }
                    )
        return entries

    def query_service_logs(
        self,
        service: str,
        level: str | None = None,
        since: str = "15m",
        limit: int = 50,
    ) -> list[str]:
        """Convenience query for a named service container."""
        selector = f'{{container="{service}"}}'
        if level:
            selector += f' |= "{level.lower()}"'
        entries = self.query_range(query=selector, since=since, limit=limit)
        raw_lines = [f"[{e['timestamp']}] {e['line']}" for e in entries]
        return deduplicate_tracebacks(raw_lines)


@dataclass
class GrafanaAlertClient:
    """Client for checking Grafana Alertmanager firing state."""

    base_url: str = field(default_factory=lambda: os.environ.get("GRAFANA_URL", "https://grafana.kubelab.live"))
    timeout: int = 10

    def get_alerts(self) -> list[dict[str, Any]]:
        """Fetch all active alerts from Grafana."""
        url = f"{self.base_url.rstrip('/')}/api/v1/alerts"
        req = urllib.request.Request(url, headers={"User-Agent": "KubeLab-Toolkit-Observability"})

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning(f"Grafana alert fetch failed: {e}")
            return []

        alerts = []
        if isinstance(data, list):
            for item in data:
                alerts.append(
                    {
                        "name": item.get("name") or item.get("labels", {}).get("alertname", "unknown"),
                        "state": item.get("state", "unknown"),
                        "severity": item.get("labels", {}).get("severity", "info"),
                        "summary": item.get("annotations", {}).get("summary", ""),
                        "runbook_url": item.get("annotations", {}).get("runbook_url", ""),
                        "active_at": item.get("activeAt", ""),
                    }
                )
        return alerts


@dataclass
class SlackSreClient:
    """Client for reading and posting to Slack incident channels."""

    token: str | None = field(default_factory=lambda: os.environ.get("SLACK_BOT_TOKEN"))
    channel_map: dict[str, str] = field(
        default_factory=lambda: {
            "alerts": "C08ALERT123",
            "ops": "C08OPS12345",
            "deployments": "C08DEPLOY12",
        }
    )
    timeout: int = 10

    def post_message(
        self,
        channel: str,
        text: str,
        thread_ts: str | None = None,
    ) -> dict[str, Any]:
        """Post a message or thread reply to a Slack channel."""
        if not self.token:
            logger.info(f"[Mock Slack Post -> #{channel} (thread={thread_ts})]: {text[:80]}...")
            return {"ok": True, "ts": str(datetime.datetime.now().timestamp()), "mock": True}

        channel_id = self.channel_map.get(channel, channel)
        url = "https://slack.com/api/chat.postMessage"
        payload: dict[str, Any] = {"channel": channel_id, "text": text}
        if thread_ts:
            payload["thread_ts"] = thread_ts

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.error(f"Slack postMessage failed: {e}")
            return {"ok": False, "error": str(e)}


@dataclass
class SreTriageEngine:
    """End-to-end automated SRE incident root cause diagnosis engine."""

    loki: LokiClient = field(default_factory=LokiClient)
    grafana: GrafanaAlertClient = field(default_factory=GrafanaAlertClient)
    slack: SlackSreClient = field(default_factory=SlackSreClient)

    def diagnose_service(self, service: str, since: str = "15m") -> dict[str, Any]:
        """Run 4-step diagnostic triage on a service."""
        # 1. Fetch error logs
        logs = self.loki.query_service_logs(service=service, level="error", since=since, limit=20)

        # 2. Check active alerts
        all_alerts = self.grafana.get_alerts()
        matching_alerts = [
            a for a in all_alerts if service in a["name"].lower() or service in a.get("summary", "").lower()
        ]

        # 3. Determine Root Cause
        root_cause = "No active error signatures detected in telemetry window."
        severity = "INFO"
        if logs:
            severity = "WARNING"
            first_error = logs[0]
            if "oom" in first_error.lower() or "137" in first_error:
                root_cause = "Out-Of-Memory (OOMKilled): Container exceeded allocated memory limit."
                severity = "CRITICAL"
            elif "502" in first_error or "connection refused" in first_error.lower():
                root_cause = "Upstream Connection Refused: Backend pod is not accepting traffic on expected port."
                severity = "HIGH"
            elif "timeout" in first_error.lower():
                root_cause = "Downstream Timeout: Network latency or backend thread exhaustion."
            else:
                root_cause = f"Application Exception: {first_error[:120]}"

        # 4. Generate structured report
        report = {
            "service": service,
            "severity": severity,
            "root_cause": root_cause,
            "alerts": matching_alerts,
            "sample_errors": logs[:5],
            "runbook_url": (
                "https://github.com/mlorentedev/kubelab/blob/master/docs/runbooks/runbook-notifications-and-alerting.md"
            ),
            "recommended_action": f"kubectl describe pod -l app.kubernetes.io/name={service} -n kubelab",
        }
        return report
