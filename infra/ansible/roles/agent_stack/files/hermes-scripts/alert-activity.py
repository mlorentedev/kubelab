#!/usr/bin/env python3
"""What the fleet's alert channels said in the last hours (spec AI-012 AC8).

The data for the hourly triage. It runs inside the gateway before the job's turn,
because the gateway holds the Slack bot token and the agent's tools do not: the
token is read from the gateway's environment and never reaches the output. Hermes
injects the output into the turn and cuts it at 8000 characters, so the report
stays under that.

`HERMES_ALERT_CHANNELS` is `<id>:<name>,...`, from `slack.alert_channels` in
common.yaml. `SLACK_ALLOWED_CHANNELS` governs what the agent answers and not this
read (measured on ace2, 2026-10-16). With nothing to triage the last line is
{"wakeAgent": false}, and Hermes skips the turn and the token spend. A channel that
cannot be read is reported in the output and never counts as quiet.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

WINDOW = 3600  # the job runs hourly
LIMIT = 100
MESSAGE_CHARS = 400
BUDGET = 7000
NOTHING = '{"wakeAgent": false}'
API = "https://slack.com/api/conversations.history"
# A credential in an alert must not reach the digest or the vault.
SECRETS = re.compile(
    r"sk-[A-Za-z0-9_-]{20,}|xox[a-z]-[A-Za-z0-9-]{10,}|gh[pousr]_[A-Za-z0-9]{30,}"
    r"|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|authelia_(?:at|rt|ac)_[A-Za-z0-9._-]+"
    r"|glsa_[A-Za-z0-9_]+|(?i:bearer)\s+[A-Za-z0-9._~+/-]{20,}"
    r"|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
)


def channels(raw: str) -> list[tuple[str, str]]:
    """(id, name) pairs; a malformed entry is skipped, an empty list is the caller's to report."""
    pairs = []
    for entry in raw.split(","):
        ident, _, name = entry.strip().partition(":")
        if ident:
            pairs.append((ident, name or ident))
    return pairs


def _clean(text: object) -> str:
    one_line = " ".join(SECRETS.sub("[redacted]", str(text)).split())
    return one_line if len(one_line) <= MESSAGE_CHARS else one_line[:MESSAGE_CHARS] + "..."


def _text(message: dict) -> str:
    """An alert's body: the text, else what its attachments say (Grafana and CI post those)."""
    parts = [message.get("text") or ""]
    for attachment in message.get("attachments") or []:
        parts += [attachment.get("title") or "", attachment.get("text") or attachment.get("fallback") or ""]
    return " ".join(part for part in parts if part)


def fetch(token: str, channel: str, oldest: float) -> list[dict]:
    """The channel's messages since `oldest`, newest first; raises on any Slack or network error."""
    query = urllib.parse.urlencode({"channel": channel, "oldest": f"{oldest:.6f}", "limit": LIMIT})
    request = urllib.request.Request(f"{API}?{query}", headers={"Authorization": f"Bearer {token}"})  # noqa: S310 (fixed https URL)
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
        body = json.load(response)
    if not body.get("ok"):
        raise RuntimeError(str(body.get("error", "unknown error")))
    return body.get("messages", [])


def report(token: str, pairs: list[tuple[str, str]], now: float, read=fetch) -> str:
    stamp = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d %H:%M UTC")
    sections: list[tuple[str, list[str]]] = []
    unreadable: list[str] = []
    for ident, name in pairs:
        try:
            messages = read(token, ident, now - WINDOW)
        except (OSError, RuntimeError, ValueError) as error:  # urllib.error.URLError is an OSError
            unreadable.append(f"#{name} ({ident}): cannot be read ({_clean(type(error).__name__ + ': ' + str(error))})")
            continue
        lines = []
        for message in sorted(messages, key=lambda m: float(m.get("ts", 0))):
            body = _clean(_text(message))
            if body:
                when = datetime.fromtimestamp(float(message.get("ts", 0)), UTC).strftime("%H:%M")
                lines.append(f"- {when} {body}")
        if lines:
            sections.append((name, lines))

    if not sections and not unreadable:
        return f"No alert in the last hour.\n{NOTHING}"

    out = [f"Alert channels, the hour before {stamp}.", *unreadable]
    used = sum(len(line) + 1 for line in out)
    for name, lines in sections:
        out += ["", f"## #{name}"]
        used += len(name) + 5
        for index, line in enumerate(lines):
            if used + len(line) + 1 > BUDGET:
                left = len(lines) - index
                out.append(f"({left} more in #{name} not shown)")
                break
            out.append(line)
            used += len(line) + 1
    return "\n".join(out)


def main() -> int:
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    pairs = channels(os.environ.get("HERMES_ALERT_CHANNELS", ""))
    if not token or not pairs:
        print("alert-activity: no Slack token or no alert channel configured; the triage cannot run.")
        return 1
    print(report(token, pairs, time.time()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
