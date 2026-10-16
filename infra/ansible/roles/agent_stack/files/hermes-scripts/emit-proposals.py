#!/usr/bin/env python3
"""The curator's proposals (spec AI-012 AC6, part 6b): the judge's verdicts as drafts.

A no-agent job that runs after the judge. The judge is an agent job, and Hermes keeps each
run in `cron/output/<job id>/<time>.md`: the prompt, the pre-run script's output and the
response. This reads the latest run of the judge (named on the record's first line), takes the
verdicts from its response, and writes one draft per RECURRENCE to
`<zone>/proposals/<candidate id>.md`, which the vault sync commits. The evidence comes from
`curator/candidates.json`, joined by the candidate's id, and not from the record: lesson
excerpts contain code fences, and a fence is what delimits the record's script output.

Nothing here infers. The judge is a language model, so its output is data: an id that is not
ten hex digits, a label other than RECURRENCE, or an id the analyzer did not produce is
ignored, and a draft is only ever created, never replaced (a human may be mid-triage).
Printing nothing sends nothing, which is what a week without a new recurrence should do.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# The record's first line names the job. The prompt is no signature to look for: Hermes puts
# the pre-run script's output into it, lesson excerpts hold `## ` lines that end the section
# early, and a session record can mention the judge in the conversation it summarises.
JUDGE_TITLE = "# Cron Job: kubelab:curator-judge"
ID = re.compile(r"^[0-9a-f]{10}$")
RUN_TIME = re.compile(r"\*\*Run Time:\*\*\s*(\d{4}-\d{2}-\d{2})")
FENCE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.DOTALL)
PLACEMENTS = {"pattern": 4, "runbook": 4, "check": 3, "none": 4}  # suggested tier; a human confirms
CONFIDENCE = ("high", "medium", "low")


def _section(record: str, header: str, last: bool = False) -> str | None:
    """The text under `## <header>` up to the next `## ` line. The response is the record's
    last section, and the script output above it can hold a `## ` line of its own (lesson
    excerpts do), so the response is looked up from the end."""
    found = re.findall(rf"(?m)^## {re.escape(header)}[ \t]*\n(.*?)(?=^## |\Z)", record, re.DOTALL)
    if not found:
        return None
    return found[-1] if last else found[0]


def latest_judge_record(output: Path) -> Path | None:
    best: tuple[float, Path] | None = None
    for path in output.glob("*/*.md"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            mtime = path.stat().st_mtime
        except OSError:
            continue
        titled = text.startswith(JUDGE_TITLE + "\n")
        if titled and _section(text, "Response", last=True) is not None and (best is None or mtime > best[0]):
            best = (mtime, path)
    return best[1] if best else None


def verdicts(record: str) -> list[dict]:
    """The response's verdicts; anything that is not the expected JSON is no verdict."""
    response = (_section(record, "Response", last=True) or "").strip()
    fenced = FENCE.search(response)
    text = fenced.group(1) if fenced else response
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        listed = json.loads(text[start : end + 1]).get("verdicts", [])
    except (ValueError, AttributeError):
        return []
    return [v for v in listed if isinstance(v, dict)] if isinstance(listed, list) else []


def render(candidate: dict, verdict: dict, run_date: str, run_file: str) -> str:
    placement = verdict.get("placement") if verdict.get("placement") in PLACEMENTS else "none"
    confidence = verdict.get("confidence") if verdict.get("confidence") in CONFIDENCE else "low"
    cause = " ".join(str(verdict.get("root_cause", "")).split())
    dates, sources = candidate.get("dates", []), candidate.get("sources", [])
    occurrences = candidate.get("occurrences", len(sources))
    title = (cause[:80] or "recurrence candidate").rstrip(".")
    lines = [
        "---",
        f"candidate_id: {json.dumps(candidate['id'])}",
        "status: pending",
        f"created: {json.dumps(run_date)}",
        f"judge_run: {json.dumps(run_file)}",
        "label: RECURRENCE",
        f"confidence: {confidence}",
        f"root_cause: {json.dumps(cause, ensure_ascii=False)}",
        f"placement: {placement}",
        f"tier_target: {PLACEMENTS[placement]}",
        f"occurrences: {int(occurrences)}",
        f"dates: {json.dumps(dates)}",
        f"sources: {json.dumps(sources, ensure_ascii=False)}",
        "issue:",
        "disposed_as:",
        "owner: manu",
        "---",
        "",
        f"# {title}",
        "",
        f"**Root cause (judge):** {cause}",
        "",
        f"**Why promote:** recurred across {occurrences} distinct incidents ({', '.join(map(str, dates))}).",
        "",
        "## Evidence",
    ]
    for item in candidate.get("excerpts", []):
        text = " ".join(str(item.get("excerpt", "")).split())
        lines.append(f"- `{item.get('source', '')}` ({item.get('date', '')}): {text}")
    lines += [
        "",
        "## Disposition (human gate)",
        "Triage with `dispose-proposals`: promote, keep, merge or wontfix.",
        "",
    ]
    return "\n".join(lines)


def create(path: Path, body: str) -> bool:
    """Create `path` with `body` unless it exists, whole or not at all. 0644, because the
    gateway's user is not the sync user's, and a file only its owner reads fails the add."""
    staging = path.with_name(f".{path.name}.tmp")
    descriptor = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o644)
        handle.write(body)
    try:
        os.link(staging, path)  # fails if it exists: a draft is never replaced
    except FileExistsError:
        return False
    finally:
        staging.unlink(missing_ok=True)
    return True


def emit(output: Path, zone: Path) -> list[str]:
    record_path = latest_judge_record(output)
    if record_path is None:
        return []
    record = record_path.read_text(encoding="utf-8", errors="replace")
    stamp = RUN_TIME.search(record)
    run_date = stamp.group(1) if stamp else ""
    source = zone / "curator" / "candidates.json"
    try:
        candidates = {str(c.get("id")): c for c in json.loads(source.read_text(encoding="utf-8")).get("candidates", [])}
    except (OSError, ValueError):
        return []
    proposals = zone / "proposals"
    written = []
    for verdict in verdicts(record):
        cid = str(verdict.get("id", ""))
        if str(verdict.get("label", "")).upper() != "RECURRENCE" or not ID.match(cid) or cid not in candidates:
            continue
        proposals.mkdir(exist_ok=True)
        if create(proposals / f"{cid}.md", render(candidates[cid], verdict, run_date, record_path.name)):
            written.append(cid)
    return written


def main() -> int:
    home, zone = os.environ.get("HERMES_HOME"), os.environ.get("HERMES_VAULT_ZONE")
    if not home or not zone:
        print("emit-proposals: HERMES_HOME and HERMES_VAULT_ZONE are required", file=sys.stderr)
        return 1
    written = emit(Path(home) / "cron" / "output", Path(zone))
    if written:
        print(f"Curator: {len(written)} proposal draft(s) in 80_agents/hermes-kubelab/proposals/")
        for cid in written:
            print(f"  + {cid}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
