"""Observability & SRE triage CLI commands (ADR-064)."""

import json
from typing import Annotated, Optional

import typer

from toolkit.core.logging import logger
from toolkit.features.observability import (
    GrafanaAlertClient,
    LokiClient,
    SlackSreClient,
    SreTriageEngine,
)

app = typer.Typer(
    name="obs",
    help="Agentic Observability & SRE triage commands (Loki, Grafana, Slack).",
    no_args_is_help=True,
)


@app.command("logs")
def logs_cmd(
    service: Annotated[
        Optional[str],
        typer.Option("--service", "-s", help="Target service container (e.g. authelia, traefik, api)"),
    ] = None,
    query: Annotated[
        Optional[str],
        typer.Option("--query", "-q", help="Raw LogQL query"),
    ] = None,
    since: Annotated[
        str,
        typer.Option("--since", help="Time range offset (e.g. 5m, 15m, 1h, 24h)"),
    ] = "15m",
    level: Annotated[
        Optional[str],
        typer.Option("--level", "-l", help="Log level filter (e.g. error, warn, info)"),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", "-n", help="Maximum log lines to return"),
    ] = 50,
    json_output: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output results in JSON format"),
    ] = False,
) -> None:
    """Query Loki logs with LogQL filtering and traceback deduplication."""
    client = LokiClient()
    if query:
        entries = client.query_range(query=query, since=since, limit=limit)
        if json_output:
            typer.echo(json.dumps(entries, indent=2))
            return
        lines = [f"[{e['timestamp']}] [{e['container']}@{e['node']}] {e['line']}" for e in entries]
    elif service:
        lines = client.query_service_logs(service=service, level=level, since=since, limit=limit)
        if json_output:
            typer.echo(json.dumps({"service": service, "lines": lines}, indent=2))
            return
    else:
        logger.error("Must specify either --service or --query")
        raise typer.Exit(code=1)

    if not lines:
        typer.echo(f"No logs found matching query in the last {since}.")
        return

    typer.echo(f"--- Telemetry Logs (Window: last {since}, Results: {len(lines)}) ---")
    for line in lines:
        typer.echo(line)


@app.command("alerts")
def alerts_cmd(
    json_output: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output results in JSON format"),
    ] = False,
) -> None:
    """List active Grafana alerts and their firing states."""
    client = GrafanaAlertClient()
    alerts = client.get_alerts()

    if json_output:
        typer.echo(json.dumps(alerts, indent=2))
        return

    if not alerts:
        typer.echo("✓ No firing or pending alerts in Grafana (All healthy).")
        return

    typer.echo("--- Active Grafana Alerts ---")
    for a in alerts:
        state_badge = "[FIRING]" if a["state"] == "alerting" else f"[{a['state'].upper()}]"
        typer.echo(f"{state_badge} {a['name']} (Severity: {a['severity']})")
        if a.get("summary"):
            typer.echo(f"  Summary: {a['summary']}")
        if a.get("runbook_url"):
            typer.echo(f"  Runbook: {a['runbook_url']}")


@app.command("slack")
def slack_cmd(
    channel: Annotated[
        str,
        typer.Option("--channel", "-c", help="Slack channel name (e.g. alerts, ops)"),
    ] = "alerts",
    post: Annotated[
        Optional[str],
        typer.Option("--post", "-p", help="Message text to post to channel"),
    ] = None,
    thread: Annotated[
        Optional[str],
        typer.Option("--thread", "-t", help="Thread timestamp ID to reply to"),
    ] = None,
) -> None:
    """Read or post messages to Slack incident channels."""
    client = SlackSreClient()
    if post:
        resp = client.post_message(channel=channel, text=post, thread_ts=thread)
        if resp.get("ok"):
            typer.echo(f"✓ Message posted to #{channel} (ts={resp.get('ts')})")
        else:
            typer.echo(f"✗ Failed to post message: {resp.get('error')}")
            raise typer.Exit(code=1)
    else:
        typer.echo(f"Slack channel #{channel} connected (Ready for triage posting).")


@app.command("triage")
def triage_cmd(
    service: Annotated[
        str,
        typer.Option("--service", "-s", help="Service to diagnose"),
    ],
    since: Annotated[
        str,
        typer.Option("--since", help="Incident analysis time window"),
    ] = "15m",
    json_output: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output results in JSON format"),
    ] = False,
) -> None:
    """Execute the 4-step automated SRE triage pipeline."""
    engine = SreTriageEngine()
    report = engine.diagnose_service(service=service, since=since)

    if json_output:
        typer.echo(json.dumps(report, indent=2))
        return

    typer.echo("============================================================")
    typer.echo(f"       AUTOMATED SRE INCIDENT DIAGNOSIS: {service.upper()}  ")
    typer.echo("============================================================")
    typer.echo(f"Severity: {report['severity']}")
    typer.echo(f"Root Cause: {report['root_cause']}")
    typer.echo(f"Recommended Action: {report['recommended_action']}")
    typer.echo(f"Runbook: {report['runbook_url']}")

    if report["sample_errors"]:
        typer.echo(f"\nRecent Error Logs ({len(report['sample_errors'])} sample lines):")
        for err in report["sample_errors"]:
            typer.echo(f"  {err}")
