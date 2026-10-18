---
id: lesson-595-an-hourly-job-that-reports-state-repeats-a-standing-problem-and-fills-the-gaps-it-cannot-see-with-guesses
type: lesson
status: active
title: "An hourly job that reports state repeats a standing problem, and fills the gaps it cannot see with guesses"
created: "2026-10-18"
owner: manu
category: observability
tags: [kubelab, observability, hermes, alerts, slack]
---

# An hourly job that reports state repeats a standing problem, and fills the gaps it cannot see with guesses

**Context**: `kubelab:alert-triage` reads the fleet's alert channels every hour and the agent summarises them (AI-012, #2080).

**Problem**: Two faults, both read in `#agent-fleet` on 2026-10-17. (1) A condition that lasted a day, the script missing its Slack token, produced 15 near-identical reports in a row; Grafana reposting one firing alert every 15 minutes would do the same. (2) When the agent could not see something (a script error, a placeholder instead of a message) it filled the gap: it told the operator to run `manage_connections`, to set `HERMES_SLACK_BOT_TOKEN`, and called two alerts about different pull requests "duplicate pings".

**Solution**: The script keeps a memory of what it handed to the agent: a hash of each alert (channel plus text with clock times removed, so a repost with a new "Started:" still matches, while a different PR number does not) and the same for an unreadable channel and for its own misconfiguration. A match inside six hours is left out and counted; nothing new means `{"wakeAgent": false}`. The file holds hashes only, lives under `HERMES_HOME/state` (found from the scripts mount when Hermes scrubs the variable), and a memory that cannot be read or written only costs a repeat. An item is marked reported only when it is printed, so one cut by the output budget is not lost. The prompt now says that different identifiers are different problems, that a script failure is quoted and not explained, and that the agent has no Slack tool and cannot see the configuration.

**Rule**: A job that reports state needs a memory of what it reported, or its volume is the duration of the problem; say it once and remind on a schedule. Tell a model what it cannot see: an unstated blind spot gets filled with plausible, wrong advice. The same shape as lesson-594 for failed units.

**Tags**: `#hermes` `#alerts` `#dedup`
