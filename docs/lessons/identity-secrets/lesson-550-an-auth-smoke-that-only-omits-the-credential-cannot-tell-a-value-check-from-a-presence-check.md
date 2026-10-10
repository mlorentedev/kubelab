---
id: lesson-550-an-auth-smoke-that-only-omits-the-credential-cannot-tell-a-value-check-from-a-presence-check
type: lesson
status: active
created: "2026-10-10"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, n8n, notifications, testing]
---

# An auth smoke that only omits the credential cannot tell a value check from a presence check

**Context**: NOTIFY-001's criterion #4 reads "a POST missing or with a wrong
shared secret is rejected". `make notify-smoke ENV=staging` proved it with one
negative probe, a POST with no `Authorization` header, which got 403. The
criterion was ticked green on 2026-06-16 on that run.

**Problem**: Both halves of the gate refuse a request with no header. A gate
that compares the value refuses it, and so does one that only checks the header
is there. The smoke answered 403 against either, so it proved half of the
criterion while reading as all of it. That lasted four months, until the spec
audit on 2026-10-10 compared the probe list with the criterion's wording.

**Solution**: The smoke now sends a fourth probe: `Bearer` plus a random value,
built fresh each run so it can never equal the real secret, and never printed.
`tests/test_notify_smoke.py` runs it against a fake webhook that accepts any
header value, and expects the smoke to fail.
`make mutate`, which made the wrong probe send the real secret, went red. Live
on staging, 2026-10-10T08:56Z: page 200, log 200, no header 403, wrong secret 403.

**Rule**: The negative probe that proves an auth gate is the refused request
that looks most like an accepted one: the same header, the same scheme, a wrong
value. Omitting the credential tests that the gate exists, not that it compares.
When a criterion names several refusals, give each its own probe and check them
against the criterion's words, not against "the auth test passed".

**Tags**: `#auth` `#smoke-test` `#notify-001`
