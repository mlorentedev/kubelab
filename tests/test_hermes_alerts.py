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
HERMES = yaml.safe_load(COMMON.read_text())["apps"]["services"]["ai"]["hermes_kubelab"]
SLACK = HERMES["slack"]
TOKENS = {"agent_stack_slack_bot_token": "xoxb-sentinel", "agent_stack_slack_app_token": "xapp-sentinel"}
# Hermes v0.22.1 builds a job script's environment with `build_subprocess_env`, which drops these two
# names whatever `env_passthrough` says (`_ALWAYS_STRIP_FOLDED`, measured on ace2 2026-10-17, lesson-592).
STRIPPED_FROM_JOB_SCRIPTS = ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN")
NOW = datetime(2026, 10, 16, 9, 0, tzinfo=UTC).timestamp()
PAIRS = [("C1", "alerts"), ("C2", "ops-log")]


def _script() -> types.ModuleType:
    """Compiled from source, never imported: an import writes a .pyc into the role's files/."""
    module = types.ModuleType("alert_activity")
    module.__dict__["__file__"] = str(SCRIPT)
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


def test_the_script_reads_its_token_under_a_name_hermes_hands_to_a_job_script() -> None:
    """The gateway holds SLACK_BOT_TOKEN, and Hermes strips it from every child it spawns, so a script
    that reads that name sees an empty string and the hourly triage reports a config gap forever."""
    source = SCRIPT.read_text()
    for name in STRIPPED_FROM_JOB_SCRIPTS:
        assert f'"{name}"' not in source, f"{name} never reaches a job script"
    env = _env(**TOKENS)
    assert env["HERMES_ALERT_SLACK_TOKEN"] == TOKENS["agent_stack_slack_bot_token"]
    assert "HERMES_ALERT_SLACK_TOKEN" in source


def test_the_script_token_exists_only_with_slack_and_channels() -> None:
    assert "HERMES_ALERT_SLACK_TOKEN" not in _env(), "no Slack, no token"
    assert "HERMES_ALERT_SLACK_TOKEN" not in _env(
        **TOKENS, agent_stack_hermes={**HERMES, "slack": {**SLACK, "alert_channels": []}}
    ), "a token for a script nothing runs is a credential for nothing"


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


def test_a_block_kit_attachment_is_read_not_its_placeholder() -> None:
    """Argo CD's webhook posts blocks and Slack fills `fallback` with a placeholder (measured on #deployments,
    2026-10-17): reporting that made the triage ask what a healthy sync said."""
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "Sync Succeeded"}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": "*App:*\nkubelab-prod"},
                {"type": "mrkdwn", "text": "*Revision:*\n92c0d03"},
            ],
        },
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "<https://argo.example/app|Open>"}]},
    ]
    attachments = [{"blocks": blocks, "fallback": "[no preview available]"}]
    out = _script().report("t", PAIRS, NOW, read=_reader({"C1": [_message("", attachments=attachments)], "C2": []}))
    assert "Sync Succeeded" in out and "kubelab-prod" in out and "92c0d03" in out
    assert "no preview available" not in out


def test_the_placeholder_is_only_a_last_resort() -> None:
    attachments = [{"fallback": "[no preview available]"}]
    out = _script().report("t", PAIRS, NOW, read=_reader({"C1": [_message("", attachments=attachments)], "C2": []}))
    assert "no preview available" in out, "a message with nothing else still shows up"


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
    monkeypatch.delenv("HERMES_ALERT_SLACK_TOKEN", raising=False)
    monkeypatch.setenv("HERMES_ALERT_CHANNELS", "C1:alerts")
    monkeypatch.delenv("HERMES_HOME", raising=False)
    assert _script().main() == 1
    assert "cannot run" in capsys.readouterr().out


def test_the_triage_job_reads_the_script_hourly_and_only_proposes() -> None:
    job = yaml.safe_load(COMMON.read_text())["apps"]["services"]["ai"]["hermes_kubelab"]["cron"]["jobs"]["alert-triage"]
    assert job["mode"] == "agent"
    assert job["script"] == "alert-activity.py"
    assert job["schedule"].split()[1:] == ["*", "*", "*", "*"], "hourly: the script reads one hour"
    assert "change nothing" in job["prompt"], "the turn proposes; the operator approves fixes"


# ------------------------------------------------- said once, then again every six hours


def _alert(pr: int, started: str) -> dict:
    return _message(f"firing: reviewer failed on pulls/{pr} Started: 2026-10-18 {started}:20 +0000 UTC")


def test_an_alert_that_repeats_is_not_reported_again_for_six_hours() -> None:
    script = _script()
    seen: dict[str, float] = {}
    first = script.report("t", PAIRS, NOW, read=_reader({"C1": [_alert(559, "04:21")], "C2": []}), seen=seen)
    assert "pulls/559" in first
    # The next hour: the same alert, reposted by Grafana with a new start time.
    later = NOW + 3600
    again = script.report("t", PAIRS, later, read=_reader({"C1": [_alert(559, "05:21")], "C2": []}), seen=seen)
    assert again.endswith('{"wakeAgent": false}'), "an unchanged alert woke the agent a second time"


