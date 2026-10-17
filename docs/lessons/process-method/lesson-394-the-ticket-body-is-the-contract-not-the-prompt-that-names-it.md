---
id: lesson-394-the-ticket-body-is-the-contract-not-the-prompt-that-names-it
type: lesson
status: active
created: "2026-08-25"
owner: manu
category: process-method
tags: [kubelab, process-method, governance, board]
---

# The ticket body is the contract; the prompt that names it is not

**Context**: #823 (GOV-002, backlog triage) was picked up from a session prompt that framed the work as "restore signal to the board" and said what to measure first. The ticket was read by title only.

**Problem**: The ticket body, written on 2026-07-02, carried its own list and acceptance criteria — close four PIVOT calendar tickets, collapse BACKUP-* into epics, fix five ID collisions, a priority on every issue, under 60 open. None of it was seen until the PR reviewer quoted it back as "partially compliant". The session delivered a different, agreed scope, and the ticket would have been closed against criteria nobody had checked. Measured while reconciling: the five collisions had become sixteen.

**Solution**: Read the ticket body before the prompt's framing of it, on the first tool call. When they diverge, reconcile on the ticket: here the body was rewritten to the agreed criterion with the original preserved under `<details>`, and every item of the old list was re-homed (#1414, #1416, #1417) or dropped with a written reason.

**Rule**: A prompt says what to do today; the ticket says what "done" means. Read both before measuring anything, and when they disagree, the disagreement is the first finding to record, not the last.

**Tags**: `#process` `#board` `#issue-823` `#pr-1415`
