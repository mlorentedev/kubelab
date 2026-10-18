#!/usr/bin/env python3
"""What the fleet's alert channels said in the last hours (spec AI-012 AC8).

The data for the hourly triage. It runs inside the gateway before the job's turn,
because the gateway holds the Slack bot token and the agent's tools do not: the
token is read from the gateway's environment and never reaches the output. It is read
as `HERMES_ALERT_SLACK_TOKEN`, a second name for the bot token, because Hermes strips
`SLACK_BOT_TOKEN` from every job script's environment (lesson-592). Hermes
injects the output into the turn and cuts it at 8000 characters, so the report
stays under that.

`HERMES_ALERT_CHANNELS` is `<id>:<name>,...`, from `slack.alert_channels` in
common.yaml. `SLACK_ALLOWED_CHANNELS` governs what the agent answers and not this
read (measured on ace2, 2026-10-16). With nothing to triage the last line is
{"wakeAgent": false}, and Hermes skips the turn and the token spend. A channel that
cannot be read is reported in the output and never counts as quiet.

A problem is said once and then again every six hours while it lasts (#2423 did the
same for the fleet's failed units): a message whose text matches one already handed to
the agent inside that window is left out, so a persistent alert, or a persistent
misconfiguration of this very script, does not become a report an hour. The memory is a
small file under `HERMES_HOME/state`; without one the script reports everything.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

WINDOW = 3600  # the job runs hourly
LIMIT = 100
MESSAGE_CHARS = 400
BUDGET = 7000
REPEAT = 6 * 3600  # a problem already reported is said again after this long
NOTHING = '{"wakeAgent": false}'
API = "https://slack.com/api/conversations.history"
# A credential in an alert must not reach the digest or the vault.
SECRETS = re.compile(
    r"sk-[A-Za-z0-9_-]{20,}|xox[a-z]-[A-Za-z0-9-]{10,}|gh[pousr]_[A-Za-z0-9]{30,}"
    r"|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|authelia_(?:at|rt|ac)_[A-Za-z0-9._-]+"
    r"|glsa_[A-Za-z0-9_]+|(?i:bearer)\s+[A-Za-z0-9._~+/-]{20,}"
    r"|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
)


# Clock times differ between two posts of one alert ("Started: 2026-10-18 04:21:20 +0000 UTC")
# and say nothing about which problem it is; PR numbers, hosts and apps do, and stay.
TIMES = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?(?: ?[+-]\d{4})?(?: UTC)?|\b\d{2}:\d{2}:\d{2}\b")


def _fingerprint(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode(), usedforsecurity=False).hexdigest()[:16]


def load_seen(path: Path | None, now: float) -> dict[str, float]:
    """Fingerprint -> when it was last handed to the agent, inside the window; empty when unreadable."""
    if path is None:
        return {}
    try:
        raw = json.loads(path.read_text())
        return {k: float(v) for k, v in raw.items() if now - float(v) < REPEAT}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def save_seen(path: Path | None, seen: dict[str, float]) -> None:
    """Best effort: a memory that cannot be written costs a repeated report, never a lost one."""
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(seen))
        tmp.replace(path)
    except OSError:
        pass


def _is_new(seen: dict[str, float] | None, key: str, now: float) -> bool:
    """True when `key` was not reported inside the window. Marking it is the caller's, once it is shown."""
    last = None if seen is None else seen.get(key)
    return last is None or now - last >= REPEAT


def channels(raw: str) -> list[tuple[str, str]]:
    """(id, name) pairs; a malformed entry is skipped, an empty list is the caller's to report."""
    pairs = []
    for entry in raw.split(","):
        ident, _, name = entry.strip().partition(":")
        if ident:
            pairs.append((ident, name or ident))
    return pairs


def _redact(text: object) -> str:
    return " ".join(SECRETS.sub("[redacted]", str(text)).split())


def _clean(text: object) -> str:
    one_line = _redact(text)
    return one_line if len(one_line) <= MESSAGE_CHARS else one_line[:MESSAGE_CHARS] + "..."


def _block_texts(blocks: object) -> list[str]:
    """The readable strings of Block Kit blocks: header and section text, section fields, context elements."""
    out: list[str] = []
    for block in blocks if isinstance(blocks, list) else []:
        if not isinstance(block, dict):
            continue
        for item in [block.get("text"), *(block.get("fields") or []), *(block.get("elements") or [])]:
            if isinstance(item, dict) and item.get("text"):
                out.append(str(item["text"]))
    return out