def test_a_different_pull_request_is_a_different_alert() -> None:
    script = _script()
    seen: dict[str, float] = {}
    script.report("t", PAIRS, NOW, read=_reader({"C1": [_alert(559, "04:21")], "C2": []}), seen=seen)
    out = script.report("t", PAIRS, NOW + 3600, read=_reader({"C1": [_alert(576, "05:21")], "C2": []}), seen=seen)
    assert "pulls/576" in out and "wakeAgent" not in out


def test_a_new_alert_is_reported_and_says_how_many_were_left_out() -> None:
    script = _script()
    seen: dict[str, float] = {}
    script.report("t", PAIRS, NOW, read=_reader({"C1": [_alert(559, "04:21")], "C2": []}), seen=seen)
    both = [_alert(559, "05:21"), _alert(576, "05:21")]
    out = script.report("t", PAIRS, NOW + 3600, read=_reader({"C1": both, "C2": []}), seen=seen)
    assert "pulls/576" in out and "pulls/559" not in out
    assert "1 more message(s) repeat something already reported" in out


def test_an_alert_that_outlasts_the_window_is_said_again() -> None:
    script = _script()
    seen: dict[str, float] = {}
    script.report("t", PAIRS, NOW, read=_reader({"C1": [_alert(559, "04:21")], "C2": []}), seen=seen)
    out = script.report(
        "t", PAIRS, NOW + script.REPEAT, read=_reader({"C1": [_alert(559, "10:21")], "C2": []}), seen=seen
    )
    assert "pulls/559" in out, "a problem left open for six hours must come back"


def test_an_unreadable_channel_is_said_once_not_every_hour() -> None:
    script = _script()
    seen: dict[str, float] = {}
    read = _reader({"C1": RuntimeError("not_in_channel"), "C2": []})
    assert "cannot be read" in script.report("t", PAIRS, NOW, read=read, seen=seen)
    assert script.report("t", PAIRS, NOW + 3600, read=read, seen=seen).endswith('{"wakeAgent": false}')
    assert "cannot be read" in script.report("t", PAIRS, NOW + script.REPEAT, read=read, seen=seen)


def test_a_message_cut_by_the_budget_is_not_marked_as_reported() -> None:
    script = _script()
    seen: dict[str, float] = {}
    many = [_message(f"alert number {n} " + "x" * 300, n) for n in range(1, 60)]
    out = script.report("t", PAIRS, NOW, read=_reader({"C1": many, "C2": []}), seen=seen)
    shown = out.count("alert number")
    assert "not shown" in out and len(seen) == shown, "an unseen message was recorded as said"


def test_without_a_memory_everything_is_reported() -> None:
    script = _script()
    read = _reader({"C1": [_alert(559, "04:21")], "C2": []})
    assert "pulls/559" in script.report("t", PAIRS, NOW, read=read)
    assert "pulls/559" in script.report("t", PAIRS, NOW + 60, read=read)


def test_the_memory_keeps_hashes_not_alert_text(tmp_path) -> None:
    script = _script()
    path = tmp_path / "state" / "alert-activity.json"
    seen: dict[str, float] = {}
    script.report("t", PAIRS, NOW, read=_reader({"C1": [_alert(559, "04:21")], "C2": []}), seen=seen)
    script.save_seen(path, seen)
    assert "pulls" not in path.read_text() and "reviewer" not in path.read_text()
    assert script.load_seen(path, NOW + 60) == seen
    assert script.load_seen(path, NOW + script.REPEAT + 1) == {}, "an old entry outlived the window"


def test_a_corrupt_or_unwritable_memory_never_stops_the_report(tmp_path) -> None:
    script = _script()
    bad = tmp_path / "state.json"
    bad.write_text("{not json")
    assert script.load_seen(bad, NOW) == {}
    blocker = tmp_path / "file"
    blocker.write_text("x")
    script.save_seen(blocker / "state" / "x.json", {"a": NOW})  # parent is a file: must not raise


def test_a_persistent_misconfiguration_is_reported_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path
) -> None:
    monkeypatch.delenv("HERMES_ALERT_SLACK_TOKEN", raising=False)
    monkeypatch.setenv("HERMES_ALERT_CHANNELS", "C1:alerts")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    script = _script()
    assert script.main() == 1 and "cannot run" in capsys.readouterr().out
    assert script.main() == 0, "the second hour woke the agent for the same configuration error"
    assert '{"wakeAgent": false}' in capsys.readouterr().out


def test_the_triage_prompt_forbids_guessing_and_merging_distinct_problems() -> None:
    job = yaml.safe_load(COMMON.read_text())["apps"]["services"]["ai"]["hermes_kubelab"]["cron"]["jobs"]["alert-triage"]
    prompt = " ".join(job["prompt"].split())
    assert "different problems" in prompt and "duplicates only when the identifier matches" in prompt
    assert "do not guess its cause" in prompt and "you have no Slack tool" in prompt


def test_the_memory_lives_next_to_the_scripts_directory_when_hermes_home_is_scrubbed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.delenv("HERMES_HOME", raising=False)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    module = types.ModuleType("alert_activity_mounted")
    module.__dict__["__file__"] = str(scripts / "alert-activity.py")
    exec(compile(SCRIPT.read_text(), str(scripts / "alert-activity.py"), "exec"), module.__dict__)  # noqa: S102
    assert module._state_path() == tmp_path / "state" / "alert-activity.json"
    assert _script()._state_path() is None, "run from the repo, the memory must not land in the role's files/"
