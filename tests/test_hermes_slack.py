"""hermes-kubelab's Slack gateway (ADR-068 D3, spec AI-009 PR 3c, AC10).

Hermes v2026.9.24 obeys a Slack user only when `SLACK_ALLOWED_USERS` names
them (`gateway/authz_mixin.py`, `_principal_authorized`). With no allowlist it
falls back to pairing codes, or to everyone under `*_ALLOW_ALL_USERS`. So the
allowlist comes from the SSOT, an empty one starts no Slack at all, and an
unknown DM is dropped rather than answered with a code.
"""

from __future__ import annotations

import pytest
import yaml

from tests.test_agent_stack_role import COMMON, ROLE, _environment, _resolved, _tasks

SLACK = yaml.safe_load(COMMON.read_text())["apps"]["services"]["ai"]["hermes_kubelab"]["slack"]
TOKENS = {"agent_stack_slack_bot_token": "xoxb-sentinel", "agent_stack_slack_app_token": "xapp-sentinel"}
OPEN_SWITCHES = ("SLACK_ALLOW_ALL_USERS", "GATEWAY_ALLOW_ALL_USERS")


def _render(name: str, **overrides: object) -> str:
    env = _environment()
    return env.get_template(name).render(**_resolved(env, **overrides))


def _env(**overrides: object) -> dict[str, str]:
    lines = _render("hermes.env.j2", **overrides).splitlines()
    return dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))


def _config(**overrides: object) -> dict:
    return yaml.safe_load(_render("hermes-config.yaml.j2", **overrides))


def _without_allowlist() -> dict:
    """The operator's actual input when nobody is listed: an empty list, so a
    mutated gate renders the tokens instead of failing on a missing key."""
    hermes = _resolved(_environment())["agent_stack_hermes"]
    return {**TOKENS, "agent_stack_hermes": {**hermes, "slack": {**SLACK, "allowed_users": []}}}


# --------------------------------------------------------------------------- the gate


def test_the_ssot_names_at_least_one_user_and_the_home_channel() -> None:
    assert SLACK["allowed_users"], "an empty list starts no Slack"
    assert all(user.startswith("U") for user in SLACK["allowed_users"]), "member IDs, not names"
    assert SLACK["home_channel"]["id"].startswith("C")


def test_slack_starts_only_with_both_tokens_and_an_allowlist() -> None:
    assert "SLACK_BOT_TOKEN" not in _env(), "no tokens, no Slack"
    assert "SLACK_BOT_TOKEN" not in _env(agent_stack_slack_bot_token="xoxb-sentinel"), "Socket Mode needs both"
    assert "SLACK_BOT_TOKEN" in _env(**TOKENS)


def test_an_empty_allowlist_starts_no_slack_rather_than_an_open_one() -> None:
    env = _env(**_without_allowlist())
    assert not [key for key in env if key.startswith("SLACK_")], env


@pytest.mark.parametrize(
    "overrides",
    [{}, TOKENS, {"agent_stack_slack_bot_token": "xoxb-sentinel"}, _without_allowlist()],
    ids=["no-tokens", "configured", "bot-token-only", "no-allowlist"],
)
def test_no_role_input_opens_the_gateway_to_everyone(overrides: dict) -> None:
    """Open means a token with no allowlist, or an allow-all switch. Either way
    Hermes answers someone the SSOT does not name."""
    env = _env(**overrides)
    if "SLACK_BOT_TOKEN" in env:
        assert env.get("SLACK_ALLOWED_USERS"), "a token with no allowlist is an open gateway"
    rendered = _render("hermes.env.j2", **overrides) + _render("hermes-config.yaml.j2", **overrides)
    for switch in OPEN_SWITCHES:
        assert switch not in rendered


# --------------------------------------------------------------------------- what it renders


def test_the_allowlist_and_the_home_channel_come_from_the_ssot() -> None:
    env = _env(**TOKENS)
    assert env["SLACK_ALLOWED_USERS"].split(",") == SLACK["allowed_users"]
    assert env["SLACK_HOME_CHANNEL"] == SLACK["home_channel"]["id"]
    assert env["SLACK_HOME_CHANNEL_NAME"] == SLACK["home_channel"]["name"]


def test_it_answers_in_the_home_channel_alone() -> None:
    """Messages from any other channel are dropped before mention gating runs;
    1:1 DMs are exempt (v2026.9.24 `allowed_channels`)."""
    assert _env(**TOKENS)["SLACK_ALLOWED_CHANNELS"] == SLACK["home_channel"]["id"]


def test_the_tokens_reach_the_env_file_only() -> None:
    env = _env(**TOKENS)
    assert env["SLACK_BOT_TOKEN"] == TOKENS["agent_stack_slack_bot_token"]
    assert env["SLACK_APP_TOKEN"] == TOKENS["agent_stack_slack_app_token"]
    # A tripwire, not a check of this change: neither file names a token today.
    for name in ("hermes-config.yaml.j2", "compose-hermes.yml.j2"):
        rendered = _render(name, **TOKENS)
        assert not [t for t in TOKENS.values() if t in rendered], name


def test_an_unknown_dm_is_dropped_not_answered_with_a_pairing_code() -> None:
    """A pairing approval is a grant held in the gateway's state, outside IaC."""
    config = _config(**TOKENS)
    assert config["unauthorized_dm_behavior"] == "ignore"
    assert config["slack"]["unauthorized_dm_behavior"] == "ignore"


def test_a_top_level_channel_message_needs_a_mention() -> None:
    assert _config(**TOKENS)["slack"]["require_mention"] is True


# --------------------------------------------------------------------------- the provision


def test_the_playbook_reads_both_tokens_from_prods_vault() -> None:
    playbook = (ROLE.parents[1] / "playbooks/provision-ace2.yml").read_text()
    for name in ("slack_bot_token", "slack_app_token"):
        assert (
            f"agent_stack_{name}: \"{{{{ gitea_secrets.apps.services.ai.hermes_kubelab.{name} | default('') }}}}\""
            in playbook
        )


def test_every_provision_proves_the_gateway_connected_to_slack() -> None:
    [probe] = [t for t in _tasks() if t.get("name") == "Verify the gateway is connected to Slack"]
    assert probe["when"] == "agent_stack_slack_configured | bool"
    assert probe["no_log"] is True
    assert probe["ansible.builtin.uri"]["url"].endswith("/health/detailed")
    assert "get('platforms', {}).get('slack', {})).get('state') == 'connected'" in probe["until"]
    names = [t.get("name", "") for t in _tasks()]
    assert names.index("Verify the Hermes API answers with its key") < names.index(
        "Verify the gateway is connected to Slack"
    )
