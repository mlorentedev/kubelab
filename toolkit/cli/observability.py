"""Observability & SRE triage CLI commands (ADR-064)."""

from __future__ import annotations

import json
import os
from contextlib import ExitStack, contextmanager
from typing import Annotated, Generator, Optional

import typer

from toolkit.core.logging import logger
from toolkit.features.k8s_kubeconfig import output_path as kubeconfig_path
from toolkit.features.observability import (
    AlertsUnavailableError,
    GrafanaAlertClient,
    LogsUnavailableError,
    LokiClient,
    ObservabilityUnavailableError,
    SlackSreClient,
    SreTriageEngine,
    kubectl_service_port_forward,
    read_cluster_secret_key,
)
from toolkit.features.pvc_drill import (
    DEFAULT_TIMEOUT_S,
    DRILL_ALERT_NAME,
    DRILL_NAMESPACE,
    DRILL_PVC_NAME,
    DrillTeardownError,
    apply_pvc,
    delete_pvc,
    drill_pvc_manifest,
    pvc_exists,
    run_drill,
)

app = typer.Typer(
    name="obs",
    help="Agentic Observability & SRE triage commands (Loki, Grafana, Slack).",
    no_args_is_help=True,
)


@app.command("logs")
def logs_cmd(
    env: Annotated[
        str,
        typer.Option("--env", "-e", help="Cluster to query (staging|prod) — ADR-028: prod is the monitoring of record"),
    ] = "prod",
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
    try:
        with _loki_client(env) as client:
            _query_loki(client, query, service, since, level, limit, json_output)
    except LogsUnavailableError as exc:
        # "No logs found in the last 15m" is a statement about Loki's answer.
        # This is the absence of one, and the two must not read alike.
        if json_output:
            typer.echo(json.dumps({"error": str(exc), "lines": None}, indent=2))
        else:
            typer.echo(f"✗ Could not ask Loki: {exc}", err=True)
            typer.echo("  This is NOT 'no logs' — the query never landed.", err=True)
        raise typer.Exit(1) from exc


def _query_loki(
    client: LokiClient,
    query: str | None,
    service: str | None,
    since: str,
    level: str | None,
    limit: int,
    json_output: bool,
) -> None:
    """The body of `logs`, extracted so the caller can wrap it in one try.

    Kept as a private helper rather than inlined: the failure being caught is
    Loki being unreachable, and that can happen on either branch below. Wrapping
    the whole body is the only shape where a new branch cannot silently escape
    the guard.
    """
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
        # Name the Loki that was asked. The two failure modes above are already
        # kept apart -- "unreachable" vs "no logs" -- but a THIRD reads exactly
        # like the second and was not covered: a reachable Loki that is not the
        # one you meant answers `status: success` with an empty result, and this
        # sentence then reports its silence as though it were prod's.
        #
        # Measured 2026-09-01: `--service crowdsec --since 15m` printed "No logs
        # found" while prod's Loki held 20 matching lines in that window. There
        # is no `--env` flag; `base_url` defaults to 127.0.0.1:3100, and a dev
        # Loki was listening there. An hour went into re-measuring prod before
        # the port was the suspect. Printing the URL makes that one glance.
        typer.echo(f"No logs found matching query in the last {since} (asked {client.base_url}).")
        return

    typer.echo(f"--- Telemetry Logs (Source: {client.base_url}, Window: last {since}, Results: {len(lines)}) ---")
    for line in lines:
        typer.echo(line)


@contextmanager
def _loki_client(env: str) -> Generator[LokiClient, None, None]:
    """Yield a client pointed at the named environment's Loki.

    Mirrors `_grafana_client` below, for the same reason and by the same route:
    prod's Loki has no public hostname at all (its overlay serves
    `loki.internal.kubelab.local`, a non-public TLD ACME cannot certify), so a
    transient `kubectl port-forward` and kubeconfig access are the trust
    boundary rather than the edge.

    This command had no `--env` until 2026-09-01 while its sibling `alerts` did.
    `LokiClient()` defaults to `127.0.0.1:3100`, so it asked whatever happened
    to be listening there — a dev Loki, on the machine where this was measured —
    and reported that instance's silence as the answer. Unlike an unreachable
    Loki, which already raised, a *wrong* Loki answers `status: success` with an
    empty result and is indistinguishable from a quiet service.

    `LOKI_URL` stays the direct-URL escape hatch, matching `GRAFANA_URL`.
    """
    if os.environ.get("LOKI_URL"):
        yield LokiClient()
        return
    # The `try` covers the port-forward SETUP and nothing else, and the `yield`
    # deliberately sits outside it. In a `@contextmanager`, an exception raised
    # in the caller's `with` body is re-injected into this generator AT THE
    # YIELD -- so a `try` spanning the yield catches the consumer's failures and
    # relabels them as this backend's. That is not hypothetical: with the yield
    # inside, a plain `RuntimeError` from `SreTriageEngine.diagnose_service`
    # surfaced as "could not reach Loki in prod: ..." while Loki was fine, and
    # an operator reading the first clause goes to debug a healthy backend --
    # the exact misattribution TOOL-055 exists to remove, reproduced one level
    # up. An earlier revision tried to fix this with `except
    # ObservabilityUnavailableError: raise`, which only ever covered the
    # subclass; every OTHER RuntimeError still went out mislabelled. The guard
    # has to be structural: the body is not inside the `try` at all.
    with ExitStack() as stack:
        try:
            port = stack.enter_context(kubectl_service_port_forward(env, "loki", 3100))
        except ObservabilityUnavailableError:
            # Already names its backend -- re-wrapping would RE-ATTRIBUTE it.
            raise
        except (RuntimeError, TimeoutError) as exc:
            raise LogsUnavailableError(f"could not reach Loki in {env}: {exc}") from exc
        yield LokiClient(base_url=f"http://127.0.0.1:{port}")


@contextmanager
def _grafana_client(env: str) -> Generator[GrafanaAlertClient, None, None]:
    """Yield a client already pointed at a reachable, authenticated Grafana.

    OBS-019: the public hostname sits behind Authelia, and the toolkit has no
    browser session — so unless `GRAFANA_URL` is set as a direct-URL escape
    hatch (manual override, or a future in-mesh address), this reaches Grafana
    through a transient `kubectl port-forward`, using kubeconfig access as the
    trust boundary instead of the edge. Any transport failure surfaces as
    `AlertsUnavailableError`, same as an HTTP failure — a blind check must fail
    loudly regardless of which half of the path went blind.
    """
    if os.environ.get("GRAFANA_URL"):
        yield GrafanaAlertClient()
        return
    # Setup inside the `try`, `yield` outside it -- see `_loki_client` for why
    # a `try` spanning the yield converts a consumer's failure into this
    # backend's.
    with ExitStack() as stack:
        try:
            port = stack.enter_context(kubectl_service_port_forward(env, "grafana", 3000))
            token = read_cluster_secret_key(env, "grafana-admin", "alerts-ro-token") or ""
        except ObservabilityUnavailableError:
            raise
        except (RuntimeError, TimeoutError) as exc:
            raise AlertsUnavailableError(f"could not reach Grafana in {env}: {exc}") from exc
        yield GrafanaAlertClient(base_url=f"http://127.0.0.1:{port}", token=token)


@app.command("alerts")
def alerts_cmd(
    env: Annotated[
        str,
        typer.Option("--env", "-e", help="Cluster to query (staging|prod) — ADR-028: prod is the monitoring of record"),
    ] = "prod",
    json_output: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output results in JSON format"),
    ] = False,
) -> None:
    """List active Grafana alerts and their firing states."""
    try:
        with _grafana_client(env) as client:
            alerts = client.get_alerts()
    except AlertsUnavailableError as exc:
        # A blind check must not read as a healthy one, in either output mode.
        # `--json` gets an OBJECT rather than `[]` for the same reason: a machine
        # consumer parsing an empty array concludes "no alerts", which is exactly
        # the wrong conclusion and the one this command used to print.
        if json_output:
            typer.echo(json.dumps({"error": str(exc), "alerts": None}, indent=2))
        else:
            typer.echo(f"✗ Could not ask Grafana: {exc}", err=True)
            typer.echo("  This is NOT 'no alerts' — the question went unanswered.", err=True)
        raise typer.Exit(1) from exc

    if json_output:
        typer.echo(json.dumps(alerts, indent=2))
        return

    if not alerts:
        typer.echo("✓ No firing or pending alerts in Grafana (asked and answered).")
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
    env: Annotated[
        str,
        typer.Option("--env", "-e", help="Cluster to query (staging|prod) — ADR-028: prod is the monitoring of record"),
    ] = "prod",
    since: Annotated[
        str,
        typer.Option("--since", help="Incident analysis time window"),
    ] = "15m",
    json_output: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output results in JSON format"),
    ] = False,
) -> None:
    """Execute the 4-step automated SRE triage pipeline.

    TOOL-055: this built both clients from `default_factory` until 2026-09-02,
    while its siblings `logs` and `alerts` had already been given `--env` and a
    port-forward transport. So it asked `127.0.0.1:3100` for logs and the default
    URL for alerts.

    That is worse here than in `logs`, and the difference is the reason this
    command is the one that mattered. `obs logs` against the wrong Loki prints
    "No logs found" — wrong, but visibly a non-answer. `diagnose_service` turns
    the same emptiness into `severity: INFO` and "No active error signatures
    detected in telemetry window": an assertion of health, sourced from a Loki
    it never contacted. Measured 2026-09-01, `0.0.0.0:3100` on this workstation
    was held by an unrelated local Loki, so the wrong answer was the default
    state of the machine the command runs from.

    Both halves are threaded now. The port-forwards must stay open for the whole
    diagnosis, so the engine is built and run inside both context managers rather
    than handed clients that outlive their tunnel.
    """
    try:
        with _loki_client(env) as loki, _grafana_client(env) as grafana:
            engine = SreTriageEngine(loki=loki, grafana=grafana)
            report = engine.diagnose_service(service=service, since=since)
    except (LogsUnavailableError, AlertsUnavailableError) as exc:
        # A diagnosis is the one output that must never be produced from a source
        # that was not reached. `logs` and `alerts` already refuse to render a
        # blind check as a healthy one; this refuses to render it as a VERDICT,
        # which is the same rule with more at stake.
        #
        # `--json` gets `severity: null`, not "INFO", for the machine consumer
        # that would otherwise read a missing key as benign.
        if json_output:
            typer.echo(json.dumps({"error": str(exc), "service": service, "severity": None, "report": None}, indent=2))
        else:
            typer.echo(f"✗ Could not triage {service} in {env}: {exc}", err=True)
            typer.echo("  This is NOT a clean bill of health — a source went unread.", err=True)
        raise typer.Exit(1) from exc

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


