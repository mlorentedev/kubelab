#!/usr/bin/env python3
"""Plan the `hermes cron` calls that make the gateway's jobs match the declared ones
(spec AI-012 AC4).

Run by the agent_stack role inside the gateway container, as the gateway's own user,
with this file on stdin so it never lands where the agent can write:

    python3 - plan --state <HERMES_HOME>/cron/jobs.json --declared '<json>'

It only reads. It prints the actions as JSON, and the role runs each one through the
CLI, which holds the job store's lock; writing jobs.json directly would race the
scheduler. Standard library only: the image's Python is the one that runs it.

An agent job may name a script too: its stdout is injected into the turn, and a last
line of {"wakeAgent": false} (or no output) skips the turn altogether.

A job belongs to the role when its name starts with `name_prefix`. Nothing else is
ever edited, resumed or removed, however alike it looks to a declared job.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MODES = ("agent", "script")
KEY = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SCRIPT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
EVERY = re.compile(r"^every (\d+)([mhd])$")
MINUTES = {"m": 1, "h": 60, "d": 1440}

# What a declared job fixes, compared with what Hermes stored.
MANAGED = ("schedule", "prompt", "script", "no_agent", "skills", "model", "provider", "deliver", "failure_deliver")


def _schedule(text: object) -> tuple[str, object]:
    """('cron', expr) or ('interval', minutes): the two forms a declaration may use."""
    value = str(text).strip()
    every = EVERY.match(value)
    if every:
        return ("interval", int(every.group(1)) * MINUTES[every.group(2)])
    if len(value.split()) == 5:
        return ("cron", " ".join(value.split()))
    raise ValueError(f"schedule {text!r} is neither a five-field cron expression nor 'every <n>m|h|d'")


def _stored_schedule(record: dict) -> tuple[str, object]:
    schedule = record.get("schedule") or {}
    if schedule.get("kind") == "cron":
        return ("cron", schedule.get("expr"))
    if schedule.get("kind") == "interval":
        return ("interval", schedule.get("minutes"))
    return (str(schedule.get("kind")), schedule.get("display"))


def _desired(declared: dict, key: str, job: dict) -> dict:
    where = f"job {key!r}"
    if not KEY.match(key):
        raise ValueError(f"{where}: the key must be lowercase letters, digits and dashes")
    mode = job.get("mode")
    if mode not in MODES:
        raise ValueError(f"{where}: mode must be one of {MODES}, not {mode!r}")
    prompt = str(job.get("prompt") or "").strip()
    script = job.get("script")
    if mode == "agent" and not prompt:
        raise ValueError(f"{where}: an agent job needs a prompt")
    if mode == "script" and not script:
        raise ValueError(f"{where}: a script job needs a script")
    if script and not (SCRIPT.match(str(script)) and ".." not in str(script)):
        raise ValueError(f"{where}: script must be a bare file name under HERMES_HOME/scripts")
    model, provider = job.get("model"), job.get("provider")
    if bool(model) != bool(provider):
        raise ValueError(f"{where}: model and provider are declared together or not at all")
    deliver = job.get("deliver") or declared["default_deliver"]
    schedule_text = str(job.get("schedule", "")).strip()
    return {
        "name": f"{declared['name_prefix']}{key}",
        "schedule_text": schedule_text,
        "schedule": _schedule(schedule_text),
        "prompt": prompt if mode == "agent" else "",
        "script": str(script) if script else None,
        "no_agent": mode == "script",
        "skills": list(job.get("skills") or []),
        "model": model or None,
        "provider": provider or None,
        "deliver": deliver,
        "failure_deliver": job.get("failure_deliver") or deliver,
    }


def _stored(record: dict) -> dict:
    return {
        "schedule": _stored_schedule(record),
        "prompt": record.get("prompt") or "",
        "script": record.get("script") or None,
        "no_agent": bool(record.get("no_agent")),
        "skills": list(record.get("skills") or []),
        "model": record.get("model") or None,
        "provider": record.get("provider") or None,
        "deliver": record.get("deliver"),
        "failure_deliver": record.get("failure_deliver"),
    }


def _create(want: dict) -> list[str]:
    argv = ["cron", "create", "--name", want["name"], "--deliver", want["deliver"]]
    argv += ["--failure-deliver", want["failure_deliver"]]
    for skill in want["skills"]:
        argv += ["--skill", skill]
    if want["script"]:
        argv += ["--script", want["script"]]
    if want["no_agent"]:
        argv.append("--no-agent")
    if want["model"]:
        argv += ["--model", want["model"], "--provider", want["provider"]]
    argv.append(want["schedule_text"])
    if not want["no_agent"]:
        argv.append(want["prompt"])
    return argv


def _edit(job_id: str, want: dict, have: dict) -> list[str]:
    """`edit` leaves what it is not told about, so every managed field is stated, a
    cleared one with its empty value."""
    argv = ["cron", "edit", job_id, "--schedule", want["schedule_text"]]
    argv += ["--deliver", want["deliver"], "--failure-deliver", want["failure_deliver"]]
    if want["prompt"] or have["prompt"]:
        argv += ["--prompt", want["prompt"]]
    if want["skills"]:
        for skill in want["skills"]:
            argv += ["--skill", skill]
    else:
        argv.append("--clear-skills")
    argv += ["--script", want["script"] or "", "--no-agent" if want["no_agent"] else "--agent"]
    argv += ["--model", want["model"] or "", "--provider", want["provider"] or ""]
    return argv


def plan(declared: dict, state_jobs: list[dict]) -> list[dict]:
    """Removals first, then each declared job in key order."""
    prefix = declared["name_prefix"]
    owned: dict[str, dict] = {}
    for record in state_jobs:
        name = record.get("name") or ""
        if not name.startswith(prefix):
            continue
        if name in owned:
            raise ValueError(f"more than one job is named {name!r} (ids {owned[name]['id']}, {record['id']})")
        owned[name] = record

    wanted = {key: _desired(declared, key, job) for key, job in declared["jobs"].items()}
    names = {want["name"] for want in wanted.values()}

    actions = [
        {"op": "remove", "name": name, "id": record["id"], "argv": ["cron", "remove", record["id"]]}
        for name, record in sorted(owned.items())
        if name not in names
    ]
    for key in sorted(wanted):
        want = wanted[key]
        record = owned.get(want["name"])
        if record is None:
            actions.append({"op": "create", "name": want["name"], "id": None, "argv": _create(want)})
            continue
        have = _stored(record)
        if any(have[field] != want[field] for field in MANAGED):
            actions.append(
                {"op": "edit", "name": want["name"], "id": record["id"], "argv": _edit(record["id"], want, have)}
            )
        if record.get("enabled") is False:
            actions.append(
                {"op": "resume", "name": want["name"], "id": record["id"], "argv": ["cron", "resume", record["id"]]}
            )
    return actions


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan"])
    parser.add_argument("--state", required=True, type=Path, help="the gateway's cron/jobs.json")
    parser.add_argument("--declared", required=True, help="the declaration, as JSON")
    args = parser.parse_args(argv)
    try:
        state = json.loads(args.state.read_text())["jobs"] if args.state.exists() else []
        actions = plan(json.loads(args.declared), state)
    except (ValueError, KeyError) as error:
        print(f"hermes-jobs: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"actions": actions}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
