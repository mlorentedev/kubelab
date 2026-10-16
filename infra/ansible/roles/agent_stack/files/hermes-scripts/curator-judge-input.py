#!/usr/bin/env python3
"""The curator judge's input (spec AI-012 AC6, part 6b).

Runs inside the gateway before the judge's turn. The analyzer wrote its candidates to
`<zone>/curator/candidates.json`, a file of tens of kilobytes, while Hermes injects a
script's output cut at 8000 characters: printing the file would have the judge rule on a
silently truncated list. So this prints the candidates that still need a verdict, trimmed
to fit, most recurrent first, and says how many it left out.

A candidate that already has a proposal in `<zone>/proposals/` is done. The id changes when
a new occurrence joins the cluster, so a fresh recurrence is judged again. With nothing
left the last line is {"wakeAgent": false}, and Hermes skips the turn and the token spend.

A missing candidates file means the analyzer never ran: that is a failure of the job, not a
quiet week.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

BUDGET = 7000
EXCERPTS = 3
EXCERPT_CHARS = 280
ID = re.compile(r"^[0-9a-f]{10}$")
NOTHING = '{"wakeAgent": false}'


def _trim(candidate: dict) -> dict:
    excerpts = []
    for item in (candidate.get("excerpts") or [])[:EXCERPTS]:
        text = " ".join(str(item.get("excerpt", "")).split())
        excerpts.append(
            {
                "source": item.get("source", ""),
                "date": item.get("date", ""),
                "excerpt": text if len(text) <= EXCERPT_CHARS else text[:EXCERPT_CHARS] + "...",
            }
        )
    return {
        "id": candidate["id"],
        "occurrences": candidate.get("occurrences"),
        "dates": candidate.get("dates", []),
        "theme": candidate.get("theme"),
        "excerpts": excerpts,
    }


def report(zone: Path) -> str:
    source = zone / "curator" / "candidates.json"
    if not source.is_file():
        raise FileNotFoundError(f"{source} does not exist: the analyzer has not run")
    candidates = json.loads(source.read_text(encoding="utf-8")).get("candidates", [])
    proposals = zone / "proposals"
    pending = [c for c in candidates if ID.match(str(c.get("id", ""))) and not (proposals / f"{c['id']}.md").exists()]
    if not pending:
        return f"No candidate without a proposal.\n{NOTHING}"

    shown: list[dict] = []
    for candidate in pending:
        trial = [*shown, _trim(candidate)]
        if len(json.dumps({"candidates": trial}, ensure_ascii=False)) > BUDGET:
            break
        shown = trial
    if not shown:  # one candidate alone over the budget: still judge it, with one excerpt
        shown = [{**_trim(pending[0]), "excerpts": _trim(pending[0])["excerpts"][:1]}]
    out = {"candidates": shown}
    if len(shown) < len(pending):
        out["not_shown"] = len(pending) - len(shown)
    return json.dumps(out, ensure_ascii=False)


def main() -> int:
    zone = os.environ.get("HERMES_VAULT_ZONE")
    if not zone:
        print("curator-judge-input: HERMES_VAULT_ZONE is not set (no vault in this gateway)", file=sys.stderr)
        return 1
    try:
        print(report(Path(zone)))
    except (OSError, ValueError) as error:
        print(f"curator-judge-input: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
