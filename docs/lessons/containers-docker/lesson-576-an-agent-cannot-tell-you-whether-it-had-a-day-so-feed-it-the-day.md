---
id: "lesson-576-an-agent-cannot-tell-you-whether-it-had-a-day-so-feed-it-the-day"
type: lesson
status: active
title: "A scheduled agent cannot say whether there was activity to record, so the job feeds it the activity"
created: "2026-10-15"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, hermes, cron, ai-012]
---

# A scheduled agent cannot say whether there was activity to record, so the job feeds it the activity

**Context**: AI-012 PR 4 declared a daily session record for hermes-kubelab. The prompt told the agent to check whether the operator had talked to it in the last 24 hours, reply `[SILENT]` if not, and otherwise write the record.

**Problem**: Run live on ace2 against a day with a real Slack conversation, the job answered `[SILENT]`. The agent's tools see the vault; the record of its own conversations is `state.db` in `HERMES_HOME`, which the sandbox does not mount. Asked a question only that file can answer, it answered "nothing", which reads as a quiet day rather than as a failure. The run was `ok`, delivered nothing and cost a turn.

**Solution**: Give the job a pre-run script. Hermes injects an agent job's script stdout into the turn (cut at 8000 characters), and a last line of `{"wakeAgent": false}` skips the turn, the delivery and the spend. `session-activity.py` reads `state.db` read-only inside the gateway, drops automated sessions, redacts credentials and prints the conversations; the prompt now says "the script output above lists the conversations". The same run on the same day wrote `sessions/2026-10-15-auto.md` and the next sync committed it.

**Rule**: Never ask a scheduled agent a question about data it has no tool for; collect the data in a pre-run script and let the gate end the run when there is none. A job that "worked" with a plausible empty answer is the failure to look for: prove such a job on a day that has activity, not on a day that does not.

**Tags**: `#hermes` `#cron` `#ai-012`
