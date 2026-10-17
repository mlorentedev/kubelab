---
id: lesson-408-a-bounded-query-answers-about-its-bound-not-the-collection
type: lesson
status: active
created: "2026-08-28"
owner: manu
category: process-method
tags: [kubelab, process-method, verification, tooling, secrets]
---

# A bounded query answers about its bound, and its answer is indistinguishable from data

**Context**: TOOL-035 (#1076), establishing a baseline for a repository migration and registering
the credential that performs it. Two unrelated measurements went wrong the same way inside one
session.

**Problem**: Both produced a plausible number from a query that could not have produced any other.

1. **A baseline that was the page size.** `gh issue list --repo mlorentedev/resume --state open
   --limit 20` returned 20 items, recorded as "20 open issues". The real figure is **28**. The query
   was structurally incapable of returning more than 20, so the 20 was a fact about the flag, not
   about the repository. It went into the spec as the number AC3 would verify the migration
   against — a check that would have passed while eight issues were missing.

2. **A credential report that read one file.** `toolkit secrets check-expiry` announced
   `apps.services.core.gitea.github_migration_token  declared PROVIDER but absent from SOPS` about a
   token that had authenticated against GitHub minutes earlier and reported an expiry of 2026-10-27.
   Both expiry reports resolved values through `ConfigurationManager("common")` alone, so every
   provider-issued credential stored per environment was invisible. The sibling caller, `secrets
   audit`, had the same defect and skipped the secret with **no output at all** — the same wrong
   answer, silently.

Neither looked like an error. A count and a status line are exactly what a working query returns,
and both erred toward reassurance: fewer issues to migrate, one less credential to worry about.

**Solution**: Recount by paginating to exhaustion, and record the correction beside the number so the
next reader sees why it is trustworthy. For the report, search every SOPS file rather than one:

```
before:  ...github_migration_token   declared PROVIDER but absent from SOPS
after:   ...github_migration_token   expires 2026-10-27  (59d)
```

The search was split into a pure `dig_across(configs, path)` so the fix has a test that needs no
decryption — `tests/test_secret_expiry_lookup.py`, with the control showing the old shape returns
`''` and the new one finds the value. `SecretSpec.envs` is the audit dimension and not the storage
location (ANSIBLE-033), so the catalog cannot be asked which file holds a value; searching all of
them is the only correct answer, and it also keeps `check-expiry` — which takes no `--env` — right by
construction.

**Rule**: When a count equals a limit you passed, you measured the limit. When a lookup reports
absence, establish that it looked where the thing is before believing it. Both are the same
question — *could this query have returned a different answer?* — and it is worth asking precisely
when the answer is convenient. A number that becomes a baseline deserves it twice, because every
later check inherits the error and reports green.

The corollary for tooling: a report that cannot find a value must distinguish **"I looked and it is
not there"** from **"I did not look there"**. Collapsing the two is how a credential-expiry control
comes to say *absent* about a working credential, which is worse than saying nothing — it is a
control actively arguing that nothing is wrong.

**Tags**: `#verification` `#secrets` `#tooling` `#issue-1076` `#issue-1485`
