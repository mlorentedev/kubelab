---
id: lesson-400-a-settled-question-can-answer-how-without-asking-at-what-cost
type: lesson
status: active
created: "2026-08-26"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, gitea, specs, adr-062]
---

# A settled question can answer "how" without asking "at what cost", and the spec builds on it anyway

**Context**: AUTH-004's R4 asked *how is login prohibited on a bot account?* and
was settled on 2026-08-23 with a real answer: not through the CLI, which has no
such subcommand, but through `PATCH /api/v1/admin/users/{username}` with
`prohibit_login: true`. It even derived the provisioning order from the API
shape — the field is in `EditUserOption` and not in `CreateUserOption`, so the
account cannot be created already blocked: create, then PATCH, then mint.

Part 3 was then written against that settled answer, and its acceptance
criterion asks for an account that is **blocked** and a scoped token that
**works**.

**Problem**: R4 never asked whether the token survives the block. It does not.
Measured in both directions, twice, the second time on an account verified clean:

| `prohibit_login` | `GET /api/v1/user` with the token |
|---|---|
| 0 | **200** |
| 1 | **403** |
| 0 | **200** (restored) |

`prohibit_login: true` disables API **token** authentication as well as the login
form. So the two halves of AC5 are mutually exclusive on Gitea 1.25.5, and the
criterion was unachievable from the day it was written — not because anyone
guessed, but because a correctly-settled question had a scope narrower than the
thing it was used to justify.

The alternative was tested rather than assumed: binding the account to the
Authelia auth source keeps the token alive, but Gitea still accepts a **local**
password on a source-bound account (`change-password` returns rc=0). That is
omission, not enforcement — the very distinction R4 itself drew when it rejected
"simply never declaring the bot in Authelia".

**Solution**: ADR-062 D5 already prescribes the answer for a tier a service
cannot enforce: record it as a **named gap**, not a silent pass. The flag is
driven to `false`, and what actually stands between a person and the account is
stated plainly — a random creation password nobody holds or stored, absence from
Authelia, no administrative scope. **None of those is Gitea refusing a login**,
and saying so is the point. A test pins it, because setting the flag back to
`true` yields a dead credential and a provisioning run that still reports
success.

**Rule**: When a spec cites a settled question as its foundation, check that the
question's *scope* covers what is being built on it. "How do I do X" and "what
does doing X cost me" are different questions, and settling the first reads like
settling both. The tell is a criterion that asks for two properties at once:
**demonstrate them together, early, before the implementation assumes they
compose.** Here "blocked account" and "working token" were each demonstrable
alone and impossible together, and nothing would have surfaced that until the
evidence run.

Corollary for the record: a settled question that turns out to be incomplete gets
an **addendum with its transcript**, not a quiet edit. A superseded settlement
with no record is how lesson-256 spent three months recommending a mechanism that
had already failed.

**Tags**: `#gitea` `#specs` `#adr-062` `#least-privilege` `#pr-1437`
