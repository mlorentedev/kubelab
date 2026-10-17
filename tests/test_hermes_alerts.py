"""The alert channels the triage reads (spec AI-012 AC8, R3).

The channels are declared once in common.yaml and reach the gateway's environment;
`alert-activity.py` reads them with the gateway's bot token. The tests hold the
script to what a triage input is for: a channel that cannot be read must never look
quiet, a credential in an alert must not reach the digest, and the token must not
appear in anything it prints.
"""

from __future__ import annotations

import types
from datetime import UTC, datetime

import pytest
import yaml

from tests.test_agent_stack_role import COMMON, ROLE, _environment, _resolved

SCRIPT = ROLE / "files/hermes-scripts/alert-activity.py"
SLACK = yaml.safe_load(COMMON.read_text())["apps"]["services"]["ai"]["hermes_kubelab"]["slack"]
TOKENS = {"agent_stack_slack_bot_token": "xoxb-sentinel", "agent_stack_slack_app_token": "xapp-sentinel"}
NOW = datetime(2026, 10, 16, 9, 0, tzinfo=UTC).timestamp()
PAIRS = [("C1", "alerts"), ("C2", "ops-log")]


def _script() -> types.ModuleType:
    """Compiled from source, never imported: an import writes a .pyc into the role's files/."""
    module = types.ModuleType("alert_activity")
    exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), module.__dict__)  # noqa: S102
    return module


def _env(**overrides: object) -> dict[str, str]:
    env = _environment()
    text = env.get_template("hermes.env.j2").render(**_resolved(env, **overrides))
    return dict(line.split("=", 1) for line in text.splitlines() if line and not line.startswith("#"))


def _reader(by_channel: dict[str, object]):
    def read(_token: str, channel: str, _oldest: float) -> list[dict]:
        result = by_channel[channel]
        if isinstance(result, Exception):
            raise result
        return result  # type: ignore[return-value]

    return read


def _message(text: str, minutes_ago: int = 5, **extra: object) -> dict:
    return {"ts": f"{NOW - minutes_ago * 60:.6f}", "text": text, **extra}


# ---------------------------------------------------------------- the declaration


def test_the_ssot_declares_the_four_alert_channels_by_id() -> None:
    channels = SLACK["alert_channels"]
    assert [c["name"] for c in channels] == ["ops-log", "alerts", "deployments", "vault-health"]
    assert all(c["id"].startswith("C") and c["id"].isalnum() for c in channels), "IDs, never names"
    assert len({c["id"] for c in channels}) == len(channels)


def test_the_gateway_gets_the_channels_only_with_slack() -> None:
    assert "HERMES_ALERT_CHANNELS" not in _env(), "no Slack, no channel list"
    value = _env(**TOKENS)["HERMES_ALERT_CHANNELS"]
    assert [tuple(pair.split(":")) for pair in value.split(",")] == [
        (c["id"], c["name"]) for c in SLACK["alert_channels"]
    ]


def test_the_channels_do_not_widen_what_the_agent_answers() -> None:
    env = _env(**TOKENS)
    assert env["SLACK_ALLOWED_CHANNELS"] == SLACK["home_channel"]["id"], "reading is not obeying"


def test_the_list_round_trips_through_the_script() -> None:
    value = _env(**TOKENS)["HERMES_ALERT_CHANNELS"]
    assert _script().channels(value) == [(c["id"], c["name"]) for c in SLACK["alert_channels"]]


@pytest.mark.parametrize("raw", ["", " , ,"])
def test_no_channel_parses_to_nothing(raw: str) -> None:
    assert _script().channels(raw) == []


# -------------------------------------------------------------------- the report


def test_a_quiet_hour_skips_the_turn() -> None:
    out = _script().report("t", PAIRS, NOW, read=_reader({"C1": [], "C2": []}))
    assert out.endswith('{"wakeAgent": false}')


def test_an_alert_is_reported_under_its_channel_in_time_order() -> None:
    read = _reader({"C1": [_message("second", 5), _message("first", 20)], "C2": []})
    out = _script().report("t", PAIRS, NOW, read=read)
    assert "wakeAgent" not in out
    assert out.index("## #alerts") < out.index("first") < out.index("second")
    assert "## #ops-log" not in out, "a quiet channel is not listed"


def test_an_unreadable_channel_wakes_the_agent_instead_of_looking_quiet() -> None:
    read = _reader({"C1": RuntimeError("not_in_channel"), "C2": []})
    out = _script().report("t", PAIRS, NOW, read=read)
    assert "wakeAgent" not in out
    assert "#alerts (C1): cannot be read" in out and "not_in_channel" in out


def test_a_network_failure_is_reported_too() -> None:
    read = _reader({"C1": OSError("timed out"), "C2": []})
    assert "cannot be read" in _script().report("t", PAIRS, NOW, read=read)


def test_an_attachment_only_alert_is_read() -> None:
    attachments = [{"title": "[FIRING] DiskFull", "text": "ace1 at 96%"}]
    out = _script().report("t", PAIRS, NOW, read=_reader({"C1": [_message("", attachments=attachments)], "C2": []}))
    assert "DiskFull" in out and "96%" in out


@pytest.mark.parametrize(
    "secret",
    [
        "glsa_" + "A" * 32 + "_abcd1234",
        "ghp_" + "a" * 36,
        "xoxb-1234567890-abcdefghij",
        "authelia_at_" + "x" * 30,
        "Bearer " + "q" * 40,
    ],
)
def test_a_credential_in_an_alert_is_redacted(secret: str) -> None:
    out = _script().report("t", PAIRS, NOW, read=_reader({"C1": [_message(f"leaked {secret} here")], "C2": []}))
    assert secret not in out and "[redacted]" in out


def test_the_report_stays_under_the_cut_and_says_what_it_dropped() -> None:
    many = [_message(f"alert {i} " + "x" * 300, i % 50) for i in range(100)]
    out = _script().report("t", PAIRS, NOW, read=_reader({"C1": many, "C2": []}))
    assert len(out) < 8000
    assert "more in #alerts not shown" in out


def test_the_token_is_never_printed() -> None:
    out = _script().report(
        "xoxb-sentinel-token", PAIRS, NOW, read=_reader({"C1": RuntimeError("invalid_auth"), "C2": []})
    )
    assert "xoxb-sentinel-token" not in out


def test_main_without_a_token_fails_loudly(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.setenv("HERMES_ALERT_CHANNELS", "C1:alerts")
    assert _script().main() == 1
    assert "cannot run" in capsys.readouterr().out


def test_the_triage_job_reads_the_script_hourly_and_only_proposes() -> None:
    job = yaml.safe_load(COMMON.read_text())["apps"]["services"]["ai"]["hermes_kubelab"]["cron"]["jobs"]["alert-triage"]
    assert job["mode"] == "agent"
    assert job["script"] == "alert-activity.py"
    assert job["schedule"].split()[1:] == ["*", "*", "*", "*"], "hourly: the script reads one hour"
    assert "change nothing" in job["prompt"], "the turn proposes; the operator approves fixes"
