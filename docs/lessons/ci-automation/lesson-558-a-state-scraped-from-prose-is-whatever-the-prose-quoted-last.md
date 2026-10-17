---
id: "lesson-558-a-state-scraped-from-prose-is-whatever-the-prose-quoted-last"
type: lesson
status: active
title: "A state scraped from prose is whatever the prose quoted last"
created: "2026-10-11"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, review-attestation, parsing]
---

# A state scraped from prose is whatever the prose quoted last

**Context**: `review-attestation` publishes a commit status whose wording depends on the classifier's state. `attested` and `disclosed` both exit 0, so the workflow had to recover which one it was.

**Problem**: The workflow took the last state word anywhere in the classifier's log (`grep -oE '\b(attested|...|declined|pending)\b' | tail -n 1`). The `disclosed` message explains itself by naming the reviewer that declined: `disclosed — no review ran (coderabbitai declined)`. The last match was `declined`, the disclosed branch never matched, and the status fell through to "a review happened" on #2206, a PR declared unreviewed. The publish step had tests; they read only its wording, never where its input came from, so they stayed green.

**Solution**: The classifier writes its state to `--state-file`, and the workflow reads that file (#2208). A CLI test runs #2206's payload and expects `disclosed`. A workflow test fails if the Classify step greps state words again.

**Rule**: When a program's output is both a message for people and an input for a machine, give the machine its own channel: a file, an exit code, or one dedicated line. Messages explain themselves by quoting neighbouring states, so a regex over them returns whichever state the explanation mentioned. Test the value a decision consumes at its source, not only the decision's branches.

**Tags**: `#ci` `#review-attestation` `#pr-2206` `#issue-2208`
