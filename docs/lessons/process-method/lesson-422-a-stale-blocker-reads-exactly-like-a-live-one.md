---
id: lesson-422-a-stale-blocker-reads-exactly-like-a-live-one
type: lesson
status: active
created: "2026-09-04"
owner: manu
category: process-method
tags: [kubelab, process-method, verification, observability, credentials]
---

# A stale blocker reads exactly like a live one, so nobody retries what a comment says is impossible

**Context**: Two Grafana alerts had been arriving in Slack for ten days, and
`make alerts` — the command `CLAUDE.md` names as the way to start any fleet work —
answered `HTTP 401` against prod. It was failing correctly: `#1377` had made it
raise rather than render an unanswered question as "all healthy". But while it
401s there is no session-time view of prod alerting at all, which is how two
alerts ran for days without anyone establishing what they were.

`SECRET_CATALOG` explained the 401, in a comment written when the entry was added:

```python
# Prod token minting is blocked by #951 (prod admin credential rejected).
# Staging carries a real value; prod will not until #951 closes, and
# `make secrets-audit` will correctly report that as a gap until then.
```

**Problem**: Measured on prod, that credential answers `200`.

```
admin                     -> 401
manu                      -> 200
operator                  -> 401
$GF_SECURITY_ADMIN_USER   -> 200
```

`#951`'s second half — Grafana's local admin username drifting from the Secret —
had **healed** at some point. The database holds `manu`, which is exactly what
the `grafana-admin` Secret declares and what `apps.auth.identities.superadmin`
says. Declared and actual agree.

Nothing recorded that it had healed. So a note describing a real block in August
was still being read as current in September, and the chain it anchored — issue
open, credential rejected, token unmintable, absent from `prod.enc.yaml`,
`apply_secrets` refusing the whole Secret, `make alerts` 401 — was broken at its
first link and nobody had looked. The service account was genuinely absent
(`GET /api/serviceaccounts/search` returned none), which is consistent with the
minting having been blocked when the note was written **and with nobody having
retried since**.

The comment was the only reason anyone believed prod could not have the token.
It was load-bearing, and it was wrong.

**Solution**: Retry the blocked operation instead of reading about it. Minting
`obs-alerts-ro` took one call, and `make alerts` answered for the first time:

```
--- Active Grafana Alerts ---
[FIRING] CrowdSec automated perimeter IP ban surge (Severity: info)
```

`make secrets-audit ENV=prod` went to **79/79**, closing the gap the same comment
predicted. The comment was replaced with the finding rather than with "no longer
blocked", because the next reader needs the method, not the status.

**Rule**: **Establish a block by consequence before repeating one you read.** A
comment, a ticket, or a handoff note describing a blocker records a measurement
taken once, at a moment that has passed; nothing re-measures it and nothing
expires it. The failure is silent in the reassuring direction — a condition that
heals produces no event, so the note outlives it and reads identically to a live
one. Cost here: ten days of unread alerts behind a fixed problem.

This is the same shape as the guard that asserts a weaker claim than it appears
to ([lesson-413](../identity-secrets/lesson-413-a-credential-can-exist-authenticate-and-not-work.md),
[lesson-416](../ci-automation/lesson-416-a-guard-the-guard-must-assert-on-the-derived-artifact.md))
seen from the other side: there, a check passes while the capability is dead;
here, a note says the capability is dead while it works. Both are answered by the same
question — *what would this still be true of?* — and both are settled by running
the operation and reading the exit status.

Corollary for whoever writes the note: a blocker comment should name **the
command that would disprove it**, so the next reader can spend thirty seconds
instead of inheriting a belief.

**Tags**: `#verification` `#credentials` `#observability` `#pr-1607` `#issue-1583`
`#issue-951`