@app.command("drill-pvc-unbound")
def drill_pvc_unbound_cmd(
    env: Annotated[
        str,
        typer.Option(
            "--env",
            "-e",
            help=(
                "Cluster to drill. Against prod this fires a REAL alert into the "
                "operator's channel — that is what a drill does, but do it knowingly."
            ),
        ),
    ] = "staging",
    timeout_minutes: Annotated[
        int,
        typer.Option(
            "--timeout-minutes",
            help="How long to wait for the alert. The rule needs ~45m worst case.",
        ),
    ] = DEFAULT_TIMEOUT_S // 60,
) -> None:
    """Prove `obs015-pvc-unbound-failure` fires, and remove the claim afterwards.

    The removal is not a second command and not a runbook step: it is a
    `finally` in the same call, so interrupting the wait still cleans up. See
    `toolkit/features/pvc_drill.py` for why that matters (#1583).
    """
    kubeconfig = str(kubeconfig_path(env))
    manifest = drill_pvc_manifest()

    with _grafana_client(env) as client:
        try:
            result = run_drill(
                exists=lambda: pvc_exists(kubeconfig, DRILL_PVC_NAME, DRILL_NAMESPACE),
                create=lambda: apply_pvc(kubeconfig, manifest, DRILL_NAMESPACE),
                delete=lambda: delete_pvc(kubeconfig, DRILL_PVC_NAME, DRILL_NAMESPACE),
                fetch_alerts=client.get_alerts,
                timeout_s=timeout_minutes * 60,
                log=typer.echo,
            )
        except DrillTeardownError as exc:
            # The one failure that leaves the cluster worse than it found it.
            typer.echo(f"✗ {exc}", err=True)
            raise typer.Exit(2) from exc

    if result.absorbed_residue:
        typer.echo("  (a claim from an earlier run was present and has been cleared)")

    if not result.fired:
        typer.echo(
            f"✗ {DRILL_ALERT_NAME} did not fire within {timeout_minutes}m. "
            "The claim is gone; the rule is what needs looking at.",
            err=True,
        )
        raise typer.Exit(1)

    typer.echo(
        f"✓ {DRILL_ALERT_NAME} fired and the claim is removed. "
        "The alert instance resolves on its own in roughly 30-45m — "
        "the rule reads a [30m] window on a 15m interval."
    )