def _text(message: dict) -> str:
    """An alert's body: the text, else what its attachments and blocks say (Grafana, CI and Argo CD post those).
    Slack's `fallback` is a last resort: for a blocks-only attachment it is the placeholder "[no preview available]"."""
    parts = [message.get("text") or "", *_block_texts(message.get("blocks"))]
    for attachment in message.get("attachments") or []:
        body = [attachment.get("title") or "", attachment.get("text") or "", *_block_texts(attachment.get("blocks"))]
        parts += body if any(body) else [attachment.get("fallback") or ""]
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


def report(
    token: str, pairs: list[tuple[str, str]], now: float, read=fetch, seen: dict[str, float] | None = None
) -> str:
    """The hour's report. `seen` is the memory of what was already said: it is read and updated in place."""
    stamp = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d %H:%M UTC")
    sections: list[tuple[str, list[tuple[str, str]]]] = []
    marks: list[str] = []
    unreadable: list[str] = []
    repeated = 0
    pending: set[str] = set()  # fingerprints already in this report
    for ident, name in pairs:
        try:
            messages = read(token, ident, now - WINDOW)
        except (OSError, RuntimeError, ValueError) as error:  # urllib.error.URLError is an OSError
            key = _fingerprint("unreadable", ident, type(error).__name__)
            if key not in pending and _is_new(seen, key, now):
                pending.add(key)
                marks.append(key)
                unreadable.append(
                    f"#{name} ({ident}): cannot be read ({_clean(type(error).__name__ + ': ' + str(error))})"
                )
            else:
                repeated += 1
            continue
        lines = []
        for message in sorted(messages, key=lambda m: float(m.get("ts", 0))):
            full = _redact(_text(message))
            body = _clean(full)
            # The fingerprint reads the whole text, not the 400 characters shown: the part that tells two
            # alerts apart can come after the cut. A copy already in this report counts as said.
            key = _fingerprint(ident, TIMES.sub("", full))
            if body and (key in pending or not _is_new(seen, key, now)):
                repeated += 1
            elif body:
                pending.add(key)
                when = datetime.fromtimestamp(float(message.get("ts", 0)), UTC).strftime("%H:%M")
                lines.append((key, f"- {when} {body}"))
        if lines:
            sections.append((name, lines))

    if not sections and not unreadable:
        return f"No new alert in the last hour.\n{NOTHING}"

    out = [f"Alert channels, the hour before {stamp}.", *unreadable]
    if repeated:
        out.append(
            f"({repeated} more message(s) repeat something shown here or reported in the last "
            f"{REPEAT // 3600} hours and are left out.)"
        )
    used = sum(len(line) + 1 for line in out)
    for name, lines in sections:
        out += ["", f"## #{name}"]
        used += len(name) + 5
        for index, (key, line) in enumerate(lines):
            if used + len(line) + 1 > BUDGET:
                left = len(lines) - index
                out.append(f"({left} more in #{name} not shown)")
                break
            out.append(line)
            marks.append(key)
            used += len(line) + 1
    if seen is not None:
        seen.update(dict.fromkeys(marks, now))
    return "\n".join(out)


def _state_path() -> Path | None:
    """`HERMES_HOME/state/alert-activity.json`. A job script's environment is scrubbed, so when HERMES_HOME
    does not arrive, the home is where the role mounts this directory: `<home>/scripts/`."""
    home = os.environ.get("HERMES_HOME", "")
    if not home:
        here = Path(__file__).resolve().parent
        home = str(here.parent) if here.name == "scripts" else ""
    return Path(home) / "state" / "alert-activity.json" if home else None


def main() -> int:
    token = os.environ.get("HERMES_ALERT_SLACK_TOKEN", "")
    pairs = channels(os.environ.get("HERMES_ALERT_CHANNELS", ""))
    now = time.time()
    path = _state_path()
    seen = load_seen(path, now)
    if not token or not pairs:
        # Said once, then every REPEAT: an hourly copy of one configuration error is noise.
        key = _fingerprint("misconfigured")
        if not _is_new(seen, key, now):
            print(f"alert-activity: still not configured (reported earlier).\n{NOTHING}")
            return 0
        seen[key] = now
        save_seen(path, seen)
        print("alert-activity: no Slack token or no alert channel configured; the triage cannot run.")
        return 1
    text = report(token, pairs, now, seen=seen)
    save_seen(path, seen)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
