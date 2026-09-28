---
id: lesson-474-a-client-that-mocks-itself-when-unconfigured-reports-success-it-never-had
type: lesson
status: active
created: "2026-09-24"
owner: manu
category: observability
tags: [kubelab, observability, slack, false-green, triage]
---

# A client that mocks itself when unconfigured reports a success it never had

**Context**: The operator asked, during the 2026-09-24 backup-health audit, how
an agent could read the Slack alert channels. ADR-064 and
`runbook-agentic-observability-and-triage.md` §C both said that
`toolkit obs slack` does that: "Reading and Replying to Slack".

**Problem**: It reads nothing, and both of its outputs claim something that
did not happen:

- Without `--post`, the CLI prints `Slack channel #alerts connected (Ready for
  triage posting).` It makes no API call. The word "connected" is a string
  literal.
- `SlackSreClient.post_message()` with no `SLACK_BOT_TOKEN` logs a "mock" line
  and returns `{"ok": True, "mock": True}`. The CLI checks only `ok`, so it
  prints `✓ Message posted`. Nothing was sent.

There is no `conversations.history` call anywhere. The same day, the prod
`pvc-backup` CronJob had failed every night for a month while `make alerts`
answered "No firing or pending alerts". Some failure paths only reach Slack,
and the tool documented as the way to read Slack had never read it.

**Solution**: #1829 (OBS-031) owns the fix: a read path, a token in
`SECRET_CATALOG`, and an unconfigured client that fails loudly. Until then,
the runbook's §C says plainly that there is no read path, and that neither
output is evidence.

**Rule**: A dev-convenience mock inside a production client must never answer
with the production success shape. Return `ok: False` with the reason, or
raise. A caller that checks `ok` cannot see a `mock` field it does not know
about. A status line such as "connected" has to be the result of a call. When
a doc describes a capability, run the capability before trusting the doc:
here the source said "read" and no read existed in the code.

**Tags**: `#false-green` `#slack` `#issue-1829` `#adr-064`
