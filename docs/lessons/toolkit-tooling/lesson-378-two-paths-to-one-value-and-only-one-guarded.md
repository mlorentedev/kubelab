---
id: lesson-378-two-paths-to-one-value-and-only-one-guarded
type: lesson
status: active
created: "2026-08-23"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, secrets, guardrails, testing]
---

# When two commands reach the same value, the guard on one is not a guard

**Context**: Checking whether a new `secrets rotate` verb duplicated the
existing `secrets init --rotate KEY`. It did not — but reading both paths side
by side exposed a latent defect neither was filed for.

**Problem**: `credentials generate` has always refused to overwrite the four
`IMMUTABLE_SECRETS` — values that encrypt or sign state that still exists.
`init_machine_secrets` reaches the same keys and **never consulted that list**.

The three facts had to line up, and they did:

1. All four immutable secrets are `kind=RANDOM_TOKEN`.
2. `RANDOM_TOKEN` is a kind `init` regenerates.
3. `--force` and `--rotate` deliberately bypass the idempotency check that was
   the only thing standing in the way.

Measured against prod, dry-run:

```
$ toolkit secrets init --env prod --force --dry-run
[INFO] Would generate 19 secrets:
[INFO]   apps.services.security.authelia.storage_encryption_key
[INFO]   apps.services.security.authelia.session_secret
```

Running it for real does not rotate a credential. It makes Authelia's SQLite
database unreadable and takes every registered second factor with it — and the
failure surfaces at the next login, not at the command.

**The tests were on the wrong side.** `TestInitIdempotent` asserted that
`--force` regenerates `session_secret` and that a missing
`storage_encryption_key` gets generated. Its fixture selected subjects by `kind`
alone, so it had been handed the immutable keys and had encoded the defect as
expected behaviour. Closing the hole turned three green tests red.

**Solution**: `init` now imports the same `IMMUTABLE_SECRETS` rather than
restating it — a second copy drifts the moment either side changes, and it
drifts in the direction that looks safe. `--force` preserves them with a warning
per key; naming one in `--rotate` refuses the **entire run** rather than quietly
doing the safe subset, because whoever asked is acting on a belief about what
that key is, and a partial success leaves the belief intact. The test fixture
now excludes them in the helper, so a future immutable entry cannot silently
become a subject again.

**Rule**: A guardrail protects a code path, not a value. When more than one
command can write the same thing, ask which of them enforces the rule — the
answer is often "the one you happened to read". And when a fix turns a test red,
the question is never how to make it pass: it is which of the two describes the
behaviour you want. A test can be the place a bug lives.

**Tags**: `#secrets` `#guardrails` `#testing` `#pr-1349`
